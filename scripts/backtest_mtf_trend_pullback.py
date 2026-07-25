#!/usr/bin/env python3
"""Closed-bar, multi-timeframe XAU trend-pullback research.

This is a separate strategy family from the rejected Z-score and Asian-sweep
systems. It uses only the supplied UTC 5-minute XAU history, deriving M15/H1/
H4/D1 bars internally with no higher-timeframe look-ahead.

Decision hierarchy
------------------
D1/H4/H1 : aligned trend state (price on the correct side of selected EMAs)
M15       : pullback touches the selected M15 EMA and closes back on trend side
M5        : reversal close beyond the preceding M5 bar in trend direction
Execution : one trade/day, fixed conservative costs, structural/ATR stop,
            fixed 2R target, day-close exit (no overnight/funding exposure)

Timing variants are selected only on 2019-09 to 2022-12 development data,
then frozen for 2023-2024 validation and 2025+ holdout. This is research, not
a live-trading recommendation.
"""
from __future__ import annotations

import argparse
import csv
import glob
import math
import sys
from bisect import bisect_left
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import config
from scripts.backtest_v5_csv import Bar, WilderIndicators, load_csv_parts


@dataclass(frozen=True)
class AggregateBar:
    start: datetime
    end: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class TrendState:
    bar: AggregateBar
    ema20: Optional[float]
    ema50: Optional[float]


@dataclass(frozen=True)
class Variant:
    name: str
    require_daily: bool
    h4_ema_period: int
    h1_ema_period: int
    m15_ema_period: int

    def label(self) -> str:
        daily = "D1" if self.require_daily else "no-D1"
        return f"{daily}|H4 EMA{self.h4_ema_period}|H1 EMA{self.h1_ema_period}|M15 EMA{self.m15_ema_period}"


@dataclass
class Pullback:
    direction: str
    low: float
    high: float
    created_at: datetime
    expires_at: datetime


@dataclass
class Position:
    opened_at: datetime
    direction: str
    entry: float
    stop: float
    target: float
    size: float
    entry_fee: float
    stop_distance: float


@dataclass
class Result:
    variant: Variant
    window: str
    trades: int
    wins: int
    losses: int
    time_exits: int
    final_balance: float
    return_pct: float
    profit_factor: Optional[float]
    max_drawdown: float
    fees: float
    vetoed_entries: int
    examples: List[str]

    def row(self) -> Dict[str, object]:
        row = asdict(self.variant)
        row.update(
            {
                "label": self.variant.label(),
                "window": self.window,
                "trades": self.trades,
                "wins": self.wins,
                "losses": self.losses,
                "time_exits": self.time_exits,
                "final_balance": round(self.final_balance, 4),
                "return_pct": round(self.return_pct, 4),
                "profit_factor": self.profit_factor,
                "max_realized_drawdown": round(self.max_drawdown, 4),
                "fees": round(self.fees, 4),
                "vetoed_entries": self.vetoed_entries,
                "example_entries": "; ".join(self.examples),
            }
        )
        return row


