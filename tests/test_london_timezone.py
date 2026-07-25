"""Regression tests for London local-session DST conversion."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

from scripts.backtest_london_asian_timezone import Bar, TimeConfig, in_london_window


class LondonTimezoneTests(unittest.TestCase):
    def _bar(self, year: int, month: int, day: int, hour: int, minute: int = 0) -> Bar:
        return Bar(
            timestamp=datetime(year, month, day, hour, minute, tzinfo=timezone.utc),
            open=3000.0,
            high=3001.0,
            low=2999.0,
            close=3000.0,
            volume=1.0,
        )

    def test_london_0800_local_changes_utc_start_for_dst(self) -> None:
        local_session = TimeConfig("local", 390, 480, 630)
        # January uses GMT: London 08:00 is 08:00 UTC.
        self.assertFalse(in_london_window(self._bar(2025, 1, 15, 7, 55), local_session))
        self.assertTrue(in_london_window(self._bar(2025, 1, 15, 8, 0), local_session))
        # July uses BST: London 08:00 is 07:00 UTC.
        self.assertFalse(in_london_window(self._bar(2025, 7, 15, 6, 55), local_session))
        self.assertTrue(in_london_window(self._bar(2025, 7, 15, 7, 0), local_session))

    def test_legacy_utc_window_does_not_follow_dst(self) -> None:
        legacy = TimeConfig("legacy", 390, 420, 630, fixed_utc_window=True)
        self.assertTrue(in_london_window(self._bar(2025, 1, 15, 7, 0), legacy))
        self.assertTrue(in_london_window(self._bar(2025, 7, 15, 7, 0), legacy))


if __name__ == "__main__":
    unittest.main()
