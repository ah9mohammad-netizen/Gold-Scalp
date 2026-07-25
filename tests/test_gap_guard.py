"""Universal gap guard must block and flatten around non-routine holes."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from scripts.backtest_v5_csv import Bar
from scripts.gap_guard import GapGuard


class GapGuardTests(unittest.TestCase):
    @staticmethod
    def bar(timestamp: datetime) -> Bar:
        return Bar(timestamp, 3000.0, 3001.0, 2999.0, 3000.0, 1.0)

    def test_non_routine_gap_blocks_recent_entries_and_force_flats(self) -> None:
        start = datetime(2025, 1, 6, 10, 0, tzinfo=timezone.utc)
        bars = [self.bar(start + timedelta(minutes=5 * index)) for index in range(4)]
        # A three-hour midweek interruption begins after 10:15.
        bars.append(self.bar(start + timedelta(hours=3, minutes=20)))
        guard = GapGuard(bars, pre_gap_minutes=10)
        self.assertEqual(guard.non_routine_gap_count, 1)
        self.assertTrue(guard.force_flat_after(start + timedelta(minutes=15)))
        self.assertFalse(guard.entry_allowed(start + timedelta(minutes=10)))
        self.assertFalse(guard.entry_allowed(start + timedelta(minutes=15)))
        self.assertTrue(guard.entry_allowed(start))

    def test_regular_maintenance_is_not_force_flat_event(self) -> None:
        start = datetime(2025, 1, 6, 23, 55, tzinfo=timezone.utc)
        bars = [self.bar(start), self.bar(start + timedelta(minutes=65))]
        guard = GapGuard(bars)
        self.assertEqual(guard.non_routine_gap_count, 0)
        self.assertFalse(guard.force_flat_after(start))


if __name__ == "__main__":
    unittest.main()
