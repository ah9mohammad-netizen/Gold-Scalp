"""Regression tests for the v7 adaptive-session forward-paper rewrite."""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from app.adaptive_scalper_engine import AdaptiveScalperConfig, AdaptiveSessionScalper
from app.database import DatabaseEngine
from app.paper_trader import PaperTradingEngine


class AdaptiveSessionScalperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = AdaptiveScalperConfig()
        self.engine = AdaptiveSessionScalper(self.config)

    @staticmethod
    def base_bar(hour: int = 9, close: float = 3000.0) -> dict:
        now = datetime(2026, 8, 18, hour, 5, tzinfo=timezone.utc)
        return {
            "timestamp": now,
            "bar_timestamp_ms": int((now - timedelta(minutes=5)).timestamp() * 1000),
            "source": "TEST_DIRECT",
            "close": close,
            "open": close - 0.8,
            "high": close + 0.6,
            "low": close - 2.5,
            "spread": 0.20,
            "atr_14": 4.0,
            "atr_avg": 4.0,
            "adx": 25.0,
            "plus_di": 31.0,
            "minus_di": 17.0,
            "rsi_14": 58.0,
            "ema_21": close - 2.0,
            "ema_21_prev": close - 2.2,
            "ema_50": close - 5.0,
            "ema_200": close - 10.0,
            "sma_z": close - 1.0,
            "stdev_z": 2.0,
            "zscore": 0.5,
            "vwap": close - 2.0,
            "prev_close": close - 0.8,
            "prev_high": close - 0.3,
            "prev_low": close - 2.0,
            "asian_range_ready": True,
            "asian_high": close + 10.0,
            "asian_low": close - 10.0,
            "pdh": close + 15.0,
            "pdl": close - 15.0,
            "is_news_window": False,
        }

    def test_liquid_session_is_broader_but_not_round_the_clock(self) -> None:
        active = self.base_bar(hour=9)
        self.assertIsNotNone(self.engine.evaluate(active, 100.0))

        dead = self.base_bar(hour=3)
        self.assertIsNone(self.engine.evaluate(dead, 100.0))
        self.assertEqual(self.engine.last_evaluation["reason"], "OUTSIDE_V7_SESSION")

    def test_trend_pullback_or_momentum_is_tagged_and_scored(self) -> None:
        plan = self.engine.evaluate(self.base_bar(), 100.0)
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan["direction"], "LONG")
        self.assertIn(plan["setup_name"], ("TREND_PULLBACK_RECLAIM", "MOMENTUM_CONTINUATION"))
        self.assertGreaterEqual(plan["signal_score"], self.config.MIN_SIGNAL_SCORE)
        self.assertEqual(plan["regime"], "TRENDING")

    def test_range_stretch_uses_lower_threshold_but_requires_reclaim_score(self) -> None:
        bar = self.base_bar(close=2990.0)
        bar.update(
            {
                "open": 2989.0,
                "high": 2990.5,
                "low": 2987.0,
                "adx": 15.0,
                "plus_di": 18.0,
                "minus_di": 19.0,
                "rsi_14": 38.0,
                "ema_21": 2992.0,
                "ema_21_prev": 2992.1,
                "ema_50": 2992.2,
                "ema_200": 2992.0,
                "sma_z": 2994.0,
                "stdev_z": 2.2,
                "zscore": -1.82,
                "vwap": 2994.0,
                "prev_close": 2989.5,
                "prev_high": 2991.0,
                "prev_low": 2988.0,
            }
        )
        plan = self.engine.evaluate(bar, 100.0)
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan["setup_name"], "RANGE_STRETCH_RECLAIM")
        self.assertEqual(plan["direction"], "LONG")

    def test_stop_and_size_include_full_round_trip_cost(self) -> None:
        plan = self.engine.evaluate(self.base_bar(), 100.0)
        self.assertIsNotNone(plan)
        assert plan is not None
        cost_per_oz = float(plan["estimated_round_trip_cost_per_oz"])
        self.assertGreaterEqual(
            float(plan["sl_distance"]), cost_per_oz * self.config.MIN_STOP_COST_MULTIPLE
        )
        self.assertLessEqual(float(plan["dollar_risk"]), 0.5001)
        price_only_risk = float(plan["sl_distance"]) * float(plan["size_oz"])
        self.assertLess(price_only_risk, float(plan["dollar_risk"]))

    def test_atr_shock_is_vetoed(self) -> None:
        bar = self.base_bar()
        bar["atr_14"] = 10.0
        bar["atr_avg"] = 4.0
        self.assertIsNone(self.engine.evaluate(bar, 100.0))
        self.assertEqual(self.engine.last_evaluation["reason"], "ATR_SHOCK_VETO")

    def test_value_exit_requires_real_indicator_return_and_positive_net(self) -> None:
        trade = {
            "direction": "LONG",
            "setup_name": "RANGE_STRETCH_RECLAIM",
            "max_holding_bars": 8,
        }
        not_at_value = {
            "close": 2991.0,
            "open": 2990.0,
            "sma_z": 2994.0,
            "stdev_z": 3.75,
            "zscore": -0.8,
            "estimated_net_pnl_usd": 0.20,
        }
        self.assertIsNone(self.engine.check_adaptive_exit(trade, not_at_value, bars_held=3))

        at_value_but_fee_loss = dict(not_at_value, close=2994.0, zscore=0.1, estimated_net_pnl_usd=-0.01)
        self.assertIsNone(self.engine.check_adaptive_exit(trade, at_value_but_fee_loss, bars_held=3))

        at_value_net_win = dict(at_value_but_fee_loss, estimated_net_pnl_usd=0.08)
        self.assertEqual(
            self.engine.check_adaptive_exit(trade, at_value_net_win, bars_held=3),
            "VALUE_TARGET_EXIT",
        )

    def test_time_exit_uses_persisted_bar_count_in_paper_trader(self) -> None:
        tempdir = tempfile.TemporaryDirectory()
        try:
            database = DatabaseEngine(os.path.join(tempdir.name, "history.db"))
            local_config = AdaptiveScalperConfig(TREND_MAX_HOLDING_BARS=1)
            local_engine = AdaptiveSessionScalper(local_config)
            trader = PaperTradingEngine(database=database, decision_engine=local_engine)
            first = self.base_bar()
            self.assertTrue(trader.process_new_market_data(first))
            opened = database.get_open_trades()
            self.assertEqual(len(opened), 1)
            self.assertTrue(opened[0]["setup_name"])
            self.assertEqual(opened[0]["strategy_version"], "v7-adaptive-session-scalper")
            first_stats = database.get_statistics()
            self.assertEqual(first_stats["market_bar_count"], 1)
            self.assertEqual(first_stats["decision_status"].get("EXECUTED"), 1)

            second = dict(first)
            second["timestamp"] = first["timestamp"] + timedelta(minutes=5)
            second["bar_timestamp_ms"] = first["bar_timestamp_ms"] + 300_000
            second["open"] = first["close"]
            second["high"] = first["close"] + 0.2
            second["low"] = first["close"] - 0.2
            second["close"] = first["close"]
            second["zscore"] = 0.5
            self.assertTrue(trader.process_new_market_data(second))
            self.assertEqual(database.get_open_trades(), [])
            closed = database.get_recent_trades(limit=1)[0]
            self.assertEqual(closed["exit_reason"], "TIME_EXIT")
            final_stats = database.get_statistics()
            setup_stats = final_stats["setup_breakdown"]
            self.assertEqual(setup_stats[closed["setup_name"]]["trades"], 1)
            self.assertEqual(final_stats["market_bar_count"], 2)
            self.assertEqual(final_stats["trade_mark_count"], 1)
            self.assertGreaterEqual(int(closed["bars_held"]), 1)
            self.assertIsNotNone(closed["max_estimated_net_pnl_usd"])
            self.assertGreaterEqual(float(closed["mfe_usd_per_oz"]), 0.0)
            # Closing arms the cooldown, which must be auditable rather than
            # disappearing from a signals-only data set.
            self.assertEqual(final_stats["decision_reasons"].get("ENTRY_COOLDOWN"), 1)
        finally:
            tempdir.cleanup()


if __name__ == "__main__":
    unittest.main()
