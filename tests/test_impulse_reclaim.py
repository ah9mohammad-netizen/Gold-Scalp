"""Structural impulse/pullback/reclaim state-machine tests."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from scripts.backtest_mtf_trend_pullback import AggregateBar, TrendState
from scripts.research_impulse_reclaim_discovery import Definition, Impulse, Pullback, m15_reclaim


class ImpulseReclaimTests(unittest.TestCase):
    def test_long_reclaim_uses_prior_pullback_swing_not_current_high(self) -> None:
        start = datetime(2024, 1, 2, 12, 0, tzinfo=timezone.utc)
        impulse = Impulse("LONG", high=110.0, low=100.0, created_at=start, expires_at=start + timedelta(hours=4))
        pullback = Pullback(impulse, low=104.0, high=106.0, created_at=start + timedelta(minutes=15))
        current = TrendState(
            AggregateBar(
                start=start + timedelta(minutes=30),
                end=start + timedelta(minutes=45),
                open=105.0,
                high=108.0,
                low=104.5,
                close=106.5,
                volume=1.0,
            ),
            ema20=105.5,
            ema50=104.0,
        )
        updated, reclaim = m15_reclaim(
            current,
            impulse,
            pullback,
            Definition("test", 1.25, 0.25, 0.60, 240),
        )
        self.assertIsNone(updated)
        self.assertIsNotNone(reclaim)
        assert reclaim is not None
        self.assertEqual(reclaim.pullback.high, 106.0)

    def test_pullback_invalidates_when_retracement_breaks_limit(self) -> None:
        start = datetime(2024, 1, 2, 12, 0, tzinfo=timezone.utc)
        impulse = Impulse("LONG", high=110.0, low=100.0, created_at=start, expires_at=start + timedelta(hours=4))
        pullback = Pullback(impulse, low=104.0, high=106.0, created_at=start + timedelta(minutes=15))
        invalid = TrendState(
            AggregateBar(
                start=start + timedelta(minutes=30),
                end=start + timedelta(minutes=45),
                open=104.0,
                high=105.0,
                low=103.5,  # 65% retracement exceeds the 60% maximum.
                close=104.0,
                volume=1.0,
            ),
            ema20=105.0,
            ema50=104.0,
        )
        updated, reclaim = m15_reclaim(
            invalid,
            impulse,
            pullback,
            Definition("test", 1.25, 0.25, 0.60, 240),
        )
        self.assertIsNone(updated)
        self.assertIsNone(reclaim)


if __name__ == "__main__":
    unittest.main()
