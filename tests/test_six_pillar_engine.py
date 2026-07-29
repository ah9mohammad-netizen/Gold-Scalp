"""Unit tests for the 6-Pillar Institutional XAU-USDT Scalping Framework."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

from app.six_pillar_engine import SixPillarConfig, SixPillarDecisionEngine


class SixPillarEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = SixPillarConfig()
        self.engine = SixPillarDecisionEngine(self.config)

    def base_bar(self, hour: int = 8, close: float = 2850.0) -> dict:
        dt = datetime(2026, 7, 29, hour, 30, tzinfo=timezone.utc)
        return {
            "timestamp": dt,
            "bar_timestamp_ms": int(dt.timestamp() * 1000),
            "source": "TEST",
            "close": close,
            "open": close,
            "high": close + 1.5,
            "low": close - 1.5,
            "spread": 0.15,
            "atr_14": 2.2,
            "atr_avg": 2.0,
            "adx": 15.0,  # RANGING
            "rsi_14": 50.0,
            "sma_z": close,
            "stdev_z": 2.0,
            "zscore": 0.0,
            "asian_high": close + 5.0,
            "asian_low": close - 5.0,
            "pdh": close + 8.0,
            "pdl": close - 8.0,
            "is_news_window": False,
        }

    def test_pillar1_spread_gate_rejects_wide_spread(self) -> None:
        bar = self.base_bar()
        bar["spread"] = 0.40  # Above 0.25 ceiling
        bar["force_signal"] = False
        # Create sweep conditions
        bar["high"] = bar["asian_high"] + 1.0
        bar["close"] = bar["asian_high"] - 0.5
        bar["open"] = bar["close"] + 1.0
        plan = self.engine.evaluate(bar, 100.0)
        self.assertIsNone(plan)

    def test_pillar2_killzones_filter_dead_hours(self) -> None:
        # 05:00 UTC is outside Tokyo (0-4), London (7-10), NY Overlap (12-16)
        bar_dead = self.base_bar(hour=5)
        bar_dead["high"] = bar_dead["asian_high"] + 1.0
        bar_dead["close"] = bar_dead["asian_high"] - 0.5
        bar_dead["open"] = bar_dead["close"] + 1.0
        self.assertIsNone(self.engine.evaluate(bar_dead, 100.0))

        # 08:00 UTC is inside London Open Kill Zone
        bar_london = self.base_bar(hour=8)
        bar_london["high"] = bar_london["asian_high"] + 1.0
        bar_london["close"] = bar_london["asian_high"] - 0.5
        bar_london["open"] = bar_london["close"] + 1.0
        plan = self.engine.evaluate(bar_london, 100.0)
        self.assertIsNotNone(plan)
        self.assertEqual(plan["killzone_session"], "LONDON_OPEN")

    def test_pillar3_regime_gating_vetoes_news_and_atr_shocks(self) -> None:
        # High-impact news window active
        bar_news = self.base_bar(hour=14)
        bar_news["is_news_window"] = True
        bar_news["high"] = bar_news["asian_high"] + 1.0
        bar_news["close"] = bar_news["asian_high"] - 0.5
        bar_news["open"] = bar_news["close"] + 1.0
        self.assertIsNone(self.engine.evaluate(bar_news, 100.0))

        # ATR shock spike (ATR > 1.8 * average ATR)
        bar_shock = self.base_bar(hour=14)
        bar_shock["atr_14"] = 4.5
        bar_shock["atr_avg"] = 2.0
        bar_shock["high"] = bar_shock["asian_high"] + 1.0
        bar_shock["close"] = bar_shock["asian_high"] - 0.5
        bar_shock["open"] = bar_shock["close"] + 1.0
        self.assertIsNone(self.engine.evaluate(bar_shock, 100.0))

    def test_pillar4_liquidity_sweep_reclaim_short_and_long(self) -> None:
        # Asian High sweep and rejection close inside -> SHORT
        bar_short = self.base_bar(hour=8, close=2850.0)
        bar_short["asian_high"] = 2853.0
        bar_short["high"] = 2854.0        # swept by $1.00 >= $0.80 pierce
        bar_short["close"] = 2852.50      # closed back inside
        bar_short["open"] = 2853.50       # bearish bar
        plan_s = self.engine.evaluate(bar_short, 100.0)
        self.assertIsNotNone(plan_s)
        self.assertEqual(plan_s["direction"], "SHORT")
        self.assertEqual(plan_s["setup_name"], "LIQUIDITY_SWEEP_RECLAIM")
        self.assertIn("Swept level $2853.00", plan_s["layer2_structure"])

        # Asian Low sweep and rejection close inside -> LONG
        bar_long = self.base_bar(hour=2, close=2850.0)
        bar_long["asian_low"] = 2845.0
        bar_long["low"] = 2844.0          # swept by $1.00 >= $0.80 pierce
        bar_long["close"] = 2845.50       # closed back inside
        bar_long["open"] = 2844.50        # bullish bar
        plan_l = self.engine.evaluate(bar_long, 100.0)
        self.assertIsNotNone(plan_l)
        self.assertEqual(plan_l["direction"], "LONG")
        self.assertEqual(plan_l["setup_name"], "LIQUIDITY_SWEEP_RECLAIM")
        self.assertIn("Swept level $2845.00", plan_l["layer2_structure"])

    def test_pillar5_adaptive_exits(self) -> None:
        trade = {
            "direction": "LONG",
            "setup_name": "LIQUIDITY_SWEEP_RECLAIM",
            "entry_price": 2845.50,
            "max_holding_bars": 6,
        }
        # Bar 1: Z=0.8 -> no exit yet
        bar1 = {"close": 2847.0, "sma_z": 2850.0, "stdev_z": 3.75, "zscore": -0.8}
        self.assertIsNone(self.engine.check_pillar5_exits(trade, bar1, bars_held=1))

        # Bar 3: Z=-0.2 (returned to mean within |Z| <= 0.35) -> MEAN_RETURN_EXIT
        bar_mean = {"close": 2849.5, "sma_z": 2850.0, "stdev_z": 2.5, "zscore": -0.2}
        self.assertEqual(self.engine.check_pillar5_exits(trade, bar_mean, bars_held=3), "MEAN_RETURN_EXIT")

        # Bar 6: Time-based kill switch triggered at max_holding_bars=6
        bar_time = {"close": 2846.0, "sma_z": 2852.0, "stdev_z": 3.0, "zscore": -2.0}
        self.assertEqual(self.engine.check_pillar5_exits(trade, bar_time, bars_held=6), "TIME_KILL_SWITCH")

    def test_pillar6_frequency_discipline_caps_session_trades(self) -> None:
        bar = self.base_bar(hour=8, close=2850.0)
        bar["asian_high"] = 2853.0
        bar["high"] = 2854.0
        bar["close"] = 2852.50
        bar["open"] = 2853.50
        # Trade 1
        plan1 = self.engine.evaluate(bar, 100.0)
        self.assertIsNotNone(plan1)
        # Trade 2
        plan2 = self.engine.evaluate(bar, 100.0)
        self.assertIsNotNone(plan2)
        # Trade 3 -> Rejected by MAX_TRADES_PER_SESSION = 2
        plan3 = self.engine.evaluate(bar, 100.0)
        self.assertIsNone(plan3)


if __name__ == "__main__":
    unittest.main()
