"""
Paper Trading Execution Engine for XAU-USDT ($100 Starting Capital).
Monitors open trades, executes SL/TP/Trailing hits, logs PnL to database, and emits instant alerts.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Callable, Any
from app.config import config
from app.database import db
from app.engine import engine

logger = logging.getLogger("PaperTrader")

class PaperTradingEngine:
    def __init__(self):
        self.is_running = False
        self.alert_callback: Optional[Callable[[str], None]] = None
        self.last_simulated_price = 2847.50

    def set_alert_callback(self, callback: Callable[[str], None]):
        """Sets the async/sync callback to emit messages to Telegram UI."""
        self.alert_callback = callback

    def emit_alert(self, message: str):
        logger.info(message)
        if self.alert_callback:
            if asyncio.iscoroutinefunction(self.alert_callback):
                asyncio.create_task(self.alert_callback(message))
            else:
                self.alert_callback(message)

    def evaluate_open_trades(self, current_price: float, current_high: float, current_low: float):
        """
        Check all open trades against current tick high/low to determine if SL, TP1, TP2, or Trailing Stop triggered.
        """
        open_trades = db.get_open_trades()
        if not open_trades:
            return

        for trade in open_trades:
            trade_id = trade["id"]
            direction = trade["direction"]
            entry = float(trade["entry_price"])
            sl = float(trade["sl_price"])
            tp1 = float(trade["tp1_price"])
            tp2 = float(trade["tp2_price"])
            size_oz = float(trade["size_oz"])

            # --------------------------------------------------------
            # LONG POSITION CHECKS
            # --------------------------------------------------------
            if direction == "LONG":
                # Check Stop Loss Hit
                if current_low <= sl:
                    exit_price = sl
                    pnl_usd = round((exit_price - entry) * size_oz, 2)
                    pnl_pct = round((pnl_usd / (entry * size_oz / trade["leverage"])) * 100.0, 2)
                    db.close_trade(trade_id, exit_price, pnl_usd, pnl_pct, "SL_HIT")
                    new_bal = db.get_current_balance()
                    self.emit_alert(
                        f"🔴 <b>[SL HIT] Trade #{trade_id} Closed</b>\n"
                        f"Pair: {trade['symbol']} (LONG)\n"
                        f"Entry: ${entry:.2f} ➡️ Exit: ${exit_price:.2f}\n"
                        f"PnL: <b>${pnl_usd:.2f} ({pnl_pct:+.2f}%)</b>\n"
                        f"💰 Updated Balance: <b>${new_bal:.2f} USDT</b>"
                    )
                    continue

                # Check Take Profit 2 Hit
                elif current_high >= tp2:
                    exit_price = tp2
                    pnl_usd = round((exit_price - entry) * size_oz, 2)
                    pnl_pct = round((pnl_usd / (entry * size_oz / trade["leverage"])) * 100.0, 2)
                    db.close_trade(trade_id, exit_price, pnl_usd, pnl_pct, "TP2_HIT")
                    new_bal = db.get_current_balance()
                    self.emit_alert(
                        f"🎉 <b>[TP2 HIT] Trade #{trade_id} Closed at Full Target!</b>\n"
                        f"Pair: {trade['symbol']} (LONG)\n"
                        f"Entry: ${entry:.2f} ➡️ Exit: ${exit_price:.2f}\n"
                        f"PnL: <b>+${pnl_usd:.2f} ({pnl_pct:+.2f}%)</b>\n"
                        f"💰 Updated Balance: <b>${new_bal:.2f} USDT</b>"
                    )
                    continue

                # Check Take Profit 1 Hit
                elif current_high >= tp1 and trade["status"] == "OPEN":
                    exit_price = tp1
                    pnl_usd = round((exit_price - entry) * size_oz, 2)
                    pnl_pct = round((pnl_usd / (entry * size_oz / trade["leverage"])) * 100.0, 2)
                    db.close_trade(trade_id, exit_price, pnl_usd, pnl_pct, "TP1_HIT")
                    new_bal = db.get_current_balance()
                    self.emit_alert(
                        f"🎯 <b>[TP1 HIT] Trade #{trade_id} Closed at Target 1!</b>\n"
                        f"Pair: {trade['symbol']} (LONG)\n"
                        f"Entry: ${entry:.2f} ➡️ Exit: ${exit_price:.2f}\n"
                        f"PnL: <b>+${pnl_usd:.2f} ({pnl_pct:+.2f}%)</b>\n"
                        f"💰 Updated Balance: <b>${new_bal:.2f} USDT</b>"
                    )
                    continue

            # --------------------------------------------------------
            # SHORT POSITION CHECKS
            # --------------------------------------------------------
            elif direction == "SHORT":
                # Check Stop Loss Hit
                if current_high >= sl:
                    exit_price = sl
                    pnl_usd = round((entry - exit_price) * size_oz, 2)
                    pnl_pct = round((pnl_usd / (entry * size_oz / trade["leverage"])) * 100.0, 2)
                    db.close_trade(trade_id, exit_price, pnl_usd, pnl_pct, "SL_HIT")
                    new_bal = db.get_current_balance()
                    self.emit_alert(
                        f"🔴 <b>[SL HIT] Trade #{trade_id} Closed</b>\n"
                        f"Pair: {trade['symbol']} (SHORT)\n"
                        f"Entry: ${entry:.2f} ➡️ Exit: ${exit_price:.2f}\n"
                        f"PnL: <b>${pnl_usd:.2f} ({pnl_pct:+.2f}%)</b>\n"
                        f"💰 Updated Balance: <b>${new_bal:.2f} USDT</b>"
                    )
                    continue

                # Check Take Profit 2 Hit
                elif current_low <= tp2:
                    exit_price = tp2
                    pnl_usd = round((entry - exit_price) * size_oz, 2)
                    pnl_pct = round((pnl_usd / (entry * size_oz / trade["leverage"])) * 100.0, 2)
                    db.close_trade(trade_id, exit_price, pnl_usd, pnl_pct, "TP2_HIT")
                    new_bal = db.get_current_balance()
                    self.emit_alert(
                        f"🎉 <b>[TP2 HIT] Trade #{trade_id} Closed at Full Target!</b>\n"
                        f"Pair: {trade['symbol']} (SHORT)\n"
                        f"Entry: ${entry:.2f} ➡️ Exit: ${exit_price:.2f}\n"
                        f"PnL: <b>+${pnl_usd:.2f} ({pnl_pct:+.2f}%)</b>\n"
                        f"💰 Updated Balance: <b>${new_bal:.2f} USDT</b>"
                    )
                    continue

                # Check Take Profit 1 Hit
                elif current_low <= tp1 and trade["status"] == "OPEN":
                    exit_price = tp1
                    pnl_usd = round((entry - exit_price) * size_oz, 2)
                    pnl_pct = round((pnl_usd / (entry * size_oz / trade["leverage"])) * 100.0, 2)
                    db.close_trade(trade_id, exit_price, pnl_usd, pnl_pct, "TP1_HIT")
                    new_bal = db.get_current_balance()
                    self.emit_alert(
                        f"🎯 <b>[TP1 HIT] Trade #{trade_id} Closed at Target 1!</b>\n"
                        f"Pair: {trade['symbol']} (SHORT)\n"
                        f"Entry: ${entry:.2f} ➡️ Exit: ${exit_price:.2f}\n"
                        f"PnL: <b>+${pnl_usd:.2f} ({pnl_pct:+.2f}%)</b>\n"
                        f"💰 Updated Balance: <b>${new_bal:.2f} USDT</b>"
                    )
                    continue

    def process_new_market_data(self, market_data: Dict[str, Any]):
        """Main processing tick for paper trading."""
        price = market_data["close"]
        high = market_data["high"]
        low = market_data["low"]
        self.last_simulated_price = price

        # 1. First, check open trades against current price action
        self.evaluate_open_trades(price, high, low)

        # 2. Check if we already have an open trade (one trade at a time policy)
        open_trades = db.get_open_trades()
        if len(open_trades) > 0:
            return

        # 3. Evaluate new structural setups via decision engine
        current_bal = db.get_current_balance()
        trade_plan = engine.evaluate(market_data, current_bal)
        if trade_plan:
            # Save signal to database
            signal_id = db.save_signal(trade_plan)
            trade_plan["signal_id"] = signal_id
            trade_plan["opened_at"] = datetime.now(timezone.utc).isoformat()
            
            # Execute paper trade
            trade_id = db.open_trade(trade_plan)
            db.update_signal_status(signal_id, "EXECUTED")
            
            self.emit_alert(
                f"🚀 <b>NEW PAPER TRADE OPENED #{trade_id}</b>\n"
                f"Pair: <b>{trade_plan['symbol']}</b> | Direction: <b>{trade_plan['direction']}</b>\n"
                f"Entry: <b>${trade_plan['entry_price']:.2f}</b>\n"
                f"Stop Loss: <b>${trade_plan['sl_price']:.2f}</b> (-${trade_plan['sl_distance']:.2f})\n"
                f"Take Profit 1: <b>${trade_plan['tp1_price']:.2f}</b> (2.0x R:R)\n"
                f"Take Profit 2: <b>${trade_plan['tp2_price']:.2f}</b> (3.5x R:R)\n"
                f"Sizing: <b>{trade_plan['size_oz']} oz</b> | Margin: <b>${trade_plan['required_margin_usd']:.2f}</b> ({trade_plan['leverage']}x)\n"
                f"Risked Equity: <b>${trade_plan['dollar_risk']:.2f}</b>\n"
                f"💡 Reason: {trade_plan['layer2_structure']}"
            )

    def close_all_open_trades(self) -> int:
        """Manually close all active open paper trades at market price."""
        open_trades = db.get_open_trades()
        closed_count = 0
        for trade in open_trades:
            entry = float(trade["entry_price"])
            size_oz = float(trade["size_oz"])
            direction = trade["direction"]
            exit_price = self.last_simulated_price
            
            if direction == "LONG":
                pnl_usd = round((exit_price - entry) * size_oz, 2)
            else:
                pnl_usd = round((entry - exit_price) * size_oz, 2)
                
            pnl_pct = round((pnl_usd / (entry * size_oz / trade["leverage"])) * 100.0, 2)
            db.close_trade(trade["id"], exit_price, pnl_usd, pnl_pct, "MANUAL_CLOSE")
            closed_count += 1
            
        if closed_count > 0:
            new_bal = db.get_current_balance()
            self.emit_alert(f"⚠️ <b>[MANUAL OVERRIDE] Closed {closed_count} Open Trade(s)</b>\n💰 Updated Balance: <b>${new_bal:.2f} USDT</b>")
        return closed_count

paper_trader = PaperTradingEngine()
