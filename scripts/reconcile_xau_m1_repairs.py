#!/usr/bin/env python3
"""Validate and use native M1 XAU data to repair M5 source holes.

The supplied M5 source labels are empirically consistent with Europe/Helsinki
broker-server time, not raw UTC: treating M5 labels as Helsinki local and M1
labels as UTC produces ~0.997 aligned M5-return correlation through their
normal overlap. The script normalizes both to canonical UTC, aggregates native
M1 to exact M5 bars, verifies overlap quality, then fills only missing M5
intervals with complete M1 aggregates.

It never overwrites original M5 bars, invents no bars in M1 gaps, and writes a
source/provenance column. Outputs are deliberately local artifacts, not Git
history, because the canonical dataset is large.
"""
from __future__ import annotations

import argparse
import csv
import glob
import math
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@dataclass(frozen=True)
class Candle:
    timestamp: datetime  # naive UTC canonical timestamp
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str


def paths_from_patterns(patterns: Sequence[str]) -> List[Path]:
    result: List[Path] = []
    for pattern in patterns:
        matches = [Path(item) for item in glob.glob(pattern)]
        result.extend(matches or [Path(pattern)])
    return result


def m5_source_time_to_utc(text: str, zone: ZoneInfo) -> datetime:
    local = datetime.strptime(text, "%Y.%m.%d %H:%M").replace(tzinfo=zone)
    return local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


def load_m5(paths: Sequence[Path], zone: ZoneInfo) -> Dict[datetime, Candle]:
    result: Dict[datetime, Candle] = {}
    for path in paths:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=";")
            for row in reader:
                timestamp = m5_source_time_to_utc(row["Date"], zone)
                candle = Candle(
                    timestamp,
                    float(row["Open"]),
                    float(row["High"]),
                    float(row["Low"]),
                    float(row["Close"]),
                    float(row.get("Volume") or 0.0),
                    "M5_ORIGINAL",
                )
                if timestamp in result:
                    raise ValueError(f"Duplicate canonical M5 timestamp: {timestamp}")
                result[timestamp] = candle
    return result


