#!/usr/bin/env python3
"""Audit the supplied XAU five-minute history before trusting any backtest.

The audit intentionally distinguishes regular session closures from unresolved
holes. It does not interpolate or fabricate any missing bar. Its output is a
Markdown summary plus a CSV of every non-routine gap requiring source review.
"""
from __future__ import annotations

import argparse
import csv
import math
import statistics
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.backtest_v5_csv import Bar, load_csv_parts


def classify_gap(previous: Bar, current: Bar) -> str:
    gap = current.timestamp - previous.timestamp
    # The series consistently pauses around midnight UTC. A 65-90 minute gap
    # is therefore a known regular maintenance/session closure pattern.
    if gap <= timedelta(minutes=90):
        return "regular_daily_closure"
    if previous.timestamp.weekday() == 4 and current.timestamp.weekday() == 0 and gap >= timedelta(days=1):
        return "weekend_closure"
    if gap > timedelta(days=1):
        return "extended_non_weekend_gap"
    if gap > timedelta(hours=6):
        return "long_intraday_or_holiday_gap"
    return "intraday_gap_requires_review"


def percentile(values: Sequence[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    location = (len(ordered) - 1) * q
    low = int(location)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (location - low)


def fmt_duration(delta: timedelta) -> str:
    seconds = int(delta.total_seconds())
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes = seconds // 60
    if days:
        return f"{days}d {hours}h {minutes}m"
    return f"{hours}h {minutes}m"


def audit(bars: Sequence[Bar]) -> Tuple[Dict[str, object], List[Dict[str, object]]]:
    if not bars:
        raise ValueError("No bars")
    timestamps = [bar.timestamp for bar in bars]
    duplicates = len(timestamps) - len(set(timestamps))
    out_of_order = sum(timestamps[i] >= timestamps[i + 1] for i in range(len(timestamps) - 1))
    invalid_ohlc = 0
    invalid_volume = 0
    daily_counts: Counter[str] = Counter()
    hour_counts: Counter[int] = Counter()
    weekday_counts: Counter[int] = Counter()
    close_returns: List[float] = []
    gap_returns: List[float] = []
    gaps: List[Dict[str, object]] = []

    for index, bar in enumerate(bars):
        daily_counts[bar.timestamp.date().isoformat()] += 1
        hour_counts[bar.timestamp.hour] += 1
        weekday_counts[bar.timestamp.weekday()] += 1
        if not all(math.isfinite(value) for value in (bar.open, bar.high, bar.low, bar.close, bar.volume)):
            invalid_ohlc += 1
        elif min(bar.open, bar.high, bar.low, bar.close) <= 0 or bar.high < max(bar.open, bar.close, bar.low) or bar.low > min(bar.open, bar.close, bar.high):
            invalid_ohlc += 1
        if not math.isfinite(bar.volume) or bar.volume <= 0:
            invalid_volume += 1
        if index == 0:
            continue
        previous = bars[index - 1]
        close_returns.append(bar.close / previous.close - 1.0)
        delta = bar.timestamp - previous.timestamp
        if delta != timedelta(minutes=5):
            gap_returns.append(bar.open / previous.close - 1.0)
            category = classify_gap(previous, bar)
            gaps.append(
                {
                    "previous_timestamp_utc": previous.timestamp.isoformat(),
                    "next_timestamp_utc": bar.timestamp.isoformat(),
                    "gap_minutes": int(delta.total_seconds() // 60),
                    "category": category,
                    "open_gap_return_pct": round((bar.open / previous.close - 1.0) * 100.0, 5),
                    "previous_close": previous.close,
                    "next_open": bar.open,
                }
            )

    unresolved = [gap for gap in gaps if gap["category"] not in {"regular_daily_closure", "weekend_closure"}]
    extended = [gap for gap in unresolved if int(gap["gap_minutes"]) >= 24 * 60]
    critical = [gap for gap in unresolved if int(gap["gap_minutes"]) > 7 * 24 * 60]
    stats: Dict[str, object] = {
        "bars": len(bars),
        "first_timestamp": bars[0].timestamp.isoformat(),
        "last_timestamp": bars[-1].timestamp.isoformat(),
        "duplicates": duplicates,
        "out_of_order": out_of_order,
        "invalid_ohlc": invalid_ohlc,
        "invalid_volume": invalid_volume,
        "price_low": min(bar.low for bar in bars),
        "price_high": max(bar.high for bar in bars),
        "daily_count_distribution": Counter(daily_counts.values()),
        "hour_counts": hour_counts,
        "weekday_counts": weekday_counts,
        "all_gaps": len(gaps),
        "gap_categories": Counter(str(gap["category"]) for gap in gaps),
        "unresolved_gaps": len(unresolved),
        "extended_non_weekend_gaps": len(extended),
        "critical_unexplained_gaps": len(critical),
        "largest_close_return_pct": max(close_returns) * 100.0,
        "smallest_close_return_pct": min(close_returns) * 100.0,
        "largest_gap_return_pct": max(gap_returns) * 100.0,
        "smallest_gap_return_pct": min(gap_returns) * 100.0,
        "return_abs_p99_pct": percentile([abs(value) * 100.0 for value in close_returns], 0.99),
    }
    return stats, unresolved


def write_gap_csv(path: Path, gaps: Sequence[Dict[str, object]]) -> None:
    fields = [
        "previous_timestamp_utc",
        "next_timestamp_utc",
        "gap_minutes",
        "category",
        "open_gap_return_pct",
        "previous_close",
        "next_open",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(gaps)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", nargs="+", help="XAU M5 CSV paths or glob patterns")
    parser.add_argument("--report", default="XAU_DATA_QUALITY_AUDIT.md")
    parser.add_argument("--gaps-csv", default="XAU_DATA_QUALITY_GAPS.csv")
    parser.add_argument("--data-revision", default="")
    args = parser.parse_args()
    bars = load_csv_parts(args.csv)
    stats, unresolved = audit(bars)
    write_gap_csv(Path(args.gaps_csv), unresolved)

    major = sorted(unresolved, key=lambda gap: int(gap["gap_minutes"]), reverse=True)[:20]
    report = [
        "# XAU 5-minute data-quality audit",
        "",
        "## Integrity checks",
        "",
        f"- Bars: **{stats['bars']:,}**",
        f"- Coverage: `{stats['first_timestamp']}` through `{stats['last_timestamp']}`",
        f"- Duplicate timestamps: **{stats['duplicates']}**",
        f"- Out-of-order timestamp pairs: **{stats['out_of_order']}**",
        f"- Invalid OHLC rows: **{stats['invalid_ohlc']}**",
        f"- Non-positive/invalid volume rows: **{stats['invalid_volume']}**",
        f"- Price range: **${float(stats['price_low']):.2f}–${float(stats['price_high']):.2f}**",
        "",
        "## Session pattern",
        "",
        "The source is a weekday-only series. Most full days contain 274 or 276 bars rather than 288, consistent with a recurring around-midnight UTC maintenance/session closure. This is not automatically corruption, but every strategy must treat it as a non-tradable gap.",
        "",
        f"- Daily bar-count distribution: `{dict(stats['daily_count_distribution'])}`",
        f"- Total non-5m gaps: **{stats['all_gaps']}**",
        f"- Gap categories: `{dict(stats['gap_categories'])}`",
        f"- Unresolved non-routine gaps: **{stats['unresolved_gaps']}**",
        f"- Extended non-weekend gaps ≥24h: **{stats['extended_non_weekend_gaps']}** (this includes documented holiday/early-close periods)",
        f"- Critical unexplained gaps >7 days: **{stats['critical_unexplained_gaps']}**",
        "",
        "## Return sanity",
        "",
        f"- Largest single M5 close-to-close return: **{float(stats['largest_close_return_pct']):+.3f}%**",
        f"- Smallest single M5 close-to-close return: **{float(stats['smallest_close_return_pct']):+.3f}%**",
        f"- 99th percentile absolute M5 close return: **{float(stats['return_abs_p99_pct']):.3f}%**",
        f"- Largest inter-gap open jump: **{float(stats['largest_gap_return_pct']):+.3f}%**",
        f"- Smallest inter-gap open jump: **{float(stats['smallest_gap_return_pct']):+.3f}%**",
        "",
        "## Major unresolved gaps requiring source confirmation",
        "",
        "| Previous UTC bar | Next UTC bar | Gap | Category | Open jump |",
        "|---|---|---:|---|---:|",
    ]
    for gap in major:
        report.append(
            f"| {gap['previous_timestamp_utc']} | {gap['next_timestamp_utc']} | "
            f"{fmt_duration(timedelta(minutes=int(gap['gap_minutes'])))} | {gap['category']} | "
            f"{float(gap['open_gap_return_pct']):+.3f}% |"
        )
    report.extend(
        [
            "",
            "## Backtest consequence",
            "",
            "The data passes basic OHLC ordering and positivity checks, but unresolved holes mean that an apparent outcome across a hole cannot be treated as a normal M5 trade path. Earlier results that allowed positions to remain open across an unresolved gap are provisional. Intraday research should either close positions before any non-routine gap or exclude the candidate/window; it must never invent missing bars or assume a stop/target sequence inside the void.",
            "",
            "## Required remediation",
            "",
            "1. **Mandatory:** obtain source-consistent UTC M5 replacement bars for the 32-day September–October 2025 void and the 9-day January 2026 void. These are not normal market closures.",
            "2. Review shorter `intraday_gap_requires_review` rows against documented broker/exchange maintenance and holiday schedules. Many extended gaps are likely holiday/early-close periods and should remain explicit no-trade intervals, not be filled.",
            "3. Keep routine daily maintenance, weekends, and documented holidays as explicit no-trade intervals rather than fabricating bars.",
            "4. Re-run all strategy comparisons with a gap guard: no new position close to a non-routine gap; open positions are excluded/force-flattened at the last known pre-gap bar under a declared policy.",
            "5. Do not use the present 2025 holdout as final evidence until the two critical voids are repaired or the affected dates are explicitly excluded from every comparison.",
            "",
            f"The machine-readable remediation list is [`{Path(args.gaps_csv).name}`]({Path(args.gaps_csv).name}).",
        ]
    )
    if args.data_revision:
        report.insert(5, f"- Data revision: `{args.data_revision}`")
    Path(args.report).write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"Unresolved gaps: {len(unresolved)}; extended non-weekend gaps: {len([g for g in unresolved if int(g['gap_minutes']) >= 24 * 60])}")


if __name__ == "__main__":
    main()
