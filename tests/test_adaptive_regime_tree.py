"""Safeguards for the adaptive regime-tree research harness."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import unittest

from scripts.research_adaptive_regime_tree import (
    Bar,
    Feature,
    candidate_bank,
    rolling_folds,
    vwap_ok,
)


class AdaptiveRegimeTreeTests(unittest.TestCase):
    def test_fractional_candidate_bank_covers_every_declared_level_per_context(self) -> None:
        candidates = candidate_bank(6)
        bull_pullbacks = [item for item in candidates if item.context == "BULL_PULLBACK"]
        self.assertEqual(len(bull_pullbacks), 6)
        self.assertEqual({item.trend_adx_min for item in bull_pullbacks}, {18.0, 22.0, 26.0})
        self.assertEqual({item.stop_atr for item in bull_pullbacks}, {1.25, 1.5, 2.0})
        self.assertEqual({item.target_rr for item in bull_pullbacks}, {1.25, 1.5, 2.0})
        self.assertEqual({item.require_vwap for item in bull_pullbacks}, {False, True})

    def test_breakout_vwap_confirmation_is_in_breakout_direction(self) -> None:
        breakout = next(item for item in candidate_bank(6) if item.context == "BULL_BREAKOUT")
        breakout = replace(breakout, require_vwap=True, vwap_distance_atr=0.5)
        bar = Bar(datetime(2024, 1, 2, 12, tzinfo=timezone.utc), 109.0, 111.0, 108.0, 110.0, 1.0, "M5_ORIGINAL")
        feature = Feature(
            bar=bar,
            atr=10.0,
            atr_ratio=None,
            adx=None,
            plus_di=None,
            minus_di=None,
            ema50=None,
            ema200=None,
            macd_hist=None,
            rsi=None,
            cci=None,
            bb_middle=None,
            bb_upper=None,
            bb_lower=None,
            bb_width_percentile=None,
            vwap=100.0,
            vwap_observations=12,
        )
        self.assertTrue(vwap_ok(feature, "LONG", breakout))

        # A range reversion uses VWAP as a destination, so the same price/value
        # relationship must not be treated as a long fade confirmation.
        reversion = next(item for item in candidate_bank(6) if item.context == "RANGE_REVERSION")
        reversion = replace(reversion, require_vwap=True, vwap_distance_atr=0.5)
        self.assertFalse(vwap_ok(feature, "LONG", reversion))

    def test_rolling_folds_never_train_on_or_after_their_test_start(self) -> None:
        last = datetime(2026, 1, 30, 22, tzinfo=timezone.utc)
        folds = rolling_folds(last)
        self.assertEqual(len(folds), 7)
        for _, train_start, train_end, test_start, test_end in folds:
            self.assertLess(train_start, train_end)
            self.assertEqual(train_end, test_start)
            self.assertLess(test_start, test_end)


if __name__ == "__main__":
    unittest.main()
