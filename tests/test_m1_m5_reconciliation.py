"""Timezone and exact M1→M5 aggregation checks for source reconciliation."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.reconcile_xau_m1_repairs import Candle, load_m1_aggregate, m5_source_time_to_utc


class M1M5ReconciliationTests(unittest.TestCase):
    def test_m5_server_labels_follow_helsinki_dst(self) -> None:
        zone = ZoneInfo("Europe/Helsinki")
        # EEST: UTC+3 in July.
        self.assertEqual(m5_source_time_to_utc("2025.07.15 12:00", zone), datetime(2025, 7, 15, 9, 0))
        # EET: UTC+2 in January.
        self.assertEqual(m5_source_time_to_utc("2025.01.15 12:00", zone), datetime(2025, 1, 15, 10, 0))

    def test_only_complete_native_minutes_create_m5_bar(self) -> None:
        content = (
            "Date,Timestamp,Open,High,Low,Close,Volume\n"
            "20250115,10:00:00,3000,3001,2999,3000.5,1\n"
            "20250115,10:01:00,3000.5,3002,3000,3001.5,2\n"
            "20250115,10:02:00,3001.5,3003,3001,3002.5,3\n"
            "20250115,10:03:00,3002.5,3004,3002,3003.5,4\n"
            "20250115,10:04:00,3003.5,3005,3003,3004.5,5\n"
            "20250115,10:06:00,3004.5,3006,3004,3005.5,6\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "m1.csv"
            path.write_text(content)
            bars = load_m1_aggregate([path], ZoneInfo("UTC"))
        first = datetime(2025, 1, 15, 10, 0)
        self.assertEqual(list(bars), [first])
        candle = bars[first]
        self.assertEqual((candle.open, candle.high, candle.low, candle.close, candle.volume), (3000.0, 3005.0, 2999.0, 3004.5, 15.0))


if __name__ == "__main__":
    unittest.main()
