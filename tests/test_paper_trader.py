"""Regression tests for closed-candle, fee-aware paper execution."""
from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone

from app.database import DatabaseEngine
from app.paper_trader import PaperTradingEngine


class PaperTraderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.database = DatabaseEngine(os.path.join(self.tempdir.name, "history.db"))
        self.trader = PaperTradingEngine(database=self.database)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    @staticmethod
    def force_tick(direction: str) -> dict:
        price = 3000.0
        return {
            "timestamp": datetime.now(timezone.utc),
            "source": "TEST",
            "close": price,
            "open": price - 0.5 if direction == "LONG" else price + 0.5,
            "high": price + 0.5,
            "low": price - 0.5,
            "spread": 0.40,
            "atr_14": 2.0,
            "atr_avg": 2.0,
            "rsi_14": 50.0,
            "adx": 10.0,
            "sma_z": price,
            "stdev_z": 2.0,
            "zscore": -2.5 if direction == "LONG" else 2.5,
            "prev_close": price - 0.2 if direction == "LONG" else price + 0.2,
            "prev_close_2": price - 0.4 if direction == "LONG" else price + 0.4,
            "force_signal": True,
            "force_direction": direction,
        }

    def test_entry_is_not_evaluated_against_its_own_signal_bar(self) -> None:
        # The force bar's high is deliberately below TP. A position must remain
        # open after entry and only be managed on the following closed bar.
        self.assertTrue(self.trader.process_new_market_data(self.force_tick("LONG")))
        opened = self.database.get_open_trades()
        self.assertEqual(len(opened), 1)
        trade = opened[0]
        self.assertGreater(float(trade["entry_price"]), 3000.0)  # ask + slippage fill
        self.assertGreater(float(trade["entry_fee_usd"]), 0.0)

        tp = float(trade["tp2_price"])
        second_bar = {
            "timestamp": datetime.now(timezone.utc),
            "source": "TEST",
            "bar_timestamp_ms": 1_900_000_000_000,
            "close": tp + 0.2,
            # Long exits at bid, so mid high needs to exceed TP + half spread.
            "high": tp + 0.5,
            "low": tp - 0.5,
            "spread": 0.40,
            "atr_14": 2.0,
            "atr_avg": 2.0,
            "rsi_14": 50.0,
            "adx": 30.0,
            "sma_z": tp,
            "stdev_z": 1.0,
            "zscore": 0.0,
            "prev_close": tp,
            "prev_close_2": tp,
        }
        self.assertTrue(self.trader.process_new_market_data(second_bar))
        self.assertEqual(self.database.get_open_trades(), [])
        closed = self.database.get_recent_trades(limit=1)[0]
        self.assertEqual(closed["exit_reason"], "TP_HIT")
        self.assertGreater(float(closed["gross_pnl_usd"]), float(closed["pnl_usd"]))
        self.assertGreater(float(closed["exit_fee_usd"]), 0.0)

        # Replaying the same bar after a restart/poll cannot create another fill.
        self.assertFalse(self.trader.process_new_market_data(second_bar))
        replay_stats = self.database.get_statistics()
        self.assertEqual(replay_stats["total_trades"], 1)
        self.assertEqual(replay_stats["market_bar_count"], 1)

    def test_export_snapshot_includes_wal_writes(self) -> None:
        signal_id = self.database.save_signal(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "bar_timestamp_ms": 123,
                "source": "TEST",
                "strategy_version": "test",
                "setup_name": "TEST",
                "reference_price": 3000.0,
                "symbol": "XAU-USDT",
                "direction": "LONG",
                "entry_price": 3000.0,
                "sl_price": 2995.0,
                "tp1_price": 3005.0,
                "tp2_price": 3010.0,
                "size_oz": 0.1,
                "leverage": 10,
                "dollar_risk": 0.5,
                "status": "NEW",
            }
        )
        self.assertGreater(signal_id, 0)
        snapshot = self.database.create_export_snapshot()
        try:
            with sqlite3.connect(snapshot) as conn:
                count = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
            self.assertEqual(count, 1)
            self.assertTrue({"market_bars", "decision_audit", "trade_marks"}.issubset(tables))
        finally:
            shutil.rmtree(os.path.dirname(snapshot), ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
