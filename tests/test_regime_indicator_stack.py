"""Unit tests for the regime/indicator research harness safeguards."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

from scripts.research_regime_indicator_stack import (
    Bar,
    Position,
    SourceLocalSessionVWAP,
    STRATEGIES,
    choose_composite_signal,
    resolve_ohlc_exit,
)


class RegimeIndicatorStackTests(unittest.TestCase):
    def bar(self, close: float, source: str, minute: int = 0) -> Bar:
        timestamp = datetime(2024, 1, 2, 12, minute, tzinfo=timezone.utc)
        return Bar(timestamp, close, close, close, close, 1.0, source)

    def test_vwap_resets_at_provenance_seam_instead_of_mixing_volume_scales(self) -> None:
        vwap = SourceLocalSessionVWAP()
        value, observations = vwap.update(self.bar(100.0, "M5_ORIGINAL"))
        self.assertEqual((value, observations), (100.0, 1))
        value, observations = vwap.update(self.bar(110.0, "M5_ORIGINAL", 5))
        self.assertEqual((value, observations), (105.0, 2))

        # An M1-repair volume scale must not be weighted against original M5.
        value, observations = vwap.update(self.bar(200.0, "M1_AGGREGATED", 10))
        self.assertEqual((value, observations), (200.0, 1))

    def test_stop_has_priority_when_one_ohlc_bar_touches_stop_and_target(self) -> None:
        strategy = STRATEGIES[0]
        position = Position(
            strategy=strategy,
            opened_at=datetime(2024, 1, 2, 12, 0, tzinfo=timezone.utc),
            direction="LONG",
            reference_price=100.0,
            entry=100.0,
            stop=95.0,
            target=105.0,
            size=1.0,
            margin=2.0,
            entry_fee=0.0,
            stop_distance=5.0,
        )
        bar = Bar(
            datetime(2024, 1, 2, 12, 5, tzinfo=timezone.utc),
            100.0,
            106.0,
            94.0,
            100.0,
            1.0,
            "M5_ORIGINAL",
        )
        outcome = resolve_ohlc_exit(position, bar, spread=0.0, slippage=0.03)
        self.assertEqual(outcome, (93.97, "SL_HIT"))
        self.assertTrue(position.ambiguous_ohlc_exit)

    def test_composite_never_uses_a_hidden_tie_breaker(self) -> None:
        # A composite may take a sole family signal but skips simultaneous
        # signals so an arbitrary strategy ordering cannot improve it.
        self.assertIsNone(choose_composite_signal([object(), object()]))
        sole = object()
        self.assertIs(choose_composite_signal([sole]), sole)


if __name__ == "__main__":
    unittest.main()
