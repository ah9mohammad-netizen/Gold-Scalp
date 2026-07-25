"""Calendar parsing and UTC veto-window regression tests."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.backtest_mtf_trend_pullback import event_veto_active
from scripts.research_event_veto import CORE_PATTERNS, parse_calendar


class EventCalendarTests(unittest.TestCase):
    def test_tehran_calendar_time_is_converted_to_utc(self) -> None:
        content = (
            "Time,Cur.,Event,Imp.,Actual,Forecast,Previous,\n"
            '"Thursday, August 10, 2023",,,,,,,\n'
            "16:00,US,CPI (MoM) (Jul),,0.20%,0.20%,0.20%,\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "calendar.csv"
            path.write_text(content, encoding="utf-8")
            events = parse_calendar(path, CORE_PATTERNS)
        self.assertEqual(len(events), 1)
        # Tehran is UTC+03:30 in this calendar period.
        self.assertEqual(
            events[0].timestamp,
            datetime(2023, 8, 10, 12, 30, tzinfo=timezone.utc),
        )

    def test_event_veto_includes_both_sides_of_release(self) -> None:
        event = datetime(2024, 1, 12, 13, 30, tzinfo=timezone.utc)
        self.assertTrue(event_veto_active(datetime(2024, 1, 12, 13, 0, tzinfo=timezone.utc), [event], 30, 30))
        self.assertTrue(event_veto_active(datetime(2024, 1, 12, 14, 0, tzinfo=timezone.utc), [event], 30, 30))
        self.assertFalse(event_veto_active(datetime(2024, 1, 12, 14, 5, tzinfo=timezone.utc), [event], 30, 30))


if __name__ == "__main__":
    unittest.main()
