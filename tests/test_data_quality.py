"""Data-gap classification regression tests."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

from scripts.audit_xau_data_quality import classify_gap
from scripts.backtest_v5_csv import Bar


class DataQualityTests(unittest.TestCase):
    @staticmethod
    def bar(timestamp: datetime) -> Bar:
        return Bar(timestamp, 3000.0, 3001.0, 2999.0, 3000.0, 1.0)

    def test_regular_daily_closure_is_not_classed_as_unresolved(self) -> None:
        previous = self.bar(datetime(2024, 1, 2, 23, 55, tzinfo=timezone.utc))
        current = self.bar(datetime(2024, 1, 3, 1, 0, tzinfo=timezone.utc))
        self.assertEqual(classify_gap(previous, current), "regular_daily_closure")

    def test_weekend_closure_is_expected(self) -> None:
        previous = self.bar(datetime(2024, 1, 5, 23, 55, tzinfo=timezone.utc))  # Friday
        current = self.bar(datetime(2024, 1, 8, 1, 0, tzinfo=timezone.utc))  # Monday
        self.assertEqual(classify_gap(previous, current), "weekend_closure")

    def test_multi_day_midweek_void_is_extended_gap(self) -> None:
        previous = self.bar(datetime(2025, 9, 12, 23, 45, tzinfo=timezone.utc))
        current = self.bar(datetime(2025, 10, 15, 7, 55, tzinfo=timezone.utc))
        self.assertEqual(classify_gap(previous, current), "extended_non_weekend_gap")


if __name__ == "__main__":
    unittest.main()