def load_m1_aggregate(paths: Sequence[Path], zone: ZoneInfo) -> Dict[datetime, Candle]:
    groups: Dict[datetime, List[Candle]] = defaultdict(list)
    for path in paths:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                local = datetime.strptime(row["Date"] + row["Timestamp"], "%Y%m%d%H:%M:%S").replace(tzinfo=zone)
                timestamp = local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
                start = timestamp.replace(minute=(timestamp.minute // 5) * 5, second=0, microsecond=0)
                groups[start].append(
                    Candle(
                        timestamp,
                        float(row["Open"]),
                        float(row["High"]),
                        float(row["Low"]),
                        float(row["Close"]),
                        float(row.get("Volume") or 0.0),
                        "M1_AGGREGATED",
                    )
                )
    result: Dict[datetime, Candle] = {}
    for start, bars in groups.items():
        bars.sort(key=lambda item: item.timestamp)
        if len(bars) != 5 or any(bars[i].timestamp != start + timedelta(minutes=i) for i in range(5)):
            continue
        result[start] = Candle(
            start,
            bars[0].open,
            max(bar.high for bar in bars),
            min(bar.low for bar in bars),
            bars[-1].close,
            sum(bar.volume for bar in bars),
            "M1_AGGREGATED",
        )
    return result


def correlation(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) < 2:
        return 0.0
    lm = sum(left) / len(left)
    rm = sum(right) / len(right)
    numerator = sum((a - lm) * (b - rm) for a, b in zip(left, right))
    denominator = math.sqrt(sum((a - lm) ** 2 for a in left) * sum((b - rm) ** 2 for b in right))
    return numerator / denominator if denominator else 0.0


def overlap_metrics(m5: Dict[datetime, Candle], m1: Dict[datetime, Candle]) -> Dict[str, float]:
    common = sorted(set(m5) & set(m1))
    if not common:
        raise ValueError("No M5/M1 overlap after timezone normalization")
    close_diffs = [m1[t].close - m5[t].close for t in common]
    returns_left: List[float] = []
    returns_right: List[float] = []
    for timestamp in common:
        previous = timestamp - timedelta(minutes=5)
        if previous in m5 and previous in m1:
            returns_left.append(m5[timestamp].close / m5[previous].close - 1.0)
            returns_right.append(m1[timestamp].close / m1[previous].close - 1.0)
    return {
        "overlap_bars": float(len(common)),
        "median_abs_close_difference": statistics.median(abs(value) for value in close_diffs),
        "p95_abs_close_difference": sorted(abs(value) for value in close_diffs)[int(0.95 * (len(close_diffs) - 1))],
        "return_correlation": correlation(returns_left, returns_right),
        "median_abs_return_difference_bps": statistics.median(abs(a - b) * 10_000 for a, b in zip(returns_left, returns_right)),
    }


def merge(m5: Dict[datetime, Candle], m1: Dict[datetime, Candle]) -> Tuple[List[Candle], List[Candle]]:
    if not m5:
        return [], []
    start, end = min(m5), max(m5)
    merged = dict(m5)
    inserted: List[Candle] = []
    for timestamp, candle in m1.items():
        if start <= timestamp <= end and timestamp not in merged:
            merged[timestamp] = candle
            inserted.append(candle)
    return [merged[key] for key in sorted(merged)], sorted(inserted, key=lambda item: item.timestamp)


def write_canonical(path: Path, candles: Iterable[Candle]) -> None:
    fields = ["timestamp_utc", "open", "high", "low", "close", "volume", "source"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for candle in candles:
            writer.writerow(
                {
                    "timestamp_utc": candle.timestamp.isoformat() + "Z",
                    "open": f"{candle.open:.6f}",
                    "high": f"{candle.high:.6f}",
                    "low": f"{candle.low:.6f}",
                    "close": f"{candle.close:.6f}",
                    "volume": f"{candle.volume:.8f}",
                    "source": candle.source,
                }
            )


def write_inserted(path: Path, candles: Iterable[Candle]) -> None:
    fields = ["timestamp_utc", "open", "high", "low", "close", "volume", "source"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for candle in candles:
            writer.writerow(
                {
                    "timestamp_utc": candle.timestamp.isoformat() + "Z",
                    "open": f"{candle.open:.6f}",
                    "high": f"{candle.high:.6f}",
                    "low": f"{candle.low:.6f}",
                    "close": f"{candle.close:.6f}",
                    "volume": f"{candle.volume:.8f}",
                    "source": candle.source,
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--m5", nargs="+", required=True, help="original M5 semicolon-CSV paths/globs")
    parser.add_argument("--m1", nargs="+", required=True, help="M1 comma-CSV paths/globs")
    parser.add_argument("--m5-timezone", default="Europe/Helsinki", help="IANA zone of original M5 Date labels")
    parser.add_argument("--m1-timezone", default="UTC", help="IANA zone of M1 Date/Timestamp labels")
    parser.add_argument("--output", required=True, help="local canonical merged UTC M5 CSV output")
    parser.add_argument("--inserted", required=True, help="local M1-derived repair provenance CSV")
    parser.add_argument("--report", required=True, help="local reconciliation report")
    args = parser.parse_args()

    m5 = load_m5(paths_from_patterns(args.m5), ZoneInfo(args.m5_timezone))
    m1 = load_m1_aggregate(paths_from_patterns(args.m1), ZoneInfo(args.m1_timezone))
    metrics = overlap_metrics(m5, m1)
    merged, inserted = merge(m5, m1)
    write_canonical(Path(args.output), merged)
    write_inserted(Path(args.inserted), inserted)
    report = [
        "# XAU M1-to-M5 repair reconciliation",
        "",
        "## Time normalization",
        "",
        f"- Original M5 label timezone: `{args.m5_timezone}` → canonical UTC",
        f"- Native M1 label timezone: `{args.m1_timezone}` → canonical UTC",
        "- This mapping was chosen from overlap return alignment, not from a guessed static hour offset. IANA daylight-saving rules are applied per timestamp.",
        "",
        "## Overlap validation",
        "",
        f"- Complete overlapping M5 bars: **{int(metrics['overlap_bars']):,}**",
        f"- M5 return correlation: **{metrics['return_correlation']:.6f}**",
        f"- Median absolute M5 return difference: **{metrics['median_abs_return_difference_bps']:.3f} bps**",
        f"- Median absolute M5 close difference: **${metrics['median_abs_close_difference']:.3f}**",
        f"- 95th-percentile absolute M5 close difference: **${metrics['p95_abs_close_difference']:.3f}**",
        "",
        "## Merge policy",
        "",
        "- Original M5 rows are never overwritten.",
        "- Only complete five-minute aggregates built from five contiguous native M1 bars are inserted.",
        "- M1 maintenance/weekend gaps remain gaps; no synthetic bars are created.",
        f"- M1-derived M5 repair rows inserted: **{len(inserted):,}**",
        f"- Canonical merged row count: **{len(merged):,}**",
        "",
        "The output and provenance files are local analysis artifacts. They should not be committed as a new source dataset until a final gap audit and strategy rerun are complete.",
    ]
    Path(args.report).write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"Return correlation: {metrics['return_correlation']:.6f}; inserted M1-derived M5 bars: {len(inserted):,}")


if __name__ == "__main__":
    main()
