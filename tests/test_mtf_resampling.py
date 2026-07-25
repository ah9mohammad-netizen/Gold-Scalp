"""Regression tests for UTC MTF aggregation and closed-parent-bar boundaries."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from scripts.backtest_mtf_trend_pullback import aggregate, floor_time
from scripts.backtest_v5_csv import Bar


class MtfResamplingTests(unittest.TestCase):
    @staticmethod
    def make_bars(start: datetime, count: int) -> list[Bar]:
        bars = []
        for index in range(count):
            value = 3000.0 + index
            bars.append(
                Bar(
                    timestamp=start + timedelta(minutes=5 * index),
                    open=value,
                    high=value + 2,
                    low=value - 1,
                    close=value + 1,
                    volume=float(index + 1),
                )
            )
        return bars

    def test_four_hour_floor_uses_utc_blocks(self) -> None:
        timestamp = datetime(2025, 7, 15, 11, 55, tzinfo=timezone.utc)
        self.assertEqual(
            floor_time(timestamp, 240),
            datetime(2025, 7, 15, 8, 0, tzinfo=timezone.utc),
        )

    def test_aggregation_requires_all_m5_components(self) -> None:
        start = datetime(2025, 1, 2, 8, 0, tzinfo=timezone.utc)
        bars = self.make_bars(start, 12)
        hourly = aggregate(bars, 60)
        self.assertEqual(len(hourly), 1)
        parent = hourly[0]
        self.assertEqual(parent.start, start)
        self.assertEqual(parent.end, start + timedelta(hours=1))
        self.assertEqual(parent.open, 3000.0)
        self.assertEqual(parent.close, 3012.0)
        self.assertEqual(parent.high, 3013.0)
        self.assertEqual(parent.low, 2999.0)
        self.assertEqual(parent.volume, sum(range(1, 13)))

        # An incomplete hourly parent is dropped instead of being made visible
        # to a lower-timeframe strategy before it has actually closed.
        self.assertEqual(aggregate(bars[:-1], 60), [])


if __name__ == "__main__":
    unittest.main()
