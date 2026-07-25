#!/usr/bin/env python3
"""DST-aware Asian-range / London-session sweep-reclaim research.

The source data timestamps are UTC.  This script compares a legacy fixed-UTC
London window against ``Europe/London`` local-time windows, so UK daylight-saving
changes are applied correctly.  It is a distinct strategy family from v5:

* form a fixed UTC Asian range beginning at 00:00;
* after the range ends, wait for a London-window sweep beyond its high/low;
* require the signal bar to close back inside the range;
* use an ATR/sweep-extreme stop and fixed 2R target;
* one structural trade per UTC day; costs and stop-first OHLC handling retained.

The study selects timing only on 2019-2022 data, then freezes it for validation
and 2025+ holdout. It must not be interpreted as proof of a live edge.
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import config
from scripts.backtest_v5_csv import Bar, WilderIndicators, load_csv_parts
from scripts.gap_guard import GapGuard

LONDON = ZoneInfo("Europe/London")


@dataclass(frozen=True)
class TimeConfig:
    name: str
    asian_end_utc_minute: int
    london_start_local_minute: int
    london_end_local_minute: int
    fixed_utc_window: bool = False
    require_ema_alignment: bool = False

    def label(self) -> str:
        def clock(total: int) -> str:
            return f"{total // 60:02d}:{total % 60:02d}"

        session = (
            f"UTC {clock(self.london_start_local_minute)}-{clock(self.london_end_local_minute)}"
            if self.fixed_utc_window
            else f"Europe/London {clock(self.london_start_local_minute)}-{clock(self.london_end_local_minute)}"
        )
        ema = "EMA200" if self.require_ema_alignment else "no-EMA"
        return f"Asia 00:00-{clock(self.asian_end_utc_minute)} UTC | {session} | {ema}"


@dataclass(frozen=True)
class Feature:
    bar: Bar
    atr: float
    ema200: float


@dataclass
class Position:
    opened_at: datetime
    direction: str
    entry: float
    stop: float
    target: float
    size: float
    entry_fee: float


@dataclass
class Result:
    timing: TimeConfig
    window: str
    trades: int
    wins: int
    losses: int
    final_balance: float
    return_pct: float
    profit_factor: Optional[float]
    max_drawdown: float
    fees: float
    example_entries: List[str]

    def row(self) -> Dict[str, object]:
        row = asdict(self.timing)
        row.update(
            {
                "label": self.timing.label(),
                "window": self.window,
                "trades": self.trades,
                "wins": self.wins,
                "losses": self.losses,
                "final_balance": round(self.final_balance, 4),
                "return_pct": round(self.return_pct, 4),
                "profit_factor": self.profit_factor,
                "max_realized_drawdown": round(self.max_drawdown, 4),
                "fees": round(self.fees, 4),
                "example_entries": "; ".join(self.example_entries),
            }
        )
        return row


def build_features(bars: Sequence[Bar]) -> List[Feature]:
    """Compute ATR14 and a close-known EMA200 without future leakage."""
    indicator = WilderIndicators(config.ATR_PERIOD, config.ZSCORE_PERIOD, config.ATR_AVG_LOOKBACK)
    features: List[Feature] = []
    ema: Optional[float] = None
    seed: List[float] = []
    multiplier = 2.0 / (config.EMA_TREND_PERIOD + 1.0)
    for index, bar in enumerate(bars):
        values = indicator.update(bar)
        if ema is None:
            seed.append(bar.close)
            if len(seed) == config.EMA_TREND_PERIOD:
                ema = sum(seed) / len(seed)
        else:
            ema = (bar.close - ema) * multiplier + ema
        if values is not None and ema is not None and index >= config.EMA_TREND_PERIOD:
            features.append(Feature(bar=bar, atr=float(values["atr_14"]), ema200=ema))
    return features


def minutes_of_day(dt: datetime) -> int:
    return dt.hour * 60 + dt.minute


def in_london_window(bar: Bar, timing: TimeConfig) -> bool:
    local = bar.timestamp if timing.fixed_utc_window else bar.timestamp.astimezone(LONDON)
    minute = minutes_of_day(local)
    return timing.london_start_local_minute <= minute < timing.london_end_local_minute


def fill_position(
    feature: Feature,
    direction: str,
    sweep_extreme: float,
    balance: float,
    spread: float,
    sweep_stop_buffer: float,
    sl_atr_multiplier: float,
    tp_r: float,
) -> Optional[Position]:
    half_spread = spread / 2.0
    entry = (
        feature.bar.close + half_spread + config.PAPER_SLIPPAGE_USD
        if direction == "LONG"
        else feature.bar.close - half_spread - config.PAPER_SLIPPAGE_USD
    )
    if direction == "LONG":
        stop = min(entry - feature.atr * sl_atr_multiplier, sweep_extreme - sweep_stop_buffer)
    else:
        stop = max(entry + feature.atr * sl_atr_multiplier, sweep_extreme + sweep_stop_buffer)
    distance = abs(entry - stop)
    round_trip_cost = max(spread * 2.0, config.ROUND_TRIP_COST_USD)
    if distance < max(config.MIN_SL_USD, round_trip_cost * config.MIN_SL_COST_MULTIPLE):
        return None
    if distance * tp_r < round_trip_cost * config.MIN_TP_COST_MULTIPLE:
        return None
    risk_dollars = balance * config.RISK_PER_TRADE_PCT / 100.0
    if risk_dollars < 0.40:
        return None
    size = max(0.01, round(risk_dollars / distance, 4))
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
    target = entry + distance * tp_r if direction == "LONG" else entry - distance * tp_r
    return Position(feature.bar.timestamp, direction, entry, stop, target, size, entry_fee)


def exit_position(position: Position, feature: Feature, spread: float) -> Optional[Tuple[float, str]]:
    """Use executable bid/ask prices and conservative SL-first ordering."""
    half_spread = spread / 2.0
    if position.direction == "LONG":
        executable_high, executable_low = feature.bar.high - half_spread, feature.bar.low - half_spread
        if executable_low <= position.stop:
            return min(position.stop, executable_low) - config.PAPER_SLIPPAGE_USD, "SL_HIT"
        if executable_high >= position.target:
            return position.target - config.PAPER_SLIPPAGE_USD, "TP_HIT"
    else:
        executable_high, executable_low = feature.bar.high + half_spread, feature.bar.low + half_spread
        if executable_high >= position.stop:
            return max(position.stop, executable_high) + config.PAPER_SLIPPAGE_USD, "SL_HIT"
        if executable_low <= position.target:
            return position.target + config.PAPER_SLIPPAGE_USD, "TP_HIT"
    return None


def in_window(timestamp: datetime, start: datetime, end: Optional[datetime]) -> bool:
    return timestamp >= start and (end is None or timestamp < end)


def simulate(
    features: Iterable[Feature],
    timing: TimeConfig,
    start: datetime,
    end: Optional[datetime],
    spread: float,
    sweep_buffer: float,
    sweep_stop_buffer: float,
    sl_atr_multiplier: float,
    tp_r: float,
    window_name: str,
    gap_guard: Optional[GapGuard] = None,
) -> Result:
    initial = balance = peak = float(config.INITIAL_BALANCE_USDT)
    max_drawdown = 0.0
    gross_profit = gross_loss = fees = 0.0
    wins = losses = 0
    position: Optional[Position] = None
    current_day: Optional[str] = None
    asian_high = -math.inf
    asian_low = math.inf
    asian_ready = False
    traded_day = False
    daily_pnl: Dict[str, float] = {}
    examples: List[str] = []

    for feature in features:
        bar = feature.bar
        day = bar.timestamp.strftime("%Y-%m-%d")
        minute_utc = minutes_of_day(bar.timestamp)
        if day != current_day:
            current_day = day
            asian_high, asian_low = -math.inf, math.inf
            asian_ready = False
            traded_day = False

        # Build the Asian range from UTC midnight through the selected cut-off.
        if minute_utc < timing.asian_end_utc_minute:
            asian_high = max(asian_high, bar.high)
            asian_low = min(asian_low, bar.low)
        elif asian_high > -math.inf:
            asian_ready = True

        if not in_window(bar.timestamp, start, end):
            continue

        # Existing position is evaluated before a new structural signal. This
        # removes same-bar entry/exit look-ahead.
        if position is not None:
            outcome = exit_position(position, feature, spread)
            if outcome is None and gap_guard is not None and gap_guard.force_flat_after(bar.timestamp):
                half = spread / 2.0
                exit_price = (
                    bar.close - half - config.PAPER_SLIPPAGE_USD
                    if position.direction == "LONG"
                    else bar.close + half + config.PAPER_SLIPPAGE_USD
                )
                outcome = (exit_price, "DATA_GAP_EXIT")
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
                max_drawdown = max(max_drawdown, peak - balance)
                daily_pnl[day] = daily_pnl.get(day, 0.0) + net
                position = None

        if position is not None or traded_day or balance < 5.0:
            continue
        if gap_guard is not None and not gap_guard.entry_allowed(bar.timestamp):
            continue
        if not asian_ready or not in_london_window(bar, timing):
            continue
        if daily_pnl.get(day, 0.0) <= -initial * config.MAX_DAILY_LOSS_PCT / 100.0:
            continue
        if feature.atr < config.MIN_ATR_USD:
            continue

        direction: Optional[str] = None
        sweep_extreme = 0.0
        # A reclaim is the core condition: a wick alone is not a signal.
        if bar.low <= asian_low - sweep_buffer and bar.close > asian_low:
            if not timing.require_ema_alignment or bar.close > feature.ema200:
                direction, sweep_extreme = "LONG", bar.low
        elif bar.high >= asian_high + sweep_buffer and bar.close < asian_high:
            if not timing.require_ema_alignment or bar.close < feature.ema200:
                direction, sweep_extreme = "SHORT", bar.high
        if direction is None:
            continue
        position = fill_position(
            feature,
            direction,
            sweep_extreme,
            balance,
            spread,
            sweep_stop_buffer,
            sl_atr_multiplier,
            tp_r,
        )
        if position is not None:
            traded_day = True
            if len(examples) < 5:
                local = bar.timestamp.astimezone(LONDON)
                examples.append(
                    f"{bar.timestamp.strftime('%Y-%m-%d %H:%M')} UTC / "
                    f"{local.strftime('%H:%M %Z')} {direction}"
                )

    trades = wins + losses
    return Result(
        timing=timing,
        window=window_name,
        trades=trades,
        wins=wins,
        losses=losses,
        final_balance=balance,
        return_pct=(balance / initial - 1.0) * 100.0,
        profit_factor=(gross_profit / gross_loss) if gross_loss else None,
        max_drawdown=max_drawdown,
        fees=fees,
        example_entries=examples,
    )


def rank_development(results: Sequence[Result]) -> List[Result]:
    def score(result: Result) -> Tuple[float, float, int]:
        if result.trades < 12:
            return (-1_000_000.0, result.return_pct, result.trades)
        pf = result.profit_factor if result.profit_factor is not None else 0.0
        return (pf, result.return_pct, result.trades)

    return sorted(results, key=score, reverse=True)


def table(results: Sequence[Result]) -> List[str]:
    lines = [
        "| Timing / structure | Trades | Final | Return | PF | DD | Example entries |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for result in results:
        pf = f"{result.profit_factor:.2f}" if result.profit_factor is not None else "n/a"
        examples = "<br>".join(result.example_entries) or "—"
        lines.append(
            f"| `{result.timing.label()}` | {result.trades} | ${result.final_balance:.2f} | "
            f"{result.return_pct:+.2f}% | {pf} | ${result.max_drawdown:.2f} | {examples} |"
        )
    return lines


def write_csv(path: Path, results: Sequence[Result]) -> None:
    rows = [result.row() for result in results]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", nargs="+", help="CSV part paths or shell globs")
    parser.add_argument("--spread", type=float, default=0.40)
    parser.add_argument("--sweep-buffer", type=float, default=0.40)
    parser.add_argument("--sweep-stop-buffer", type=float, default=0.20)
    parser.add_argument("--sl-atr", type=float, default=1.5)
    parser.add_argument("--tp-r", type=float, default=2.0)
    parser.add_argument("--gap-guard", action="store_true")
    parser.add_argument("--report", default="LONDON_ASIAN_TIMEZONE_RESEARCH.md")
    parser.add_argument("--results-csv", default="LONDON_ASIAN_TIMEZONE_RESEARCH.csv")
    parser.add_argument("--data-revision", default="")
    args = parser.parse_args()
    if min(args.spread, args.sweep_buffer, args.sweep_stop_buffer, args.sl_atr, args.tp_r) < 0:
        parser.error("spread, buffers, SL ATR, and TP R must be non-negative")

    bars = load_csv_parts(args.csv)
    gap_guard = GapGuard(bars) if args.gap_guard else None
    features = build_features(bars)
    configs = [
        # Legacy fixed UTC window used by older strategy sketches.
        TimeConfig("Legacy fixed UTC", 6 * 60 + 30, 7 * 60, 10 * 60 + 30, fixed_utc_window=True),
        # DST-aware London clock tests. At 08:00 local, the UTC start is 08:00
        # in GMT and 07:00 in BST.
        TimeConfig("London local / Asia 06:00", 6 * 60, 8 * 60, 10 * 60 + 30),
        TimeConfig("London local / Asia 06:30", 6 * 60 + 30, 8 * 60, 10 * 60 + 30),
        TimeConfig("London local / Asia 07:00", 7 * 60, 8 * 60, 10 * 60 + 30),
        TimeConfig("London local extended", 6 * 60 + 30, 8 * 60, 11 * 60),
        TimeConfig("London local + EMA", 6 * 60 + 30, 8 * 60, 10 * 60 + 30, require_ema_alignment=True),
    ]
    windows = [
        (
            "Development (2019-09 to 2022-12)",
            datetime(2019, 9, 6, tzinfo=timezone.utc),
            datetime(2023, 1, 1, tzinfo=timezone.utc),
        ),
        (
            "Validation (2023-2024)",
            datetime(2023, 1, 1, tzinfo=timezone.utc),
            datetime(2025, 1, 1, tzinfo=timezone.utc),
        ),
        ("Holdout (2025 onward)", datetime(2025, 1, 1, tzinfo=timezone.utc), None),
    ]
    development_name, development_start, development_end = windows[0]
    development = [
        simulate(
            features,
            timing,
            development_start,
            development_end,
            args.spread,
            args.sweep_buffer,
            args.sweep_stop_buffer,
            args.sl_atr,
            args.tp_r,
            development_name,
            gap_guard=gap_guard,
        )
        for timing in configs
    ]
    ranked = rank_development(development)
    selected = ranked[0].timing

    unseen: List[Result] = []
    legacy = configs[0]
    for window_name, start, end in windows[1:]:
        for timing, label in ((legacy, "Legacy fixed UTC"), (selected, "Development-selected timing")):
            result = simulate(
                features,
                timing,
                start,
                end,
                args.spread,
                args.sweep_buffer,
                args.sweep_stop_buffer,
                args.sl_atr,
                args.tp_r,
                f"{label} — {window_name}",
                gap_guard=gap_guard,
            )
            unseen.append(result)

    all_results = [*development, *unseen]
    write_csv(Path(args.results_csv), all_results)
    report = [
        "# Asian range / London session timezone research",
        "",
        "## Method",
        "",
        f"- Data: {len(bars):,} source 5-minute bars; timestamps explicitly treated as UTC.",
        "- Asian range: 00:00 UTC through the listed cutoff; London window is either fixed UTC or `Europe/London` local time using IANA DST rules.",
        f"- Entry: sweep beyond Asian range by ${args.sweep_buffer:.2f}, then a 5-minute close back inside the range. One structural trade per UTC day.",
        f"- Stop: farther of {args.sl_atr:.1f} ATR from entry or ${args.sweep_stop_buffer:.2f} beyond the sweep extreme. Target: {args.tp_r:.1f}R.",
        f"- Cost: ${args.spread:.2f} spread, ${config.PAPER_SLIPPAGE_USD:.2f} adverse slippage per fill, and {config.PAPER_TAKER_FEE_RATE * 100:.02f}% taker fee per side.",
        "- Position management begins on the bar after entry. If a subsequent OHLC bar touches both stop and target, stop is selected first.",
        "- Timing choice is made only from development data; validation and holdout are frozen.",
        f"- Gap guard: {'enabled' if args.gap_guard else 'disabled'}.",
    ]
    if args.data_revision:
        report.append(f"- Data revision: `{args.data_revision}`.")
    report.extend(["", "## DST consequence", ""])
    report.extend(
        [
            "A London 08:00 local window begins at 08:00 UTC during GMT and 07:00 UTC during British Summer Time. The legacy fixed 07:00 UTC window therefore starts one hour too early during UK winter and is only aligned with London 08:00 during BST.",
            "",
            "## Development-only timing comparison",
            "",
        ]
    )
    report.extend(table(ranked))
    report.extend(["", "## Frozen validation and holdout comparison", ""])
    report.extend(table(unseen))
    report.extend(
        [
            "",
            "## Decision rule",
            "",
            f"The development-selected timing is `{selected.label()}`. It is rejected unless both frozen windows show adequate sample size and net PF above 1 after costs. A local-time adjustment alone is not sufficient evidence of an edge.",
            "",
            f"All results are available in [`{Path(args.results_csv).name}`]({Path(args.results_csv).name}).",
        ]
    )
    Path(args.report).write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"Development-selected timing: {selected.label()}")
    for result in unseen:
        print(
            f"{result.window}: trades={result.trades} final=${result.final_balance:.2f} "
            f"return={result.return_pct:+.2f}% PF={result.profit_factor}"
        )


if __name__ == "__main__":
    main()
