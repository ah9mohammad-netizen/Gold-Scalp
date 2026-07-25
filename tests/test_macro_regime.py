"""Daily macro data must be lagged before intraday XAU decisions."""
from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from scripts.research_daily_macro_regime import MacroHistory, MacroRow, MacroPolicy, make_gate


class MacroRegimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.history = MacroHistory(
            [
                MacroRow(date(2024, 1, 2), 100.0, 18.0, 0.01, 0.01, 0.02),
                MacroRow(date(2024, 1, 3), 101.0, 18.0, 0.01, 0.01, 0.02),
                MacroRow(date(2024, 1, 4), 102.0, 18.0, 0.01, 0.01, 0.02),
                MacroRow(date(2024, 1, 5), 103.0, 18.0, 0.01, 0.01, 0.02),
                MacroRow(date(2024, 1, 8), 104.0, 18.0, 0.01, 0.01, 0.02),
                MacroRow(date(2024, 1, 9), 105.0, 18.0, 0.01, 0.01, 0.02),
            ]
        )

    def test_same_day_macro_close_is_not_available(self) -> None:
        point = datetime(2024, 1, 9, 16, 0, tzinfo=timezone.utc)
        row, dxy_5d = self.history.prior(point) or (None, None)
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row.date, date(2024, 1, 8))
        self.assertIsNone(dxy_5d)  # Only five prior rows exist at this point.

    def test_dxy_direction_gate_is_symmetric(self) -> None:
        point = datetime(2024, 1, 10, 10, 0, tzinfo=timezone.utc)
        gate = make_gate(self.history, MacroPolicy("dxy", require_dxy_direction=True))
        # DXY rose from Jan 2 to Jan 9, so permit short XAU continuation only.
        self.assertFalse(gate(point, "LONG"))
        self.assertTrue(gate(point, "SHORT"))


if __name__ == "__main__":
    unittest.main()