def floor_time(timestamp: datetime, minutes: int) -> datetime:
    minute = (timestamp.minute // minutes) * minutes
    if minutes >= 60:
        hour_block = (timestamp.hour * 60 + timestamp.minute) // minutes
        total = hour_block * minutes
        return timestamp.replace(hour=total // 60, minute=total % 60, second=0, microsecond=0)
    return timestamp.replace(minute=minute, second=0, microsecond=0)


def aggregate(bars: Sequence[Bar], minutes: int) -> List[AggregateBar]:
    """Create only fully populated UTC parent bars from M5 components."""
    expected = minutes // 5
    groups: Dict[datetime, List[Bar]] = {}
    for bar in bars:
        groups.setdefault(floor_time(bar.timestamp, minutes), []).append(bar)
    output: List[AggregateBar] = []
    for start, members in sorted(groups.items()):
        members.sort(key=lambda item: item.timestamp)
        continuous = len(members) == expected and all(
            members[i].timestamp == start + timedelta(minutes=5 * i) for i in range(expected)
        )
        if not continuous:
            continue
        output.append(
            AggregateBar(
                start=start,
                end=start + timedelta(minutes=minutes),
                open=members[0].open,
                high=max(item.high for item in members),
                low=min(item.low for item in members),
                close=members[-1].close,
                volume=sum(item.volume for item in members),
            )
        )
    return output


def aggregate_daily(bars: Sequence[Bar]) -> List[AggregateBar]:
    """Create complete UTC weekday bars; weekend/holiday gaps are excluded."""
    groups: Dict[datetime, List[Bar]] = {}
    for bar in bars:
        start = bar.timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
        groups.setdefault(start, []).append(bar)
    output: List[AggregateBar] = []
    for start, members in sorted(groups.items()):
        members.sort(key=lambda item: item.timestamp)
        # Source is a weekday XAU series. Require enough bars to avoid a partial
        # holiday/session being mistaken for a complete daily trend bar.
        if len(members) < 200:
            continue
        output.append(
            AggregateBar(
                start=start,
                end=start + timedelta(days=1),
                open=members[0].open,
                high=max(item.high for item in members),
                low=min(item.low for item in members),
                close=members[-1].close,
                volume=sum(item.volume for item in members),
            )
        )
    return output


def indicator_states(bars: Sequence[AggregateBar]) -> Dict[datetime, TrendState]:
    """Return EMA20/EMA50 state keyed by a parent bar's close time."""
    ema20: Optional[float] = None
    ema50: Optional[float] = None
    seed20: List[float] = []
    seed50: List[float] = []
    alpha20 = 2.0 / 21.0
    alpha50 = 2.0 / 51.0
    result: Dict[datetime, TrendState] = {}
    for bar in bars:
        if ema20 is None:
            seed20.append(bar.close)
            if len(seed20) == 20:
                ema20 = sum(seed20) / 20.0
        else:
            ema20 = (bar.close - ema20) * alpha20 + ema20
        if ema50 is None:
            seed50.append(bar.close)
            if len(seed50) == 50:
                ema50 = sum(seed50) / 50.0
        else:
            ema50 = (bar.close - ema50) * alpha50 + ema50
        result[bar.end] = TrendState(bar=bar, ema20=ema20, ema50=ema50)
    return result


def side_of_ema(state: Optional[TrendState], period: int, direction: str) -> bool:
    if state is None:
        return False
    value = state.ema20 if period == 20 else state.ema50
    if value is None:
        return False
    return state.bar.close > value if direction == "LONG" else state.bar.close < value


def trend_direction(
    variant: Variant,
    daily: Optional[TrendState],
    h4: Optional[TrendState],
    h1: Optional[TrendState],
) -> Optional[str]:
    for direction in ("LONG", "SHORT"):
        if variant.require_daily and not side_of_ema(daily, 20, direction):
            continue
        if side_of_ema(h4, variant.h4_ema_period, direction) and side_of_ema(h1, variant.h1_ema_period, direction):
            return direction
    return None


def fill_position(
    bar: Bar,
    direction: str,
    pullback: Pullback,
    atr: float,
    balance: float,
    spread: float,
    stop_buffer: float,
    sl_atr: float,
    rr: float,
) -> Optional[Position]:
    half_spread = spread / 2.0
    entry = bar.close + half_spread + config.PAPER_SLIPPAGE_USD if direction == "LONG" else bar.close - half_spread - config.PAPER_SLIPPAGE_USD
    if direction == "LONG":
        stop = min(pullback.low - stop_buffer, entry - atr * sl_atr)
    else:
        stop = max(pullback.high + stop_buffer, entry + atr * sl_atr)
    distance = abs(entry - stop)
    cost = max(spread * 2.0, config.ROUND_TRIP_COST_USD)
    if distance < max(config.MIN_SL_USD, cost * config.MIN_SL_COST_MULTIPLE):
        return None
    if distance * rr < cost * config.MIN_TP_COST_MULTIPLE:
        return None
    risk = balance * config.RISK_PER_TRADE_PCT / 100.0
    size = max(0.01, round(risk / distance, 4))
    margin_cap = balance * config.MARGIN_CAP_PCT / 100.0
    margin = entry * size / config.MAX_LEVERAGE
    if margin > margin_cap:
        size = round(margin_cap * config.MAX_LEVERAGE / entry, 4)
        if size < 0.01:
            return None
        margin = entry * size / config.MAX_LEVERAGE
    fee = entry * size * config.PAPER_TAKER_FEE_RATE
    if margin + fee > balance:
        return None
    target = entry + distance * rr if direction == "LONG" else entry - distance * rr
    return Position(bar.timestamp, direction, entry, stop, target, size, fee, distance)


def bar_exit(position: Position, bar: Bar, spread: float) -> Optional[Tuple[float, str]]:
    half = spread / 2.0
    if position.direction == "LONG":
        high, low = bar.high - half, bar.low - half
        if low <= position.stop:
            return min(position.stop, low) - config.PAPER_SLIPPAGE_USD, "SL_HIT"
        if high >= position.target:
            return position.target - config.PAPER_SLIPPAGE_USD, "TP_HIT"
    else:
        high, low = bar.high + half, bar.low + half
        if high >= position.stop:
            return max(position.stop, high) + config.PAPER_SLIPPAGE_USD, "SL_HIT"
        if low <= position.target:
            return position.target + config.PAPER_SLIPPAGE_USD, "TP_HIT"
    return None


def close_at_market(position: Position, bar: Bar, spread: float) -> float:
    half = spread / 2.0
    if position.direction == "LONG":
        return bar.close - half - config.PAPER_SLIPPAGE_USD
    return bar.close + half + config.PAPER_SLIPPAGE_USD


def in_window(timestamp: datetime, start: datetime, end: Optional[datetime]) -> bool:
    return timestamp >= start and (end is None or timestamp < end)


def event_veto_active(
    timestamp: datetime, event_times: Sequence[datetime], pre_minutes: int, post_minutes: int
) -> bool:
    """Check a UTC timestamp against a sorted event list in logarithmic time."""
    if not event_times or (pre_minutes <= 0 and post_minutes <= 0):
        return False
    index = bisect_left(event_times, timestamp)
    for candidate_index in (index - 1, index):
        if 0 <= candidate_index < len(event_times):
            event = event_times[candidate_index]
            if event - timedelta(minutes=pre_minutes) <= timestamp <= event + timedelta(minutes=post_minutes):
                return True
    return False


def simulate(
    bars: Sequence[Bar],
    m15_states: Dict[datetime, TrendState],
    h1_states: Dict[datetime, TrendState],
    h4_states: Dict[datetime, TrendState],
    d1_states: Dict[datetime, TrendState],
    variant: Variant,
    start: datetime,
    end: Optional[datetime],
    spread: float,
    stop_buffer: float,
    sl_atr: float,
    rr: float,
    session_start_hour: int,
    session_end_hour: int,
    flat_hour: int,
    window_name: str,
    event_times: Sequence[datetime] = (),
    event_pre_minutes: int = 0,
    event_post_minutes: int = 0,
    entry_allowed: Optional[Callable[[datetime, str], bool]] = None,
) -> Result:
    indicators = WilderIndicators(config.ATR_PERIOD, config.ZSCORE_PERIOD, config.ATR_AVG_LOOKBACK)
    initial = balance = peak = float(config.INITIAL_BALANCE_USDT)
    max_drawdown = fees = gross_profit = gross_loss = 0.0
    wins = losses = time_exits = 0
    position: Optional[Position] = None
    daily_state: Optional[TrendState] = None
    h4_state: Optional[TrendState] = None
    h1_state: Optional[TrendState] = None
    m15_state: Optional[TrendState] = None
    pullback: Optional[Pullback] = None
    traded_day = ""
    vetoed_entries = 0
    examples: List[str] = []

    for index, bar in enumerate(bars):
        # Date in source is M5 open. Strategy decisions happen at the bar close.
        decision_time = bar.timestamp + timedelta(minutes=5)
        values = indicators.update(bar)
        if decision_time in d1_states:
            daily_state = d1_states[decision_time]
        if decision_time in h4_states:
            h4_state = h4_states[decision_time]
        if decision_time in h1_states:
            h1_state = h1_states[decision_time]
        if decision_time in m15_states:
            m15_state = m15_states[decision_time]
            direction = trend_direction(variant, daily_state, h4_state, h1_state)
            ema = None
            if m15_state:
                ema = m15_state.ema20 if variant.m15_ema_period == 20 else m15_state.ema50
            if direction and ema is not None:
                if direction == "LONG" and m15_state.bar.low <= ema and m15_state.bar.close >= ema:
                    pullback = Pullback(
                        direction="LONG",
                        low=m15_state.bar.low,
                        high=m15_state.bar.high,
                        created_at=decision_time,
                        expires_at=decision_time + timedelta(minutes=90),
                    )
                elif direction == "SHORT" and m15_state.bar.high >= ema and m15_state.bar.close <= ema:
                    pullback = Pullback(
                        direction="SHORT",
                        low=m15_state.bar.low,
                        high=m15_state.bar.high,
                        created_at=decision_time,
                        expires_at=decision_time + timedelta(minutes=90),
                    )

        if not in_window(decision_time, start, end) or values is None or index < 300:
            continue

        # Position lifecycle comes before entry logic, excluding same-bar exit.
        if position:
            outcome = bar_exit(position, bar, spread)
            reason = None
            if outcome:
                exit_price, reason = outcome
            elif decision_time.hour >= flat_hour or decision_time.date() != position.opened_at.date():
                exit_price, reason = close_at_market(position, bar, spread), "TIME_EXIT"
            if reason:
                gross = (exit_price - position.entry) * position.size if position.direction == "LONG" else (position.entry - exit_price) * position.size
                exit_fee = exit_price * position.size * config.PAPER_TAKER_FEE_RATE
                net = gross - position.entry_fee - exit_fee
                balance = max(0.0, balance + net)
                fees += position.entry_fee + exit_fee
                if reason == "TIME_EXIT":
                    time_exits += 1
                if net > 0:
                    wins += 1
                    gross_profit += net
                elif net < 0:
                    losses += 1
                    gross_loss += abs(net)
                peak = max(peak, balance)
                max_drawdown = max(max_drawdown, peak - balance)
                position = None

        if position or balance < 5.0:
            continue
        if not session_start_hour <= decision_time.hour < session_end_hour:
            continue
        if decision_time.hour >= flat_hour or traded_day == decision_time.strftime("%Y-%m-%d"):
            continue
        if pullback is None or decision_time > pullback.expires_at:
            continue
        if trend_direction(variant, daily_state, h4_state, h1_state) != pullback.direction:
            pullback = None
            continue
        # Current close crossing the preceding M5 high/low is the explicit trigger.
        previous = bars[index - 1]
        trigger = (
            pullback.direction == "LONG"
            and bar.close > bar.open
            and bar.close > previous.high
            or pullback.direction == "SHORT"
            and bar.close < bar.open
            and bar.close < previous.low
        )
        if not trigger:
            continue
        if event_veto_active(
            decision_time, event_times, event_pre_minutes, event_post_minutes
        ):
            vetoed_entries += 1
            # A setup that cannot be acted upon inside a news window is not
            # carried forward as a stale post-event entry.
            pullback = None
            continue
        if entry_allowed is not None and not entry_allowed(decision_time, pullback.direction):
            vetoed_entries += 1
            # Macro filters are decision-time gates, not permission to retain
            # a stale pullback until the regime changes later in the day.
            pullback = None
            continue
        position = fill_position(
            bar,
            pullback.direction,
            pullback,
            float(values["atr_14"]),
            balance,
            spread,
            stop_buffer,
            sl_atr,
            rr,
        )
        pullback = None
        if position:
            traded_day = decision_time.strftime("%Y-%m-%d")
            if len(examples) < 5:
                examples.append(f"{decision_time.strftime('%Y-%m-%d %H:%M')} UTC {position.direction}")

    trades = wins + losses
    return Result(
        variant=variant,
        window=window_name,
        trades=trades,
        wins=wins,
        losses=losses,
        time_exits=time_exits,
        final_balance=balance,
        return_pct=(balance / initial - 1.0) * 100.0,
        profit_factor=(gross_profit / gross_loss) if gross_loss else None,
        max_drawdown=max_drawdown,
        fees=fees,
        vetoed_entries=vetoed_entries,
        examples=examples,
    )


def rank_development(results: Sequence[Result]) -> List[Result]:
    def score(result: Result) -> Tuple[float, float, int]:
        if result.trades < 10:
            return (-1_000_000.0, result.return_pct, result.trades)
        pf = result.profit_factor if result.profit_factor is not None else 0.0
        return (pf, result.return_pct, result.trades)

    return sorted(results, key=score, reverse=True)


def markdown_table(results: Sequence[Result]) -> List[str]:
    lines = [
        "| Variant | Trades | W/L | Time exits | Final | Return | PF | DD | Example M5 entries |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for result in results:
        pf = f"{result.profit_factor:.2f}" if result.profit_factor is not None else "n/a"
        lines.append(
            f"| `{result.variant.label()}` | {result.trades} | {result.wins}/{result.losses} | {result.time_exits} | "
            f"${result.final_balance:.2f} | {result.return_pct:+.2f}% | {pf} | ${result.max_drawdown:.2f} | "
            f"{'<br>'.join(result.examples) or '—'} |"
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
    parser.add_argument("csv", nargs="+", help="M5 CSV paths or shell globs")
    parser.add_argument("--spread", type=float, default=0.40)
    parser.add_argument("--stop-buffer", type=float, default=0.20)
    parser.add_argument("--sl-atr", type=float, default=1.5)
    parser.add_argument("--rr", type=float, default=2.0)
    parser.add_argument("--session-start", type=int, default=7)
    parser.add_argument("--session-end", type=int, default=17)
    parser.add_argument("--flat-hour", type=int, default=21)
    parser.add_argument("--report", default="MTF_TREND_PULLBACK_RESEARCH.md")
    parser.add_argument("--results-csv", default="MTF_TREND_PULLBACK_RESEARCH.csv")
    parser.add_argument("--data-revision", default="")
    args = parser.parse_args()
    if min(args.spread, args.stop_buffer, args.sl_atr, args.rr) < 0:
        parser.error("cost and stop values cannot be negative")
    if not 0 <= args.session_start < args.session_end <= 24 or not 0 < args.flat_hour <= 24:
        parser.error("invalid UTC session/flat hours")

    bars = load_csv_parts(args.csv)
    m15 = indicator_states(aggregate(bars, 15))
    h1 = indicator_states(aggregate(bars, 60))
    h4 = indicator_states(aggregate(bars, 240))
    d1 = indicator_states(aggregate_daily(bars))
    variants = [
        Variant("Strict hierarchy", True, 50, 50, 20),
        Variant("No daily filter", False, 50, 50, 20),
        Variant("Faster hierarchy", True, 20, 20, 20),
        Variant("Slow M15 pullback", True, 50, 50, 50),
    ]
    windows = [
        ("Development (2019-09 to 2022-12)", datetime(2019, 9, 6, tzinfo=timezone.utc), datetime(2023, 1, 1, tzinfo=timezone.utc)),
        ("Validation (2023-2024)", datetime(2023, 1, 1, tzinfo=timezone.utc), datetime(2025, 1, 1, tzinfo=timezone.utc)),
        ("Holdout (2025 onward)", datetime(2025, 1, 1, tzinfo=timezone.utc), None),
    ]
    development_name, development_start, development_end = windows[0]
    development = [
        simulate(bars, m15, h1, h4, d1, variant, development_start, development_end, args.spread, args.stop_buffer, args.sl_atr, args.rr, args.session_start, args.session_end, args.flat_hour, development_name)
        for variant in variants
    ]
    ranked = rank_development(development)
    selected = ranked[0].variant
    unseen: List[Result] = []
    strict = variants[0]
    for window_name, start, end in windows[1:]:
        for variant, name in ((strict, "Strict hierarchy"), (selected, "Development-selected")):
            unseen.append(
                simulate(bars, m15, h1, h4, d1, variant, start, end, args.spread, args.stop_buffer, args.sl_atr, args.rr, args.session_start, args.session_end, args.flat_hour, f"{name} — {window_name}")
            )
    all_results = [*development, *unseen]
    write_csv(Path(args.results_csv), all_results)
    report = [
        "# MTF trend-pullback XAU research",
        "",
        "## Model",
        "",
        f"- Source: {len(bars):,} UTC five-minute XAU bars. M15, H1, H4 and D1 bars are derived internally from only completed M5 components.",
        "- Trend layer: D1/H4/H1 close relative to selected EMA20/EMA50 values. Pullback: an M15 touch and close back on the trend side of its EMA. Trigger: M5 directional close beyond the preceding M5 high/low.",
        f"- Intraday lifecycle: new entries only {args.session_start:02d}:00–{args.session_end:02d}:00 UTC; force-flat from {args.flat_hour:02d}:00 UTC / next UTC date; one trade per day.",
        f"- Execution: ${args.spread:.2f} spread, ${config.PAPER_SLIPPAGE_USD:.2f} adverse slippage per fill, {config.PAPER_TAKER_FEE_RATE * 100:.02f}% fee per side, SL-first ambiguity treatment.",
        f"- Stop: farther of M15 pullback extreme + ${args.stop_buffer:.2f} buffer or {args.sl_atr:.1f}×M5 ATR. Target: {args.rr:.1f}R.",
        "- Development selection is limited to 2019-09 through 2022-12. Validation and holdout remain frozen.",
    ]
    if args.data_revision:
        report.append(f"- Data revision: `{args.data_revision}`.")
    report.extend(["", "## Development-only comparison", ""])
    report.extend(markdown_table(ranked))
    report.extend(["", "## Frozen validation and holdout", ""])
    report.extend(markdown_table(unseen))
    report.extend(
        [
            "",
            "## Decision rule",
            "",
            f"Development selected `{selected.label()}` only if it met the 10-trade minimum and ranked best on development PF/return. It is rejected unless both unseen windows show sufficient trades and net PF above 1 after the same costs.",
            "",
            f"Every result is in [`{Path(args.results_csv).name}`]({Path(args.results_csv).name}).",
        ]
    )
    Path(args.report).write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"Development-selected variant: {selected.label()}")
    for result in unseen:
        print(f"{result.window}: trades={result.trades} final=${result.final_balance:.2f} return={result.return_pct:+.2f}% PF={result.profit_factor}")


if __name__ == "__main__":
    main()
