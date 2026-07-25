#!/usr/bin/env python3
"""Phase 5A: discover whether XAU impulse-pullback-reclaim setups have edge.

This is an outcome-label study, not a trading system. It first identifies a
strict, close-only structure:

D1/H4 trend permission
→ H1 range expansion and 20-bar structure break
→ M15 controlled 25–60% pullback
→ M15 reclaim above/below the pullback swing and M15 EMA20
→ later M5 directional break trigger

For every candidate, it measures whether +0.5R, +1R, +1.5R, and +2R are
reached before the structural stop, using the same fixed bid/ask/slippage
assumptions and stop-first intrabar policy used by the other studies.

No candidate is promoted unless outcome labels themselves demonstrate positive
behavior across development, validation, and holdout before a PnL strategy is
built around it.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import math
import sys
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import config
from scripts.backtest_mtf_trend_pullback import (
    AggregateBar,
    TrendState,
    aggregate,
    aggregate_daily,
    indicator_states,
    load_csv_parts,
    side_of_ema,
)
from scripts.backtest_v5_csv import Bar, WilderIndicators
from scripts.research_daily_macro_regime import MacroHistory, load_macro, make_gate, MacroPolicy


@dataclass(frozen=True)
class Definition:
    name: str
    impulse_atr_multiple: float
    pullback_min: float
    pullback_max: float
    max_pullback_minutes: int

    def label(self) -> str:
        return (
            f"{self.name}: H1≥{self.impulse_atr_multiple:g}ATR | "
            f"PB {self.pullback_min:.0%}-{self.pullback_max:.0%} | "
            f"≤{self.max_pullback_minutes}m"
        )


@dataclass(frozen=True)
class H1Context:
    bar: AggregateBar
    atr: Optional[float]
    prior_high_20: Optional[float]
    prior_low_20: Optional[float]


@dataclass
class Impulse:
    direction: str
    high: float
    low: float
    created_at: datetime
    expires_at: datetime

    @property
    def size(self) -> float:
        return self.high - self.low


@dataclass
class Pullback:
    impulse: Impulse
    low: float
    high: float
    created_at: datetime


@dataclass
class Reclaim:
    pullback: Pullback
    created_at: datetime


@dataclass(frozen=True)
class Candidate:
    definition: str
    timestamp: datetime
    direction: str
    entry: float
    stop: float
    risk: float
    macro_allowed: bool


@dataclass(frozen=True)
class Outcome:
    candidate: Candidate
    reached_half_r: bool
    reached_one_r: bool
    reached_one_half_r: bool
    reached_two_r: bool
    stopped: bool
    timed_out: bool
    max_r: float
    min_r: float


@dataclass
class Summary:
    definition: Definition
    subset: str
    window: str
    candidates: int
    half_r_rate: float
    one_r_rate: float
    one_half_r_rate: float
    two_r_rate: float
    stop_rate: float
    median_max_r: float
    median_min_r: float

    def row(self) -> Dict[str, object]:
        return {
            "definition": self.definition.name,
            "impulse_atr_multiple": self.definition.impulse_atr_multiple,
            "pullback_min": self.definition.pullback_min,
            "pullback_max": self.definition.pullback_max,
            "max_pullback_minutes": self.definition.max_pullback_minutes,
            "subset": self.subset,
            "window": self.window,
            "candidates": self.candidates,
            "hit_0_5r_pct": round(self.half_r_rate, 2),
            "hit_1r_pct": round(self.one_r_rate, 2),
            "hit_1_5r_pct": round(self.one_half_r_rate, 2),
            "hit_2r_pct": round(self.two_r_rate, 2),
            "stop_first_pct": round(self.stop_rate, 2),
            "median_max_r": round(self.median_max_r, 3),
            "median_min_r": round(self.median_min_r, 3),
        }


def median(values: List[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2.0


def h1_contexts(bars: Sequence[AggregateBar]) -> Dict[datetime, H1Context]:
    """H1 ATR14 and prior 20-H1 structure, all available only at H1 close."""
    previous_close: Optional[float] = None
    tr_seed: List[float] = []
    atr: Optional[float] = None
    highs: deque[float] = deque(maxlen=20)
    lows: deque[float] = deque(maxlen=20)
    result: Dict[datetime, H1Context] = {}
    for bar in bars:
        prior_high = max(highs) if len(highs) == 20 else None
        prior_low = min(lows) if len(lows) == 20 else None
        if previous_close is not None:
            tr = max(bar.high - bar.low, abs(bar.high - previous_close), abs(bar.low - previous_close))
            if atr is None:
                tr_seed.append(tr)
                if len(tr_seed) == 14:
                    atr = sum(tr_seed) / 14.0
            else:
                atr = (atr * 13.0 + tr) / 14.0
        result[bar.end] = H1Context(bar, atr, prior_high, prior_low)
        highs.append(bar.high)
        lows.append(bar.low)
        previous_close = bar.close
    return result


def higher_trend(daily: Optional[TrendState], h4: Optional[TrendState], direction: str) -> bool:
    return side_of_ema(daily, 50, direction) and side_of_ema(h4, 50, direction)


def is_impulse(context: H1Context, direction: str, definition: Definition) -> bool:
    if context.atr is None or context.prior_high_20 is None or context.prior_low_20 is None:
        return False
    bar = context.bar
    bar_range = bar.high - bar.low
    if bar_range < definition.impulse_atr_multiple * context.atr:
        return False
    close_location = (bar.close - bar.low) / bar_range if bar_range > 1e-12 else 0.5
    if direction == "LONG":
        return close_location >= 0.75 and bar.close > context.prior_high_20
    return close_location <= 0.25 and bar.close < context.prior_low_20


def m15_reclaim(
    m15: TrendState, impulse: Impulse, pullback: Optional[Pullback], definition: Definition
) -> Tuple[Optional[Pullback], Optional[Reclaim]]:
    """Advance the controlled pullback state at an M15 close."""
    bar = m15.bar
    if bar.end > impulse.expires_at or impulse.size <= 0:
        return None, None
    ema = m15.ema20
    if ema is None:
        return pullback, None
    if impulse.direction == "LONG":
        retracement = (impulse.high - bar.low) / impulse.size
        if pullback is None:
            if definition.pullback_min <= retracement <= definition.pullback_max and bar.close > impulse.low:
                return Pullback(impulse, bar.low, bar.high, bar.end), None
            return None, None
        if bar.low < impulse.high - definition.pullback_max * impulse.size or bar.low <= impulse.low:
            return None, None
        if bar.close > pullback.high and bar.close > ema:
            return None, Reclaim(pullback, bar.end)
        updated = Pullback(impulse, min(pullback.low, bar.low), max(pullback.high, bar.high), pullback.created_at)
        return updated, None

    retracement = (bar.high - impulse.low) / impulse.size
    if pullback is None:
        if definition.pullback_min <= retracement <= definition.pullback_max and bar.close < impulse.high:
            return Pullback(impulse, bar.low, bar.high, bar.end), None
        return None, None
    if bar.high > impulse.low + definition.pullback_max * impulse.size or bar.high >= impulse.high:
        return None, None
    if bar.close < pullback.low and bar.close < ema:
        return None, Reclaim(pullback, bar.end)
    updated = Pullback(impulse, min(pullback.low, bar.low), max(pullback.high, bar.high), pullback.created_at)
    return updated, None


def candidate_from_trigger(
    definition: Definition,
    bar: Bar,
    previous: Bar,
    reclaim: Reclaim,
    m5_atr: float,
    macro_allowed: bool,
    spread: float,
) -> Optional[Candidate]:
    direction = reclaim.pullback.impulse.direction
    if direction == "LONG":
        triggered = bar.close > bar.open and bar.close > previous.high
        entry = bar.close + spread / 2.0 + config.PAPER_SLIPPAGE_USD
        stop = min(reclaim.pullback.low - 0.20, entry - 1.5 * m5_atr)
    else:
        triggered = bar.close < bar.open and bar.close < previous.low
        entry = bar.close - spread / 2.0 - config.PAPER_SLIPPAGE_USD
        stop = max(reclaim.pullback.high + 0.20, entry + 1.5 * m5_atr)
    if not triggered:
        return None
    risk = abs(entry - stop)
    cost = max(spread * 2.0, config.ROUND_TRIP_COST_USD)
    if risk < max(config.MIN_SL_USD, cost * config.MIN_SL_COST_MULTIPLE):
        return None
    if risk * 2.0 < cost * config.MIN_TP_COST_MULTIPLE:
        return None
    return Candidate(definition.name, bar.timestamp + timedelta(minutes=5), direction, entry, stop, risk, macro_allowed)


def label_outcome(candidate: Candidate, bars: Sequence[Bar], start_index: int, spread: float) -> Outcome:
    half = spread / 2.0
    reached = {0.5: False, 1.0: False, 1.5: False, 2.0: False}
    max_r = 0.0
    min_r = 0.0
    stopped = False
    timed_out = False
    entry_date = candidate.timestamp.date()
    for bar in bars[start_index + 1 :]:
        decision = bar.timestamp + timedelta(minutes=5)
        if candidate.direction == "LONG":
            favorable = (bar.high - half - candidate.entry) / candidate.risk
            adverse = (candidate.entry - (bar.low - half)) / candidate.risk
            stop_hit = bar.low - half <= candidate.stop
        else:
            favorable = (candidate.entry - (bar.low + half)) / candidate.risk
            adverse = ((bar.high + half) - candidate.entry) / candidate.risk
            stop_hit = bar.high + half >= candidate.stop
        # The existing project policy resolves stop first if both are possible.
        if stop_hit:
            stopped = True
            min_r = min(min_r, -max(1.0, adverse))
            break
        max_r = max(max_r, favorable)
        min_r = min(min_r, -max(0.0, adverse))
        for threshold in reached:
            if favorable >= threshold:
                reached[threshold] = True
        if reached[2.0]:
            # A +2R target would be realized at this point; do not let a later
            # reversal relabel an already achieved target as a stop-out.
            break
        if decision.hour >= 21 or decision.date() != entry_date:
            timed_out = True
            break
    return Outcome(
        candidate,
        reached[0.5],
        reached[1.0],
        reached[1.5],
        reached[2.0],
        stopped,
        timed_out,
        max_r,
        min_r,
    )


def discover(
    bars: Sequence[Bar],
    m15_states: Dict[datetime, TrendState],
    h1_states: Dict[datetime, H1Context],
    h4_states: Dict[datetime, TrendState],
    d1_states: Dict[datetime, TrendState],
    definition: Definition,
    macro_gate,
    spread: float,
) -> List[Outcome]:
    m5_indicators = WilderIndicators(config.ATR_PERIOD, config.ZSCORE_PERIOD, config.ATR_AVG_LOOKBACK)
    daily: Optional[TrendState] = None
    h4: Optional[TrendState] = None
    h1: Optional[H1Context] = None
    impulse: Optional[Impulse] = None
    pullback: Optional[Pullback] = None
    reclaim: Optional[Reclaim] = None
    outcomes: List[Outcome] = []
    for index, bar in enumerate(bars):
        decision = bar.timestamp + timedelta(minutes=5)
        values = m5_indicators.update(bar)
        if decision in d1_states:
            daily = d1_states[decision]
        if decision in h4_states:
            h4 = h4_states[decision]
        if decision in h1_states:
            h1 = h1_states[decision]
            for direction in ("LONG", "SHORT"):
                if higher_trend(daily, h4, direction) and is_impulse(h1, direction, definition):
                    impulse = Impulse(
                        direction=direction,
                        high=h1.bar.high,
                        low=h1.bar.low,
                        created_at=decision,
                        expires_at=decision + timedelta(minutes=definition.max_pullback_minutes),
                    )
                    pullback = None
                    reclaim = None
                    break
        if decision in m15_states and impulse is not None:
            pullback, new_reclaim = m15_reclaim(m15_states[decision], impulse, pullback, definition)
            if new_reclaim is not None:
                reclaim = new_reclaim
            if decision > impulse.expires_at:
                impulse = pullback = reclaim = None

        if values is None or index < 300 or reclaim is None or decision <= reclaim.created_at:
            continue
        macro_allowed = macro_gate(decision, reclaim.pullback.impulse.direction)
        candidate = candidate_from_trigger(
            definition, bar, bars[index - 1], reclaim, float(values["atr_14"]), macro_allowed, spread
        )
        if candidate is not None:
            outcomes.append(label_outcome(candidate, bars, index, spread))
            # One candidate per validated impulse; label the structure then
            # wait for the next H1 impulse instead of stacking variants.
            impulse = pullback = reclaim = None
    return outcomes


def summarize(definition: Definition, subset: str, window: str, outcomes: Sequence[Outcome]) -> Summary:
    count = len(outcomes)
    if not count:
        return Summary(definition, subset, window, 0, 0, 0, 0, 0, 0, 0, 0)
    pct = lambda n: 100.0 * n / count
    return Summary(
        definition,
        subset,
        window,
        count,
        pct(sum(item.reached_half_r for item in outcomes)),
        pct(sum(item.reached_one_r for item in outcomes)),
        pct(sum(item.reached_one_half_r for item in outcomes)),
        pct(sum(item.reached_two_r for item in outcomes)),
        pct(sum(item.stopped for item in outcomes)),
        median([item.max_r for item in outcomes]),
        median([item.min_r for item in outcomes]),
    )


def table(rows: Sequence[Summary]) -> List[str]:
    lines = [
        "| Definition | Subset | Candidates | +0.5R first | +1R first | +1.5R first | +2R first | Stop first | Median MFE R | Median MAE R |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| `{row.definition.label()}` | {row.subset} | {row.candidates} | {row.half_r_rate:.1f}% | "
            f"{row.one_r_rate:.1f}% | {row.one_half_r_rate:.1f}% | {row.two_r_rate:.1f}% | "
            f"{row.stop_rate:.1f}% | {row.median_max_r:.2f} | {row.median_min_r:.2f} |"
        )
    return lines


def write_csv(path: Path, rows: Sequence[Summary]) -> None:
    payload = [row.row() for row in rows]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(payload[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(payload)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", nargs="+", help="UTC M5 XAU CSV paths or globs")
    parser.add_argument("--macro", required=True, help="daily macro CSV from main")
    parser.add_argument("--spread", type=float, default=0.40)
    parser.add_argument("--report", default="XAU_IMPULSE_RECLAIM_DISCOVERY.md")
    parser.add_argument("--results-csv", default="XAU_IMPULSE_RECLAIM_DISCOVERY.csv")
    parser.add_argument("--data-revision", default="")
    args = parser.parse_args()
    bars = load_csv_parts(args.csv)
    macro_history = load_macro(Path(args.macro))
    m15 = indicator_states(aggregate(bars, 15))
    h1_context = h1_contexts(aggregate(bars, 60))
    h4 = indicator_states(aggregate(bars, 240))
    d1 = indicator_states(aggregate_daily(bars))
    definitions = [
        Definition("Standard", 1.25, 0.25, 0.60, 240),
        Definition("Conservative", 1.50, 0.25, 0.50, 180),
    ]
    policies = {
        "All candidates": make_gate(macro_history, MacroPolicy("no macro")),
        "Prior-day stress allowed": make_gate(macro_history, MacroPolicy("stress", stress_veto=True)),
    }
    windows = [
        ("Development (2019-09 to 2022-12)", datetime(2019, 9, 6, tzinfo=timezone.utc), datetime(2023, 1, 1, tzinfo=timezone.utc)),
        ("Validation (2023-2024)", datetime(2023, 1, 1, tzinfo=timezone.utc), datetime(2025, 1, 1, tzinfo=timezone.utc)),
        ("Holdout (2025 onward)", datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2026, 2, 1, tzinfo=timezone.utc)),
    ]
    all_rows: List[Summary] = []
    for definition in definitions:
        all_outcomes = discover(
            bars, m15, h1_context, h4, d1, definition, policies["All candidates"], args.spread
        )
        stress_outcomes = discover(
            bars, m15, h1_context, h4, d1, definition, policies["Prior-day stress allowed"], args.spread
        )
        for subset, outcomes in (
            ("All candidates", all_outcomes),
            ("Prior-day stress allowed", stress_outcomes),
        ):
            for window_name, start, end in windows:
                in_window = [
                    item
                    for item in outcomes
                    if item.candidate.timestamp >= start and (end is None or item.candidate.timestamp < end)
                ]
                all_rows.append(summarize(definition, subset, window_name, in_window))

    write_csv(Path(args.results_csv), all_rows)
    report = [
        "# XAU impulse-pullback-reclaim discovery study",
        "",
        "## Purpose",
        "",
        "This study labels the gross structural behavior before another PnL strategy is built. A candidate is valuable only if it reaches material R multiples before its structural stop often enough to overcome the fixed cost model.",
        "",
        "## Anti-look-ahead controls",
        "",
        f"- Source: {len(bars):,} UTC M5 XAU bars. Higher timeframes are derived from complete M5 bars only.",
        "- D1/H4/H1/M15 state changes become visible only at their parent close time.",
        "- M5 entry can occur only after a later M5 close than the M15 reclaim close.",
        "- Daily macro gate reads only the prior daily row; same-day DXY/VIX/oil closes and ex-post geopolitical labels are not allowed.",
        f"- Outcome: ${args.spread:.2f} fixed spread, ${config.PAPER_SLIPPAGE_USD:.2f} adverse slippage, stop-first intrabar ordering, 8-hour/21:00 UTC horizon.",
        "",
        "## Structure definitions",
        "",
        "- H1 impulse: true range exceeds the definition ATR multiple, closes in the top/bottom 25% of its range, and closes beyond the prior 20 H1 bars' high/low.",
        "- M15 pullback: retraces the definition percentage of the impulse without invalidating its origin.",
        "- M15 reclaim: closes through the pullback swing and on the correct side of M15 EMA20.",
        "- M5 trigger: a later directional M5 close through the preceding M5 high/low.",
    ]
    if args.data_revision:
        report.append(f"- XAU data revision: `{args.data_revision}`.")
    report.extend(["", "## Outcome labels", ""])
    report.extend(table(all_rows))
    report.extend(
        [
            "",
            "## Discovery gate",
            "",
            "A definition is rejected before PnL optimisation unless it produces at least 30 development candidates, materially more +1R-before-stop outcomes than stop-first outcomes, and a meaningful number of +1.5R/+2R outcomes across both validation and holdout. This is a behavior test, not a search for one attractive backtest period.",
            "",
            f"All output rows are in [`{Path(args.results_csv).name}`]({Path(args.results_csv).name}).",
        ]
    )
    Path(args.report).write_text("\n".join(report) + "\n", encoding="utf-8")
    for row in all_rows:
        print(f"{row.definition.name} | {row.subset} | {row.window}: n={row.candidates}, +1R={row.one_r_rate:.1f}%, stop={row.stop_rate:.1f}%")


if __name__ == "__main__":
    main()
