#!/usr/bin/env python3
"""Critically evaluate and *walk-forward test* compact v5 parameter changes.

This is deliberately not a brute-force hunt for the best full-sample result.
It uses three chronological windows:

* development: 2019-09 through 2022-12 (parameter selection only);
* validation: 2023-01 through 2024-12 (not used for selection);
* holdout: 2025-01 onward (not used for selection or confirmation).

The script mirrors the current closed-candle paper model and reports every
candidate. A candidate is never recommended merely because it looks good on
the development slice. No external numerical packages are required.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import config
from backtest_v5_csv import Bar, WilderIndicators, load_csv_parts


@dataclass(frozen=True)
class Parameters:
    z_entry: float = 2.2
    adx_max: float = 18.0
    sl_atr: float = 2.5
    tp_r: float = 2.0
    session_start: int = 7
    session_end: int = 17
    require_turn: bool = True
    be_r: Optional[float] = None

    def label(self) -> str:
        turn = "turn" if self.require_turn else "no-turn"
        be = "off" if self.be_r is None else f"BE{self.be_r:g}R"
        return (
            f"Z{self.z_entry:g}|ADX≤{self.adx_max:g}|SL{self.sl_atr:g}ATR|"
            f"TP{self.tp_r:g}R|{self.session_start:02d}-{self.session_end:02d}|{turn}|{be}"
        )


@dataclass(frozen=True)
class Feature:
    index: int
    bar: Bar
    atr: float
    atr_avg: float
    adx: float
    zscore: float
    bullish_turn: bool
    bearish_turn: bool


@dataclass
class Position:
    opened_at: datetime
    direction: str
    entry: float
    stop: float
    target: float
    size: float
    entry_fee: float
    sl_distance: float
    be_r: Optional[float]
    be_armed: bool = False


@dataclass
class Result:
    params: Parameters
    window: str
    trades: int
    wins: int
    losses: int
    final_balance: float
    net_pnl: float
    return_pct: float
    pf: Optional[float]
    max_dd: float
    fees: float

    def row(self) -> Dict[str, object]:
        row = asdict(self.params)
        row.update(
            {
                "label": self.params.label(),
                "window": self.window,
                "trades": self.trades,
                "wins": self.wins,
                "losses": self.losses,
                "final_balance": round(self.final_balance, 4),
                "net_pnl": round(self.net_pnl, 4),
                "return_pct": round(self.return_pct, 4),
                "profit_factor": self.pf,
                "max_realized_dd": round(self.max_dd, 4),
                "fees": round(self.fees, 4),
            }
        )
        return row


def build_features(bars: Sequence[Bar]) -> List[Feature]:
    indicator = WilderIndicators(config.ATR_PERIOD, config.ZSCORE_PERIOD, config.ATR_AVG_LOOKBACK)
    features: List[Feature] = []
    for index, bar in enumerate(bars):
        values = indicator.update(bar)
        if not values or index < 300:
            continue
        # The two closes immediately before the signal bar are known at close.
        prior_close = bars[index - 1].close
        prior_close_2 = bars[index - 2].close
        features.append(
            Feature(
                index=index,
                bar=bar,
                atr=float(values["atr_14"]),
                atr_avg=float(values["atr_avg"]),
                adx=float(values["adx"]),
                zscore=float(values["zscore"]),
                bullish_turn=bar.close > bar.open and prior_close <= prior_close_2,
                bearish_turn=bar.close < bar.open and prior_close >= prior_close_2,
            )
        )
    return features


def candidate_direction(feature: Feature, params: Parameters, spread: float) -> Optional[Tuple[str, float]]:
    """Apply every live entry gate except account-state guards."""
    hour = feature.bar.timestamp.hour
    if not params.session_start <= hour < params.session_end:
        return None
    if feature.atr < config.MIN_ATR_USD or feature.atr_avg <= 0:
        return None
    atr_ratio = feature.atr / feature.atr_avg
    if not config.ATR_VS_AVG_MIN <= atr_ratio <= config.ATR_VS_AVG_MAX:
        return None
    sl_distance = max(config.MIN_SL_USD, round(feature.atr * params.sl_atr, 2))
    round_trip_cost = max(spread * 2.0, config.ROUND_TRIP_COST_USD)
    if sl_distance < round_trip_cost * config.MIN_SL_COST_MULTIPLE:
        return None
    if sl_distance * params.tp_r < round_trip_cost * config.MIN_TP_COST_MULTIPLE:
        return None
    if feature.adx > params.adx_max:
        return None
    if feature.zscore <= -params.z_entry and (not params.require_turn or feature.bullish_turn):
        return "LONG", sl_distance
    if feature.zscore >= params.z_entry and (not params.require_turn or feature.bearish_turn):
        return "SHORT", sl_distance
    return None


def open_position(
    feature: Feature, direction: str, sl_distance: float, params: Parameters, balance: float, spread: float
) -> Optional[Position]:
    half_spread = spread / 2.0
    entry = (
        feature.bar.close + half_spread + config.PAPER_SLIPPAGE_USD
        if direction == "LONG"
        else feature.bar.close - half_spread - config.PAPER_SLIPPAGE_USD
    )
    risk_dollars = balance * config.RISK_PER_TRADE_PCT / 100.0
    if risk_dollars < 0.40 or entry <= 0:
        return None
    size = max(0.01, round(risk_dollars / sl_distance, 4))
    margin_cap = balance * config.MARGIN_CAP_PCT / 100.0
    margin = entry * size / config.MAX_LEVERAGE
    if margin > margin_cap:
        size = round(margin_cap * config.MAX_LEVERAGE / entry, 4)
        if size < 0.01:
            return None
        margin = entry * size / config.MAX_LEVERAGE
    entry_fee = entry * size * config.PAPER_TAKER_FEE_RATE
    if margin + entry_fee > balance:
        return None
    if direction == "LONG":
        stop, target = entry - sl_distance, entry + sl_distance * params.tp_r
    else:
        stop, target = entry + sl_distance, entry - sl_distance * params.tp_r
    return Position(feature.bar.timestamp, direction, entry, stop, target, size, entry_fee, sl_distance, params.be_r)


def close_on_bar(position: Position, bar: Bar, spread: float) -> Optional[Tuple[float, str]]:
    """Exact conservative execution order: SL, TP, then optional BE arm."""
    half_spread = spread / 2.0
    if position.direction == "LONG":
        executable_high, executable_low = bar.high - half_spread, bar.low - half_spread
        if executable_low <= position.stop:
            reason = "BE_STOP" if position.be_armed and position.stop >= position.entry else "SL_HIT"
            return min(position.stop, executable_low) - config.PAPER_SLIPPAGE_USD, reason
        if executable_high >= position.target:
            return position.target - config.PAPER_SLIPPAGE_USD, "TP_HIT"
        if (
            position.be_r is not None
            and not position.be_armed
            and executable_high >= position.entry + position.sl_distance * position.be_r
        ):
            position.stop, position.be_armed = position.entry, True
    else:
        executable_high, executable_low = bar.high + half_spread, bar.low + half_spread
        if executable_high >= position.stop:
            reason = "BE_STOP" if position.be_armed and position.stop <= position.entry else "SL_HIT"
            return max(position.stop, executable_high) + config.PAPER_SLIPPAGE_USD, reason
        if executable_low <= position.target:
            return position.target + config.PAPER_SLIPPAGE_USD, "TP_HIT"
        if (
            position.be_r is not None
            and not position.be_armed
            and executable_low <= position.entry - position.sl_distance * position.be_r
        ):
            position.stop, position.be_armed = position.entry, True
    return None


def in_window(timestamp: datetime, start: datetime, end: Optional[datetime]) -> bool:
    return timestamp >= start and (end is None or timestamp < end)


def simulate(
    features: Iterable[Feature], params: Parameters, start: datetime, end: Optional[datetime], spread: float, name: str
) -> Result:
    initial = float(config.INITIAL_BALANCE_USDT)
    balance = peak = initial
    max_dd = 0.0
    fees = 0.0
    gross_profit = gross_loss = 0.0
    wins = losses = 0
    daily_count: Dict[str, int] = {}
    daily_pnl: Dict[str, float] = {}
    cooldown_until: Optional[datetime] = None
    position: Optional[Position] = None

    for feature in features:
        bar = feature.bar
        if not in_window(bar.timestamp, start, end):
            continue
        if position:
            outcome = close_on_bar(position, bar, spread)
            if outcome:
                exit_price, _reason = outcome
                gross = (
                    (exit_price - position.entry) * position.size
                    if position.direction == "LONG"
                    else (position.entry - exit_price) * position.size
                )
                exit_fee = exit_price * position.size * config.PAPER_TAKER_FEE_RATE
                net = gross - position.entry_fee - exit_fee
                balance = max(0.0, balance + net)
                fees += position.entry_fee + exit_fee
                if net > 0:
                    wins += 1
                    gross_profit += net
                elif net < 0:
                    losses += 1
                    gross_loss += abs(net)
                peak = max(peak, balance)
                max_dd = max(max_dd, peak - balance)
                date_key = bar.timestamp.strftime("%Y-%m-%d")
                daily_pnl[date_key] = daily_pnl.get(date_key, 0.0) + net
                cooldown_seconds = config.LOSS_COOLDOWN_SECONDS if net < 0 else config.ENTRY_COOLDOWN_SECONDS
                cooldown_until = bar.timestamp + timedelta(seconds=cooldown_seconds)
                position = None
        if position or balance < 5:
            continue
        date_key = bar.timestamp.strftime("%Y-%m-%d")
        if cooldown_until and bar.timestamp < cooldown_until:
            continue
        if daily_count.get(date_key, 0) >= config.MAX_TRADES_PER_DAY:
            continue
        if daily_pnl.get(date_key, 0.0) <= -initial * config.MAX_DAILY_LOSS_PCT / 100.0:
            continue
        signal = candidate_direction(feature, params, spread)
        if not signal:
            continue
        direction, distance = signal
        position = open_position(feature, direction, distance, params, balance, spread)
        if position:
            daily_count[date_key] = daily_count.get(date_key, 0) + 1

    trades = wins + losses
    return Result(
        params=params,
        window=name,
        trades=trades,
        wins=wins,
        losses=losses,
        final_balance=balance,
        net_pnl=balance - initial,
        return_pct=(balance / initial - 1.0) * 100.0,
        pf=(gross_profit / gross_loss) if gross_loss else None,
        max_dd=max_dd,
        fees=fees,
    )


def rank_development(results: Sequence[Result]) -> List[Result]:
    """Rank without allowing tiny samples or loss-free one-trade PFs to win."""
    def score(result: Result) -> Tuple[float, float, int]:
        if result.trades < 8:
            return (-1_000_000.0, result.net_pnl, result.trades)
        pf = result.pf if result.pf is not None else 0.0
        return (pf, result.net_pnl, result.trades)

    return sorted(results, key=score, reverse=True)


def write_csv(path: Path, results: Sequence[Result]) -> None:
    rows = [result.row() for result in results]
    with path.open("w", newline="", encoding="utf-8") as handle:
        fields = list(rows[0]) if rows else []
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def markdown_table(results: Sequence[Result], limit: int = 10) -> List[str]:
    lines = [
        "| Candidate | Trades | Final | Return | PF | DD |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for result in results[:limit]:
        pf = f"{result.pf:.2f}" if result.pf is not None else "n/a"
        lines.append(
            f"| `{result.params.label()}` | {result.trades} | ${result.final_balance:.2f} | "
            f"{result.return_pct:+.2f}% | {pf} | ${result.max_dd:.2f} |"
        )
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", nargs="+", help="CSV part paths or shell globs")
    parser.add_argument("--spread", type=float, default=0.40)
    parser.add_argument("--report", default="V5_PARAMETER_RESEARCH.md")
    parser.add_argument("--results-csv", default="V5_PARAMETER_RESEARCH.csv")
    parser.add_argument("--data-revision", default="")
    args = parser.parse_args()
    if args.spread < 0:
        parser.error("--spread must be non-negative")

    bars = load_csv_parts(args.csv)
    features = build_features(bars)
    windows = {
        "Development (2019-09 to 2022-12)": (
            datetime(2019, 9, 6, tzinfo=timezone.utc),
            datetime(2023, 1, 1, tzinfo=timezone.utc),
        ),
        "Validation (2023-2024)": (
            datetime(2023, 1, 1, tzinfo=timezone.utc),
            datetime(2025, 1, 1, tzinfo=timezone.utc),
        ),
        "Holdout (2025 onward)": (datetime(2025, 1, 1, tzinfo=timezone.utc), None),
    }
    baseline = Parameters()

    # Step 1: pre-registered regime/entry threshold alternatives.
    stage1_params = [
        baseline,
        Parameters(z_entry=2.4),
        Parameters(z_entry=2.6),
        Parameters(z_entry=2.8),
        Parameters(adx_max=14.0),
        Parameters(z_entry=2.4, adx_max=14.0),
        Parameters(z_entry=2.6, adx_max=14.0),
        Parameters(adx_max=20.0),
        Parameters(z_entry=2.4, adx_max=20.0),
    ]
    dev_start, dev_end = windows["Development (2019-09 to 2022-12)"]
    stage1_dev = [
        simulate(features, params, dev_start, dev_end, args.spread, "Development") for params in stage1_params
    ]
    stage1_ranked = rank_development(stage1_dev)
    stage1_winner = stage1_ranked[0].params

    # Step 2: session alternatives, selected only on the same explicitly named
    # development set. This is an exploratory pass, not validation evidence.
    stage2_params = [
        Parameters(**{**asdict(stage1_winner), "session_start": start, "session_end": end})
        for start, end in [(7, 17), (7, 12), (12, 17), (12, 16), (13, 17), (8, 16)]
    ]
    stage2_dev = [
        simulate(features, params, dev_start, dev_end, args.spread, "Development") for params in stage2_params
    ]
    stage2_ranked = rank_development(stage2_dev)
    stage2_winner = stage2_ranked[0].params

    # Step 3: exits / breakeven. Early BE is included as a falsifiable test,
    # not presumed beneficial.
    stage3_params = []
    for sl_atr, tp_r, be_r in [
        (2.0, 1.5, None), (2.0, 2.0, None), (2.5, 1.0, None),
        (2.5, 1.5, None), (2.5, 2.0, None), (3.0, 1.0, None),
        (3.0, 1.5, None), (3.0, 2.0, None), (2.5, 2.0, 1.0),
        (2.5, 2.0, 1.5), (3.0, 1.5, 1.0),
    ]:
        stage3_params.append(
            Parameters(
                **{
                    **asdict(stage2_winner),
                    "sl_atr": sl_atr,
                    "tp_r": tp_r,
                    "be_r": be_r,
                }
            )
        )
    stage3_dev = [
        simulate(features, params, dev_start, dev_end, args.spread, "Development") for params in stage3_params
    ]
    stage3_ranked = rank_development(stage3_dev)
    selected = stage3_ranked[0].params

    all_rows: List[Result] = [*stage1_dev, *stage2_dev, *stage3_dev]
    # Re-evaluate only the preselected baseline and selected configuration on
    # validation and holdout. Neither window is used in choosing parameters.
    comparisons: List[Result] = []
    for params, label in ((baseline, "Baseline"), (selected, "Development-selected")):
        for window_name in ("Validation (2023-2024)", "Holdout (2025 onward)"):
            start, end = windows[window_name]
            result = simulate(features, params, start, end, args.spread, f"{label} — {window_name}")
            comparisons.append(result)
            all_rows.append(result)

    write_csv(Path(args.results_csv), all_rows)
    report = [
        "# v5 parameter research — critical walk-forward test",
        "",
        "## Protocol",
        "",
        f"- Data: {len(bars):,} supplied 5-minute bars; source timestamps treated as UTC.",
        f"- Fixed execution assumption: ${args.spread:.2f} spread, ${config.PAPER_SLIPPAGE_USD:.2f} adverse slippage per fill, {config.PAPER_TAKER_FEE_RATE * 100:.02f}% taker fee per side.",
        "- Development window: 2019-09 through 2022-12. Validation and 2025+ holdout were not used to select parameters.",
        "- Rank rule: at least 8 development trades, then profit factor, then net PnL. A candidate with too few trades is not allowed to win on an infinite/undefined PF.",
    ]
    if args.data_revision:
        report.append(f"- Data revision: `{args.data_revision}`.")
    report.extend(["", "## Step 1 — regime and entry threshold candidates", ""])
    report.extend(markdown_table(stage1_ranked))
    report.extend(["", "## Step 2 — session candidates using the step-1 development winner", ""])
    report.extend(markdown_table(stage2_ranked))
    report.extend(["", "## Step 3 — exit and breakeven candidates using the step-2 development winner", ""])
    report.extend(markdown_table(stage3_ranked))
    report.extend(["", "## Frozen comparison on unseen windows", ""])
    report.extend(markdown_table(comparisons, limit=len(comparisons)))
    report.extend(
        [
            "",
            "## Critical interpretation",
            "",
            f"The development-selected candidate is `{selected.label()}`. It must not be treated as deployable unless it has acceptable validation and holdout results with adequate trade counts. "
            "This script is intentionally designed to make overfitting visible rather than hide it.",
            "",
            "[`V5_PARAMETER_RESEARCH.csv`](V5_PARAMETER_RESEARCH.csv) contains every evaluated candidate and window. A negative or very small-sample validation/holdout result is a rejection of the change, not an invitation to keep searching the holdout set.",
        ]
    )
    Path(args.report).write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"Selected on development only: {selected.label()}")
    for result in comparisons:
        print(
            f"{result.window}: trades={result.trades} final=${result.final_balance:.2f} "
            f"return={result.return_pct:+.2f}% PF={result.pf}"
        )


if __name__ == "__main__":
    main()
