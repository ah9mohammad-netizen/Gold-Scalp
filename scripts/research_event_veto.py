#!/usr/bin/env python3
"""Phase 4A: test a calendar-only USD event veto on the XAU MTF pullback.

The supplied ForexFactory-style CSV contains date-header rows and event rows in
Asia/Tehran display time. This script normalizes it with ``ZoneInfo`` to UTC,
uses only named high-impact USD event families, and does not use actual versus
forecast values. The first purpose is risk avoidance, not news-direction
prediction.

Coverage begins in August 2023, so this test uses only calendar-covered periods:
  development: 2023-08 through 2024-06
  validation:  2024-07 through 2024-12
  holdout:     2025-01 through 2026-01
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import config
from scripts.backtest_mtf_trend_pullback import (
    Result,
    Variant,
    aggregate,
    aggregate_daily,
    indicator_states,
    load_csv_parts,
    simulate,
)

CALENDAR_ZONE = ZoneInfo("Asia/Tehran")

# A fixed, predeclared core set. It corresponds to the releases most commonly
# associated with abrupt USD-rate repricing; it is not fitted to trade results.
CORE_PATTERNS = (
    "cpi",
    "ppi",
    "nonfarm payrolls",
    "unemployment rate",
    "average hourly earnings",
    "fed interest rate decision",
    "fomc statement",
    "fomc press conference",
    "fomc economic projections",
)
EXTENDED_PATTERNS = CORE_PATTERNS + (
    "core pce",
    "pce price",
    "gdp (qoq)",
    "retail sales",
    "ism manufacturing pmi",
    "ism non-manufacturing pmi",
)


@dataclass(frozen=True)
class CalendarEvent:
    timestamp: datetime
    title: str
    bucket: str


@dataclass(frozen=True)
class VetoVariant:
    name: str
    patterns: Tuple[str, ...]
    pre_minutes: int
    post_minutes: int

    def label(self) -> str:
        if not self.patterns:
            return "No event veto"
        scope = "Core USD" if self.patterns == CORE_PATTERNS else "Extended USD"
        return f"{scope} veto {self.pre_minutes}m before / {self.post_minutes}m after"


@dataclass
class Evaluation:
    veto: VetoVariant
    window: str
    result: Result

    def row(self) -> Dict[str, object]:
        row = asdict(self.veto)
        row.update(
            {
                "label": self.veto.label(),
                "window": self.window,
                "trades": self.result.trades,
                "wins": self.result.wins,
                "losses": self.result.losses,
                "time_exits": self.result.time_exits,
                "vetoed_entries": self.result.vetoed_entries,
                "final_balance": round(self.result.final_balance, 4),
                "return_pct": round(self.result.return_pct, 4),
                "profit_factor": self.result.profit_factor,
                "max_realized_drawdown": round(self.result.max_drawdown, 4),
                "fees": round(self.result.fees, 4),
                "example_entries": "; ".join(self.result.examples),
            }
        )
        return row


def parse_date_header(text: str) -> date | None:
    text = text.strip()
    if not text or not re.match(r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),", text):
        return None
    return datetime.strptime(text, "%A, %B %d, %Y").date()


def is_selected(title: str, patterns: Sequence[str]) -> bool:
    normalized = title.lower()
    return any(pattern in normalized for pattern in patterns)


def parse_calendar(path: Path, patterns: Sequence[str]) -> List[CalendarEvent]:
    current_date: date | None = None
    events: List[CalendarEvent] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        next(reader, None)
        for row in reader:
            if not row:
                continue
            header = parse_date_header(row[0])
            if header is not None:
                current_date = header
                continue
            if current_date is None or len(row) < 3 or row[1].strip().upper() != "US":
                continue
            raw_time = row[0].strip()
            title = row[2].strip()
            if not raw_time or not title or not is_selected(title, patterns):
                continue
            try:
                local_time = datetime.strptime(raw_time, "%H:%M").time()
            except ValueError:
                continue
            local = datetime.combine(current_date, local_time, tzinfo=CALENDAR_ZONE)
            bucket = next(pattern for pattern in patterns if pattern in title.lower())
            events.append(CalendarEvent(local.astimezone(timezone.utc), title, bucket))
    # Several rows at the same timestamp belong to a single release bundle.
    # Keep names for reporting but deduplicate the time for veto evaluation.
    events.sort(key=lambda event: event.timestamp)
    return events


def event_times(events: Iterable[CalendarEvent]) -> List[datetime]:
    return sorted({event.timestamp for event in events})


def rank_development(evaluations: Sequence[Evaluation]) -> List[Evaluation]:
    def score(evaluation: Evaluation) -> Tuple[float, float, int]:
        result = evaluation.result
        if result.trades < 20:
            return (-1_000_000.0, result.return_pct, result.trades)
        pf = result.profit_factor if result.profit_factor is not None else 0.0
        return (pf, result.return_pct, result.trades)

    return sorted(evaluations, key=score, reverse=True)


def table(evaluations: Sequence[Evaluation]) -> List[str]:
    lines = [
        "| Veto policy | Trades | W/L | Vetoed entries | Final | Return | PF | DD |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for evaluation in evaluations:
        result = evaluation.result
        pf = f"{result.profit_factor:.2f}" if result.profit_factor is not None else "n/a"
        lines.append(
            f"| `{evaluation.veto.label()}` | {result.trades} | {result.wins}/{result.losses} | "
            f"{result.vetoed_entries} | ${result.final_balance:.2f} | {result.return_pct:+.2f}% | "
            f"{pf} | ${result.max_drawdown:.2f} |"
        )
    return lines


def write_csv(path: Path, evaluations: Sequence[Evaluation]) -> None:
    rows = [evaluation.row() for evaluation in evaluations]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", nargs="+", help="UTC M5 XAU CSV paths or glob patterns")
    parser.add_argument("--calendar", required=True, help="ForexFactory-style calendar CSV")
    parser.add_argument("--spread", type=float, default=0.40)
    parser.add_argument("--report", default="XAU_EVENT_VETO_RESEARCH.md")
    parser.add_argument("--results-csv", default="XAU_EVENT_VETO_RESEARCH.csv")
    parser.add_argument("--data-revision", default="")
    args = parser.parse_args()
    if args.spread < 0:
        parser.error("spread must be non-negative")

    bars = load_csv_parts(args.csv)
    m15 = indicator_states(aggregate(bars, 15))
    h1 = indicator_states(aggregate(bars, 60))
    h4 = indicator_states(aggregate(bars, 240))
    d1 = indicator_states(aggregate_daily(bars))
    # Frozen MTF variant from the preceding test; event policy is the only
    # variable in this phase.
    trend_variant = Variant("Slow M15 pullback", True, 50, 50, 50)
    core_events = parse_calendar(Path(args.calendar), CORE_PATTERNS)
    extended_events = parse_calendar(Path(args.calendar), EXTENDED_PATTERNS)
    if not core_events:
        raise RuntimeError("No selected USD events parsed; verify CSV format/timezone.")

    vetoes = [
        VetoVariant("No veto", (), 0, 0),
        VetoVariant("Core 30/30", CORE_PATTERNS, 30, 30),
        VetoVariant("Core 60/60", CORE_PATTERNS, 60, 60),
        VetoVariant("Extended 30/30", EXTENDED_PATTERNS, 30, 30),
    ]
    calendar_start = datetime(2023, 8, 9, tzinfo=timezone.utc)
    windows = [
        ("Development (calendar-covered 2023-08 to 2024-06)", calendar_start, datetime(2024, 7, 1, tzinfo=timezone.utc)),
        ("Validation (2024-07 to 2024-12)", datetime(2024, 7, 1, tzinfo=timezone.utc), datetime(2025, 1, 1, tzinfo=timezone.utc)),
        ("Holdout (2025-01 onward)", datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2026, 2, 1, tzinfo=timezone.utc)),
    ]

    def run(veto: VetoVariant, window: Tuple[str, datetime, datetime]) -> Evaluation:
        name, start, end = window
        events = event_times(core_events if veto.patterns == CORE_PATTERNS else extended_events)
        result = simulate(
            bars, m15, h1, h4, d1, trend_variant, start, end,
            args.spread, 0.20, 1.5, 2.0, 7, 17, 21, name,
            events, veto.pre_minutes, veto.post_minutes,
        )
        return Evaluation(veto, name, result)

    development = [run(veto, windows[0]) for veto in vetoes]
    ranked = rank_development(development)
    selected = ranked[0].veto
    unseen: List[Evaluation] = []
    for window in windows[1:]:
        unseen.append(run(vetoes[0], window))
        unseen.append(run(selected, window))
    all_evaluations = [*development, *unseen]
    write_csv(Path(args.results_csv), all_evaluations)

    type_counts: Dict[str, int] = {}
    for event in core_events:
        type_counts[event.bucket] = type_counts.get(event.bucket, 0) + 1
    core_times = event_times(core_events)
    report = [
        "# XAU macro-event veto research",
        "",
        "## Scope and data provenance",
        "",
        f"- Price source: {len(bars):,} XAU UTC five-minute bars; M15/H1/H4/D1 derived only from completed M5 bars.",
        "- Calendar source: user-supplied ForexFactory-style export from the main branch, parsed as `Asia/Tehran` display time and converted to UTC with IANA timezone rules.",
        f"- Calendar coverage used: {core_times[0].isoformat()} through {core_times[-1].isoformat()}.",
        f"- Core USD event bundles: {len(core_times)} unique timestamps / {len(core_events)} event rows.",
        "- This phase uses a news veto only. Actual/forecast values are intentionally not used for directional prediction.",
        f"- Costs: ${args.spread:.2f} spread, ${config.PAPER_SLIPPAGE_USD:.2f} adverse slippage per fill, {config.PAPER_TAKER_FEE_RATE * 100:.02f}% fee per side.",
        "- Base strategy fixed: D1/H4/H1 EMA50 trend state, M15 EMA50 pullback, M5 directional trigger, 2R target, force-flat 21:00 UTC. Only the veto policy changes.",
    ]
    if args.data_revision:
        report.append(f"- XAU data revision: `{args.data_revision}`.")
    report.extend(["", "## Core event taxonomy", ""])
    for bucket, count in sorted(type_counts.items()):
        report.append(f"- `{bucket}`: {count} CSV rows")
    report.extend(["", "## Development-only veto comparison", ""])
    report.extend(table(ranked))
    report.extend(["", "## Frozen validation and holdout", ""])
    report.extend(table(unseen))
    report.extend(
        [
            "",
            "## Decision rule",
            "",
            f"The development-selected policy is `{selected.label()}`. It is rejected unless it produces adequate trade count and net PF above 1 in both later windows. A veto may reduce exposure; it does not create permission to trade a weak base setup.",
            "",
            f"All results are in [`{Path(args.results_csv).name}`]({Path(args.results_csv).name}).",
        ]
    )
    Path(args.report).write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"Parsed {len(core_times)} core USD event timestamps in UTC.")
    print(f"Development-selected veto: {selected.label()}")
    for evaluation in unseen:
        result = evaluation.result
        print(f"{evaluation.window} | {evaluation.veto.label()}: trades={result.trades} final=${result.final_balance:.2f} return={result.return_pct:+.2f}% PF={result.profit_factor}")


if __name__ == "__main__":
    main()
