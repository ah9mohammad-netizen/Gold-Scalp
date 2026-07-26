"""Safeguards for the larger-evidence adaptive regime-tree study."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import unittest

from scripts.research_adaptive_regime_tree_large_sample import (
    RESEARCH_START,
    candidate_bank,
    rolling_folds,
    trigger_mode_ok,
)


class LargeSampleRegimeTreeTests(unittest.TestCase):
    def test_bank_covers_broader_levels_and_trigger_combinations(self) -> None:
        candidates = candidate_bank(12)
        bull_pullbacks = [item for item in candidates if item.context == "BULL_PULLBACK"]
        self.assertEqual(len(bull_pullbacks), 12)
        self.assertEqual({item.trend_adx_min for item in bull_pullbacks}, {14.0, 18.0, 22.0})
        self.assertEqual({item.atr_ratio_max for item in bull_pullbacks}, {1.8, 2.2, 2.6})
        self.assertEqual(
            {item.trigger_mode for item in bull_pullbacks},
            {"RSI_MACD", "RSI_CCI", "CCI_MACD", "ALL_THREE"},
        )

    def test_trigger_modes_keep_at_least_two_indicator_confirmations(self) -> None:
        candidate = candidate_bank(12)[0]
        self.assertFalse(trigger_mode_ok(candidate, rsi=True, cci=False, macd=False))
        for mode in ("RSI_MACD", "RSI_CCI", "CCI_MACD", "ALL_THREE"):
            configured = replace(candidate, trigger_mode=mode)
            if mode == "RSI_MACD":
                self.assertTrue(trigger_mode_ok(configured, rsi=True, cci=False, macd=True))
            elif mode == "RSI_CCI":
                self.assertTrue(trigger_mode_ok(configured, rsi=True, cci=True, macd=False))
            elif mode == "CCI_MACD":
                self.assertTrue(trigger_mode_ok(configured, rsi=False, cci=True, macd=True))
            else:
                self.assertTrue(trigger_mode_ok(configured, rsi=True, cci=True, macd=True))

    def test_expanding_folds_use_all_available_prior_history(self) -> None:
        last = datetime(2026, 1, 30, 22, tzinfo=timezone.utc)
        folds = rolling_folds(last)
        self.assertEqual(len(folds), 7)
        for _, train_start, train_end, test_start, test_end in folds:
            self.assertEqual(train_start, RESEARCH_START)
            self.assertEqual(train_end, test_start)
            self.assertLess(test_start, test_end)


if __name__ == "__main__":
    unittest.main()
