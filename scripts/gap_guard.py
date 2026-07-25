"""Shared gap policy for historical intraday research.

A gap guard never manufactures a path through missing candles. It recognizes
short recurring maintenance breaks and weekends, then treats all other gaps as
non-routine: entries are blocked near the last pre-gap bar and an open position
is force-flattened at the last observable executable close.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, List, Sequence, Set


@dataclass(frozen=True)
class Gap:
    previous: datetime
    following: datetime
    duration: timedelta
    category: str


def classify_gap(previous: datetime, following: datetime) -> str:
    duration = following - previous
    if duration <= timedelta(minutes=90):
        return "regular_daily_closure"
    # Canonical UTC sources commonly resume Sunday evening; tolerate either
    # Sunday or Monday for different broker session conventions.
    if previous.weekday() == 4 and following.weekday() in (6, 0) and duration >= timedelta(days=1):
        return "weekend_closure"
    if duration > timedelta(days=1):
        return "extended_non_weekend_gap"
    return "intraday_gap_requires_review"


class GapGuard:
    def __init__(self, bars: Sequence[object], pre_gap_minutes: int = 60):
        timestamps = [getattr(bar, "timestamp") for bar in bars]
        self.pre_gap_minutes = pre_gap_minutes
        self.gaps: List[Gap] = []
        self.force_flat_timestamps: Set[datetime] = set()
        self.entry_blocked_timestamps: Set[datetime] = set()
        for index, (previous, following) in enumerate(zip(timestamps, timestamps[1:])):
            if following - previous == timedelta(minutes=5):
                continue
            category = classify_gap(previous, following)
            gap = Gap(previous, following, following - previous, category)
            self.gaps.append(gap)
            if category in {"regular_daily_closure", "weekend_closure"}:
                continue
            self.force_flat_timestamps.add(previous)
            block_start = previous - timedelta(minutes=pre_gap_minutes)
            cursor = index
            while cursor >= 0 and timestamps[cursor] >= block_start:
                self.entry_blocked_timestamps.add(timestamps[cursor])
                cursor -= 1

    def force_flat_after(self, timestamp: datetime) -> bool:
        return timestamp in self.force_flat_timestamps

    def entry_allowed(self, timestamp: datetime) -> bool:
        return timestamp not in self.entry_blocked_timestamps

    @property
    def non_routine_gap_count(self) -> int:
        return sum(g.category not in {"regular_daily_closure", "weekend_closure"} for g in self.gaps)
