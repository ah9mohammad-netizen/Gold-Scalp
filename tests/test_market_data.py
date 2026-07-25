"""No-network tests for the feed's closed-candle safety boundary."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

from app.market_data import LiveMarketDataFeed


class MarketDataTests(unittest.TestCase):
    def test_live_candle_is_excluded_and_previous_bar_is_identified(self) -> None:
        feed = LiveMarketDataFeed()
        period_ms = feed.timeframe_seconds * 1000
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        current_open = (now_ms // period_ms) * period_ms

        # Include 250 complete synthetic OHLC rows and one currently open row.
        rows = []
        for index in range(251):
            timestamp = current_open - (250 - index) * period_ms
            close = 3000.0 + index * 0.1
            rows.append([timestamp, close - 0.2, close + 0.5, close - 0.5, close, 10.0])

        tick = feed._build_tick_result("TEST_DIRECT", "XAUUSDT", rows, 3000.0, 3000.4)
        self.assertIsNotNone(tick)
        assert tick is not None
        expected_last = max(row[0] for row in rows if row[0] + period_ms <= now_ms - 1000)
        self.assertEqual(tick["bar_timestamp_ms"], expected_last)
        self.assertEqual(tick["source"], "TEST_DIRECT")
        self.assertFalse(tick["is_proxy"])
        self.assertAlmostEqual(tick["spread"], 0.4, places=4)


if __name__ == "__main__":
    unittest.main()
