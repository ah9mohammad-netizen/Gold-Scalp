#!/usr/bin/env python3
"""Reproducible, closed-candle backtest for the current v5 paper-execution model.

The main branch contains the supplied semicolon-delimited 5-minute CSV parts.
This script does not download data and uses only Python's standard library plus
project modules. It deliberately models the current paper assumptions:

* Z-score/ADX/turn-bar entry on a completed candle;
* one position, session/max-trade/daily-loss/cooldown guards;
* bid/ask + $0.03 adverse slippage and 4 bp **per-side** taker fee;
* stop-first resolution when a subsequent OHLC bar touches both SL and TP.

Example (without checking the data files into this branch):
    mkdir -p /tmp/xau-main
    for f in XAU_5m_data-part-{011,012,013,014,015}.csv; do
      git show origin/main:$f > /tmp/xau-main/$f
    done
    python scripts/backtest_v5_csv.py /tmp/xau-main/XAU_5m_data-part-*.csv

The source CSV has no timezone field. Timestamps are treated as UTC because the
strategy's session filter is configured in UTC. Confirm the source timezone
before treating any result as a venue-specific live expectation.
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import math
import sys
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Deque, Dict, Iterable, List, Optional, Sequence

# ``python scripts/backtest_v5_csv.py`` puts scripts/ on sys.path, not the
# repository root. Add the root without requiring installation as a package.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from app.config import config
from app.engine import engine
from scripts.gap_guard import GapGuard


@dataclass(frozen=True)
class Bar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Position:
    opened_at: datetime
    direction: str
    reference_price: float
    entry: float
    stop: float
    target: float
    size: float
    margin: float
    entry_fee: float
    sl_distance: float
    zscore: float
    adx: float
    atr: float
    atr_ratio: float
    bars_held: int = 0
    mfe_price: float = 0.0
    mae_price: float = 0.0
    mfe_before_exit_price: float = 0.0
    ambiguous_ohlc_exit: bool = False


class WilderIndicators:
    """Streaming indicators equivalent to the live feed after warm-up.

    The live feed asks for 300 bars and runs Wilder calculations over that
    window. A 14-period Wilder seed has negligible influence after 300 bars;
    using a continuous stream avoids an O(bars × 300) backtest while retaining
    the same current-bar/no-look-ahead semantics.
    """

    def __init__(self, period: int = 14, z_period: int = 20, atr_average: int = 50):
        self.period = period
        self.z_period = z_period
        self.closes: Deque[float] = deque(maxlen=z_period)
        self.atr_values: Deque[float] = deque(maxlen=atr_average)
        self.prev_close: Optional[float] = None
        self.prev_high: Optional[float] = None
        self.prev_low: Optional[float] = None
        self.tr_seed: List[float] = []
        self.plus_seed: List[float] = []
        self.minus_seed: List[float] = []
        self.smooth_tr: Optional[float] = None
        self.smooth_plus: Optional[float] = None
        self.smooth_minus: Optional[float] = None
        self.dx_seed: List[float] = []
        self.adx: Optional[float] = None

    def update(self, bar: Bar) -> Optional[Dict[str, float]]:
        self.closes.append(bar.close)
        if self.prev_close is None:
            self.prev_close, self.prev_high, self.prev_low = bar.close, bar.high, bar.low
            return None

        true_range = max(
            bar.high - bar.low,
            abs(bar.high - self.prev_close),
            abs(bar.low - self.prev_close),
        )
        up_move = bar.high - float(self.prev_high)
        down_move = float(self.prev_low) - bar.low
        plus_dm = up_move if up_move > down_move and up_move > 0 else 0.0
        minus_dm = down_move if down_move > up_move and down_move > 0 else 0.0

        if self.smooth_tr is None:
            self.tr_seed.append(true_range)
            self.plus_seed.append(plus_dm)
            self.minus_seed.append(minus_dm)
            if len(self.tr_seed) == self.period:
                self.smooth_tr = sum(self.tr_seed)
                self.smooth_plus = sum(self.plus_seed)
                self.smooth_minus = sum(self.minus_seed)
        else:
            self.smooth_tr = self.smooth_tr - self.smooth_tr / self.period + true_range
            self.smooth_plus = self.smooth_plus - self.smooth_plus / self.period + plus_dm
            self.smooth_minus = self.smooth_minus - self.smooth_minus / self.period + minus_dm

        atr: Optional[float] = None
        plus_di = minus_di = adx = 0.0
        if self.smooth_tr is not None:
            atr = self.smooth_tr / self.period
            self.atr_values.append(atr)
            denom_tr = self.smooth_tr or 1e-12
            plus_di = 100.0 * float(self.smooth_plus) / denom_tr
            minus_di = 100.0 * float(self.smooth_minus) / denom_tr
            dx_denom = plus_di + minus_di
            dx = 100.0 * abs(plus_di - minus_di) / dx_denom if dx_denom else 0.0
            if self.adx is None:
                self.dx_seed.append(dx)
                # This mirrors TechnicalIndicators.calculate_adx's early
                # average before it has a full 14 DX observations.
                adx = sum(self.dx_seed) / len(self.dx_seed)
                if len(self.dx_seed) == self.period:
                    self.adx = adx
            else:
                self.adx = (self.adx * (self.period - 1) + dx) / self.period
                adx = self.adx

        self.prev_close, self.prev_high, self.prev_low = bar.close, bar.high, bar.low
        if atr is None or len(self.closes) < self.z_period or not self.atr_values:
            return None
        sma = sum(self.closes) / len(self.closes)
        variance = sum((close - sma) ** 2 for close in self.closes) / len(self.closes)
        stdev = math.sqrt(variance)
        return {
            "atr_14": atr,
            "atr_avg": sum(self.atr_values) / len(self.atr_values),
            "adx": adx,
            "plus_di": plus_di,
            "minus_di": minus_di,
            "sma_z": sma,
            "stdev_z": stdev,
            "zscore": (bar.close - sma) / stdev if stdev > 1e-12 else 0.0,
        }


def load_csv_parts(patterns: Sequence[str]) -> List[Bar]:
    paths: List[Path] = []
    for pattern in patterns:
        matches = [Path(item) for item in glob.glob(pattern)]
        paths.extend(matches or [Path(pattern)])
    unique_paths = sorted({path.resolve() for path in paths})
    bars: List[Bar] = []
    for path in unique_paths:
        if not path.exists():
            raise FileNotFoundError(path)
        with path.open(newline="", encoding="utf-8-sig") as handle:
            # Main-branch source files are semicolon-delimited. Canonical repair
            # output is standard CSV with `timestamp_utc`; support both without
            # ever changing their source-time semantics here.
            preview = handle.read(4096)
            handle.seek(0)
            delimiter = ";" if preview.splitlines()[0].count(";") > 0 else ","
            reader = csv.DictReader(handle, delimiter=delimiter)
            canonical = bool(reader.fieldnames and "timestamp_utc" in reader.fieldnames)
            for row in reader:
                try:
                    if canonical:
                        timestamp = datetime.fromisoformat(
                            row["timestamp_utc"].replace("Z", "+00:00")
                        ).astimezone(timezone.utc)
                        open_key, high_key, low_key, close_key, volume_key = (
                            "open",
                            "high",
                            "low",
                            "close",
                            "volume",
                        )
                    else:
                        timestamp = datetime.strptime(row["Date"], "%Y.%m.%d %H:%M").replace(
                            tzinfo=timezone.utc
                        )
                        open_key, high_key, low_key, close_key, volume_key = (
                            "Open",
                            "High",
                            "Low",
                            "Close",
                            "Volume",
                        )
                    bars.append(
                        Bar(
                            timestamp=timestamp,
                            open=float(row[open_key]),
                            high=float(row[high_key]),
                            low=float(row[low_key]),
                            close=float(row[close_key]),
                            volume=float(row.get(volume_key) or 0.0),
                        )
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError(f"Invalid row in {path}: {row}") from exc
    bars.sort(key=lambda bar: bar.timestamp)
    deduplicated: List[Bar] = []
    seen = set()
    for bar in bars:
        if bar.timestamp not in seen:
            deduplicated.append(bar)
            seen.add(bar.timestamp)
    return deduplicated


def paper_fill(plan: Dict[str, float], bar: Bar, balance: float, spread: float) -> Optional[Position]:
    """Apply the same entry transformation as PaperTradingEngine."""
    reference = float(plan["entry_price"])
    half_spread = spread / 2.0
    entry = (
        reference + half_spread + config.PAPER_SLIPPAGE_USD
        if plan["direction"] == "LONG"
        else reference - half_spread - config.PAPER_SLIPPAGE_USD
    )
    sl_distance = float(plan["sl_distance"])
    target_distance = sl_distance * config.TP_RR_RATIO
    size = float(plan["size_oz"])
    margin = entry * size / config.MAX_LEVERAGE
    entry_fee = entry * size * config.PAPER_TAKER_FEE_RATE
    margin_cap = balance * config.MARGIN_CAP_PCT / 100.0
    if margin > margin_cap:
        size = round(margin_cap * config.MAX_LEVERAGE / entry, 4)
        if size < 0.01:
            return None
        margin = entry * size / config.MAX_LEVERAGE
        entry_fee = entry * size * config.PAPER_TAKER_FEE_RATE
    if entry <= 0 or margin + entry_fee > balance:
        return None
    if plan["direction"] == "LONG":
        stop, target = entry - sl_distance, entry + target_distance
    else:
        stop, target = entry + sl_distance, entry - target_distance
    return Position(
        opened_at=bar.timestamp,
        direction=str(plan["direction"]),
        reference_price=reference,
        entry=entry,
        stop=stop,
        target=target,
        size=size,
        margin=margin,
        entry_fee=entry_fee,
        sl_distance=sl_distance,
        zscore=float(plan.get("zscore", 0.0)),
        adx=float(plan.get("adx", 0.0)),
        atr=float(plan.get("atr_at_entry", 0.0)),
        atr_ratio=float(plan.get("atr_ratio", 0.0)),
    )


def exit_position(position: Position, bar: Bar, spread: float) -> Optional[tuple[float, str]]:
    """Resolve the next candle with bid/ask range and conservative stop priority.

    Excursion fields are updated from executable quotes. ``mfe_before_exit`` is
    deliberately captured before the current bar so it does not invent an
    intrabar path on an OHLC candle that also hit the stop.
    """
    half = spread / 2.0
    position.mfe_before_exit_price = max(position.mfe_before_exit_price, position.mfe_price)
    position.bars_held += 1
    if position.direction == "LONG":
        executable_high, executable_low = bar.high - half, bar.low - half
        favorable, adverse = executable_high - position.entry, position.entry - executable_low
        hit_stop, hit_target = executable_low <= position.stop, executable_high >= position.target
        position.mfe_price = max(position.mfe_price, favorable)
        position.mae_price = max(position.mae_price, adverse)
        position.ambiguous_ohlc_exit = hit_stop and hit_target
        if hit_stop:
            return min(position.stop, executable_low) - config.PAPER_SLIPPAGE_USD, "SL_HIT"
        if hit_target:
            return position.target - config.PAPER_SLIPPAGE_USD, "TP_HIT"
    else:
        executable_high, executable_low = bar.high + half, bar.low + half
        favorable, adverse = position.entry - executable_low, executable_high - position.entry
        hit_stop, hit_target = executable_high >= position.stop, executable_low <= position.target
        position.mfe_price = max(position.mfe_price, favorable)
        position.mae_price = max(position.mae_price, adverse)
        position.ambiguous_ohlc_exit = hit_stop and hit_target
        if hit_stop:
            return max(position.stop, executable_high) + config.PAPER_SLIPPAGE_USD, "SL_HIT"
        if hit_target:
            return position.target + config.PAPER_SLIPPAGE_USD, "TP_HIT"
    return None


def run_window(
    bars: Iterable[Bar],
    start: Optional[datetime],
    end: Optional[datetime],
    spread: float,
    gap_guard: Optional[GapGuard] = None,
) -> Dict[str, object]:
    indicator = WilderIndicators(config.ATR_PERIOD, config.ZSCORE_PERIOD, config.ATR_AVG_LOOKBACK)
    balance = float(config.INITIAL_BALANCE_USDT)
    initial = balance
    peak = balance
    max_drawdown = 0.0
    max_drawdown_pct = 0.0
    position: Optional[Position] = None
    cooldown_until: Optional[datetime] = None
    daily_counts: Dict[str, int] = {}
    daily_pnl: Dict[str, float] = {}
    trades: List[Dict[str, object]] = []
    bars_in_window = 0

    for index, bar in enumerate(bars):
        indicators = indicator.update(bar)
        in_window = (start is None or bar.timestamp >= start) and (end is None or bar.timestamp < end)
        if not in_window:
            continue
        bars_in_window += 1
        if indicators is None or index < 300:
            continue

        # Manage a position first. A new signal cannot use its own OHLC range.
        if position is not None:
            outcome = exit_position(position, bar, spread)
            if outcome is None and gap_guard is not None and gap_guard.force_flat_after(bar.timestamp):
                half = spread / 2.0
                exit_price = (
                    bar.close - half - config.PAPER_SLIPPAGE_USD
                    if position.direction == "LONG"
                    else bar.close + half + config.PAPER_SLIPPAGE_USD
                )
                outcome = (exit_price, "DATA_GAP_EXIT")
            if outcome:
                exit_price, reason = outcome
                gross = (
                    (exit_price - position.entry) * position.size
                    if position.direction == "LONG"
                    else (position.entry - exit_price) * position.size
                )
                exit_fee = exit_price * position.size * config.PAPER_TAKER_FEE_RATE
                net = gross - position.entry_fee - exit_fee
                balance = max(0.0, balance + net)
                peak = max(peak, balance)
                drawdown = peak - balance
                max_drawdown = max(max_drawdown, drawdown)
                max_drawdown_pct = max(max_drawdown_pct, drawdown / peak * 100.0 if peak else 0.0)
                daily_key = bar.timestamp.strftime("%Y-%m-%d")
                daily_pnl[daily_key] = daily_pnl.get(daily_key, 0.0) + net
                cooldown_until = bar.timestamp + timedelta(
                    seconds=(config.LOSS_COOLDOWN_SECONDS if net < 0 else config.ENTRY_COOLDOWN_SECONDS)
                )
                trades.append(
                    {
                        "opened_at": position.opened_at.isoformat(),
                        "closed_at": bar.timestamp.isoformat(),
                        "direction": position.direction,
                        "reference_price": round(position.reference_price, 4),
                        "entry_price": round(position.entry, 4),
                        "exit_price": round(exit_price, 4),
                        "size_oz": position.size,
                        "sl_distance": round(position.sl_distance, 4),
                        "zscore": round(position.zscore, 4),
                        "adx": round(position.adx, 4),
                        "atr": round(position.atr, 4),
                        "atr_ratio": round(position.atr_ratio, 4),
                        "entry_hour_utc": position.opened_at.hour,
                        "turn_confirmed": True,
                        "bars_held": position.bars_held,
                        "mfe_r": round(position.mfe_price / position.sl_distance, 4),
                        "mae_r": round(position.mae_price / position.sl_distance, 4),
                        "mfe_before_exit_r": round(position.mfe_before_exit_price / position.sl_distance, 4),
                        "ambiguous_ohlc_exit": position.ambiguous_ohlc_exit,
                        "stop_overshoot_r": round(
                            max(0.0, position.mae_price / position.sl_distance - 1.0), 4
                        ),
                        "diagnosis_tag": (
                            "TP_CONFIRMED_REVERSAL"
                            if reason == "TP_HIT"
                            else "NO_REVERSAL"
                            if position.mfe_before_exit_price / position.sl_distance < 0.25
                            else "WEAK_REVERSAL"
                            if position.mfe_before_exit_price / position.sl_distance < 0.5
                            else "PARTIAL_REVERSAL"
                            if position.mfe_before_exit_price / position.sl_distance < 1.0
                            else "GAVE_BACK_AFTER_1R"
                        ),
                        "gross_pnl_usd": round(gross, 6),
                        "entry_fee_usd": round(position.entry_fee, 6),
                        "exit_fee_usd": round(exit_fee, 6),
                        "net_pnl_usd": round(net, 6),
                        "exit_reason": reason,
                        "balance_after": round(balance, 6),
                    }
                )
                position = None

        if position is not None or balance < 5.0:
            continue
        if gap_guard is not None and not gap_guard.entry_allowed(bar.timestamp):
            continue
        date_key = bar.timestamp.strftime("%Y-%m-%d")
        if cooldown_until and bar.timestamp < cooldown_until:
            continue
        if daily_counts.get(date_key, 0) >= config.MAX_TRADES_PER_DAY:
            continue
        if daily_pnl.get(date_key, 0.0) <= -initial * config.MAX_DAILY_LOSS_PCT / 100.0:
            continue

        # Call the same decision engine used by the Railway worker.
        # The two prior values are kept by bar list rather than indicator state.
        # Since index >= 300 here, they always exist.
        # NOTE: close data used through this bar; no future values are supplied.
        history = bars_list[index - 2 : index + 1]
        tick = {
            "timestamp": bar.timestamp,
            "bar_timestamp_ms": int(bar.timestamp.timestamp() * 1000),
            "source": "MAIN_BRANCH_CSV",
            "close": bar.close,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "spread": spread,
            **indicators,
            "prev_close": history[-2].close,
            "prev_close_2": history[-3].close,
            "ema_200": bar.close,
            "ema_50": bar.close,
            "ema_21": bar.close,
            "vwap": bar.close,
            "asian_high": bar.high,
            "asian_low": bar.low,
            "asian_range_ready": True,
            "ny_orb_high": 0.0,
            "ny_orb_low": 0.0,
            "ny_orb_ready": False,
        }
        plan = engine.evaluate(tick, balance)
        if plan:
            plan["adx"] = indicators["adx"]
            plan["atr_ratio"] = indicators["atr_14"] / indicators["atr_avg"] if indicators["atr_avg"] else 0.0
            candidate = paper_fill(plan, bar, balance, spread)
            if candidate:
                position = candidate
                daily_counts[date_key] = daily_counts.get(date_key, 0) + 1

    wins = [trade for trade in trades if float(trade["net_pnl_usd"]) > 0]
    losses = [trade for trade in trades if float(trade["net_pnl_usd"]) < 0]
    gross_profit = sum(float(trade["net_pnl_usd"]) for trade in wins)
    gross_loss = abs(sum(float(trade["net_pnl_usd"]) for trade in losses))
    total_fees = sum(float(trade["entry_fee_usd"]) + float(trade["exit_fee_usd"]) for trade in trades)
    return {
        "start": start.isoformat() if start else "first available bar",
        "end_exclusive": end.isoformat() if end else "last available bar",
        "bars_in_window": bars_in_window,
        "initial_balance": round(initial, 4),
        "final_realized_balance": round(balance, 4),
        "net_pnl_usd": round(balance - initial, 4),
        "return_pct": round((balance / initial - 1.0) * 100.0, 4),
        "closed_trades": len(trades),
        "open_position_at_end": position is not None,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(len(wins) / len(trades) * 100.0, 4) if trades else 0.0,
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else None,
        "max_realized_drawdown_usd": round(max_drawdown, 4),
        "max_realized_drawdown_pct": round(max_drawdown_pct, 4),
        "simulated_fees_usd": round(total_fees, 4),
        "trades": trades,
    }


# Set by main before run_window. Keeps the backtest loop simple and avoids copying
# 443k bars to every window invocation.
bars_list: List[Bar] = []


def summary_row(name: str, result: Dict[str, object]) -> str:
    return (
        f"| {name} | {result['bars_in_window']:,} | {result['closed_trades']} | "
        f"${float(result['final_realized_balance']):.2f} | {float(result['return_pct']):+.2f}% | "
        f"{result['profit_factor'] if result['profit_factor'] is not None else 'n/a'} | "
        f"{float(result['win_rate_pct']):.1f}% | ${float(result['max_realized_drawdown_usd']):.2f} | "
        f"${float(result['simulated_fees_usd']):.2f} |"
    )


def write_report(
    path: Path,
    results: Dict[str, Dict[str, object]],
    source_paths: Sequence[str],
    spread: float,
    data_revision: str = "",
) -> None:
    full = results["Full sample"]
    lines = [
        "# XAU 5-minute v5 cost-aware backtest",
        "",
        "## Scope",
        "",
        f"- Source: supplied main-branch CSV parts ({', '.join(Path(source).name for source in source_paths)}).",
    ]
    if data_revision:
        lines.append(f"- Data revision: `{data_revision}`.")
    lines.extend(
        [
            "- Timestamp assumption: source `Date` field is treated as UTC; the CSV does not provide a timezone.",
        "- Entry model: closed-candle signal, then adverse bid/ask fill plus slippage.",
        f"- Friction model: fixed ${spread:.2f} bid/ask spread, ${config.PAPER_SLIPPAGE_USD:.2f} adverse slippage **per fill**, and {config.PAPER_TAKER_FEE_RATE * 100:.02f}% taker fee **per side**.",
        "- Exit model: first subsequent bar only; if stop and target both touch, stop is selected first.",
        "- This is a research backtest of OHLC data, not a claim that the execution contract would have filled identically.",
        "",
        "## Results",
        "",
        "| Window | Bars | Closed trades | Final realized balance | Net return | PF | Net win rate | Max realized DD | Simulated fees |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for name, result in results.items():
        lines.append(summary_row(name, result))
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            f"The full sample closed {full['closed_trades']} trades and ended at ${float(full['final_realized_balance']):.2f}. "
            "This should be treated as a rejection/validation signal, not as a marketing result. "
            "The out-of-sample/recent window is more relevant than an optimized full-sample result.",
            "",
            "Important limitations: the CSV has no bid/ask or funding data, timestamps lack a stated timezone, and the source series may not match the future execution venue's contract/index. "
            "Do not enable live trading based on this report. Forward paper performance and venue-specific fee/fill validation are still required.",
            "",
            "## Machine-readable output",
            "",
            "The companion JSON and trade-audit CSV contain every closed trade with entry/exit, gross PnL, fees, net PnL, Z-score, ADX, excursions, and balance after close.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_trade_audit_csv(path: Path, trades: Sequence[Dict[str, object]]) -> None:
    """Write an analyst-friendly row for every closed full-sample trade."""
    fieldnames = [
        "opened_at",
        "closed_at",
        "direction",
        "entry_hour_utc",
        "zscore",
        "adx",
        "atr",
        "atr_ratio",
        "turn_confirmed",
        "reference_price",
        "entry_price",
        "exit_price",
        "sl_distance",
        "size_oz",
        "bars_held",
        "mfe_r",
        "mfe_before_exit_r",
        "mae_r",
        "ambiguous_ohlc_exit",
        "stop_overshoot_r",
        "diagnosis_tag",
        "exit_reason",
        "gross_pnl_usd",
        "entry_fee_usd",
        "exit_fee_usd",
        "net_pnl_usd",
        "balance_after",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(trades)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", nargs="+", help="CSV part paths or shell-style patterns")
    parser.add_argument("--spread", type=float, default=0.40, help="fixed historical bid/ask spread in USD")
    parser.add_argument(
        "--gap-guard",
        action="store_true",
        help="block entries near non-routine gaps and force-flat before them",
    )
    parser.add_argument("--report", default="BACKTEST_MAIN_HISTORY_V5_COST_AWARE.md")
    parser.add_argument("--json", default="BACKTEST_MAIN_HISTORY_V5_COST_AWARE.json")
    parser.add_argument(
        "--trades-csv",
        default="BACKTEST_MAIN_HISTORY_V5_TRADE_AUDIT.csv",
        help="CSV audit of every closed full-sample trade",
    )
    parser.add_argument(
        "--data-revision",
        default="",
        help="optional Git commit/ref for the input dataset, included in the Markdown report",
    )
    args = parser.parse_args()
    if args.spread < 0:
        parser.error("--spread must be non-negative")

    global bars_list
    bars_list = load_csv_parts(args.csv)
    if len(bars_list) < 301:
        raise RuntimeError("At least 301 bars are required")
    gap_guard = GapGuard(bars_list) if args.gap_guard else None
    windows = {
        "Full sample": (None, None),
        "Mid sample (2022-2023)": (
            datetime(2022, 1, 1, tzinfo=timezone.utc),
            datetime(2024, 1, 1, tzinfo=timezone.utc),
        ),
        "Recent / pseudo-OOS (2025-01 onward)": (
            datetime(2025, 1, 1, tzinfo=timezone.utc),
            None,
        ),
    }
    results = {
        name: run_window(bars_list, start, end, args.spread, gap_guard=gap_guard)
        for name, (start, end) in windows.items()
    }
    write_report(Path(args.report), results, args.csv, args.spread, args.data_revision)
    Path(args.json).write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    write_trade_audit_csv(Path(args.trades_csv), results["Full sample"]["trades"])
    for name, result in results.items():
        print(
            f"{name}: trades={result['closed_trades']} final=${float(result['final_realized_balance']):.2f} "
            f"return={float(result['return_pct']):+.2f}% PF={result['profit_factor']} "
            f"DD=${float(result['max_realized_drawdown_usd']):.2f}"
        )


if __name__ == "__main__":
    main()
