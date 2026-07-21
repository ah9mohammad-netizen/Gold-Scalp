"""
Telegram Bot UI & Bidirectional Communication Engine.
Provides interactive commands (/status, /balance, /signals, /trades, /stats, /close_all) and live push alerts.
"""
import asyncio
import json
import logging
import urllib.request
import urllib.parse
from typing import Optional, Dict, Any, List
from app.config import config
from app.database import db
from app.paper_trader import paper_trader

logger = logging.getLogger("TelegramUI")

class TelegramUI:
    def __init__(self):
        self.token = config.TELEGRAM_BOT_TOKEN
        self.chat_id = config.TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.token}/" if self.token else ""
        self.last_update_id = 0
        self.is_polling = False

    def _send_request(self, method: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Synchronous HTTP post request to Telegram Bot API."""
        if not self.token or not self.chat_id:
            return None
        try:
            url = self.base_url + method
            req_data = json.dumps(data).encode("utf-8")
            req = urllib.request.Request(url, data=req_data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                res_body = json.loads(resp.read().decode("utf-8"))
                return res_body
        except Exception as e:
            logger.debug(f"Telegram API request failed ({method}): {e}")
            return None

    async def send_message(self, text: str, parse_mode: str = "HTML", chat_id: Optional[str] = None):
        """Sends an async push notification/alert to the user via Telegram."""
        target_chat = chat_id or self.chat_id
        if not self.token or not target_chat:
            logger.info(f"[TELEGRAM LOG ONLY - NO TOKEN SET]\n{text}")
            return
        
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: self._send_request("sendMessage", {
                "chat_id": target_chat,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True
            })
        )

    async def poll_updates_loop(self):
        """Long polling loop to process user commands from Telegram 24/7 on Railway."""
        if not self.token:
            logger.info("Telegram Bot Token not configured. UI commands will operate via logs or local tests.")
            return

        self.is_polling = True
        logger.info("Telegram UI long-polling loop started...")
        while self.is_polling:
            try:
                loop = asyncio.get_running_loop()
                updates_resp = await loop.run_in_executor(
                    None,
                    lambda: self._send_request("getUpdates", {
                        "offset": self.last_update_id + 1,
                        "timeout": 20
                    })
                )
                if updates_resp and updates_resp.get("ok"):
                    for update in updates_resp.get("result", []):
                        self.last_update_id = update["update_id"]
                        if "message" in update and "text" in update["message"]:
                            msg_text = update["message"]["text"].strip()
                            sender_chat = str(update["message"]["chat"]["id"])
                            await self.handle_command(msg_text, sender_chat)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in Telegram polling loop: {e}")
                await asyncio.sleep(5.0)

    async def handle_command(self, command: str, chat_id: str):
        """Dispatches incoming Telegram bot commands."""
        logger.info(f"Received Telegram command: {command} from {chat_id}")
        cmd_lower = command.lower().split()[0]

        if cmd_lower in ("/start", "/help"):
            msg = (
                "🪙 <b>XAU-USDT Quantitative Paper Trading Bot UI</b>\n\n"
                "Available Commands:\n"
                "• /status - Check 24/7 bot status, spread & current price\n"
                "• /balance - View current paper trading balance ($100 starting)\n"
                "• /signals - List last 5 signals from the database\n"
                "• /trades - View active open trades and closed history\n"
                "• /stats - Comprehensive performance statistics & win rate\n"
                "• /close_all - Immediately close all active open paper trades\n"
                "• /pause - Pause opening new automated paper trades\n"
                "• /resume - Resume automated paper trading loop\n"
                "• /force_long - Trigger a manual simulated LONG entry test\n"
                "• /force_short - Trigger a manual simulated SHORT entry test\n"
            )
            await self.send_message(msg, chat_id=chat_id)

        elif cmd_lower == "/status":
            open_trades = db.get_open_trades()
            msg = (
                "⚙️ <b>XAU-USDT Scalping Bot Status</b>\n\n"
                f"• Execution Mode: <b>{'PAPER TRADING ($100 Capital)' if config.PAPER_TRADING else 'LIVE TRADING'}</b>\n"
                f"• Bot Status: <b>{'🟢 RUNNING 24/7' if paper_trader.is_running else '🟡 PAUSED'}</b>\n"
                f"• Target Symbol: <b>{config.SYMBOL} ({config.EXCHANGE_ID.upper()})</b>\n"
                f"• Last Market Price: <b>${paper_trader.last_simulated_price:.2f} / oz</b>\n"
                f"• Max Leverage: <b>{config.MAX_LEVERAGE}x</b>\n"
                f"• Open Active Trades: <b>{len(open_trades)}</b>\n"
                f"• Database Engine: <b>Connected & Ready</b>"
            )
            await self.send_message(msg, chat_id=chat_id)

        elif cmd_lower == "/balance":
            bal = db.get_current_balance()
            pnl_tot = bal - config.INITIAL_BALANCE_USDT
            ret_pct = (pnl_tot / config.INITIAL_BALANCE_USDT) * 100.0
            msg = (
                "💰 <b>Paper Trading Account Balance</b>\n\n"
                f"• Initial Balance: <b>${config.INITIAL_BALANCE_USDT:.2f} USDT</b>\n"
                f"• Current Balance: <b>${bal:.2f} USDT</b>\n"
                f"• Total PnL: <b>${pnl_tot:+.2f} ({ret_pct:+.2f}%)</b>\n"
                f"• Risk Per Trade: <b>{config.RISK_PER_TRADE_PCT}% (~${(bal * config.RISK_PER_TRADE_PCT / 100):.2f})</b>"
            )
            await self.send_message(msg, chat_id=chat_id)

        elif cmd_lower == "/signals":
            signals = db.get_recent_signals(limit=5)
            if not signals:
                await self.send_message("📡 No trading signals recorded in database yet.", chat_id=chat_id)
                return
            msg_lines = ["📡 <b>Recent Database Signals (Top 5)</b>\n"]
            for s in signals:
                dt_str = s["timestamp"].split("T")[1][:8] if "T" in s["timestamp"] else s["timestamp"][:19]
                msg_lines.append(
                    f"• [{dt_str}] <b>{s['direction']}</b> @ ${float(s['entry_price']):.2f} "
                    f"| SL: ${float(s['sl_price']):.2f} | TP1: ${float(s['tp1_price']):.2f} "
                    f"| Status: <b>{s['status']}</b>"
                )
            await self.send_message("\n".join(msg_lines), chat_id=chat_id)

        elif cmd_lower == "/trades":
            open_t = db.get_open_trades()
            closed_t = db.get_recent_trades(limit=5)
            msg_lines = ["📊 <b>Trades Management Panel</b>\n"]
            if open_t:
                msg_lines.append("🟢 <b>ACTIVE OPEN TRADES:</b>")
                for t in open_t:
                    msg_lines.append(
                        f"• #{t['id']} <b>{t['direction']}</b> {t['symbol']} | Entry: ${float(t['entry_price']):.2f} "
                        f"| Size: {float(t['size_oz'])} oz | SL: ${float(t['sl_price']):.2f} | TP1: ${float(t['tp1_price']):.2f}"
                    )
            else:
                msg_lines.append("🟢 <i>No active open trades right now.</i>")
                
            msg_lines.append("\n🏁 <b>RECENT CLOSED TRADES:</b>")
            if closed_t:
                for t in closed_t:
                    pnl = float(t.get("pnl_usd", 0.0))
                    emoji = "✅" if pnl >= 0 else "❌"
                    msg_lines.append(
                        f"• {emoji} #{t['id']} <b>{t['direction']}</b> [{t['exit_reason']}] | "
                        f"Exit: ${float(t['exit_price']):.2f} | PnL: <b>${pnl:+.2f} ({float(t.get('pnl_pct',0)):+.2f}%)</b>"
                    )
            else:
                msg_lines.append("<i>No closed trades in history yet.</i>")
                
            await self.send_message("\n".join(msg_lines), chat_id=chat_id)

        elif cmd_lower == "/stats":
            st = db.get_statistics()
            msg = (
                "📈 <b>Comprehensive Performance Statistics</b>\n\n"
                f"• Total Trades: <b>{st['total_trades']}</b>\n"
                f"• Wins: <b>{st['wins']}</b> | Losses: <b>{st['losses']}</b>\n"
                f"• Win Rate: <b>{st['win_rate']}%</b>\n"
                f"• Total PnL: <b>${st['total_pnl_usd']:+.2f} USDT ({st['total_return_pct']:+.2f}%)</b>\n"
                f"• Best Trade: <b>${st['best_trade_usd']:+.2f}</b>\n"
                f"• Worst Trade: <b>${st['worst_trade_usd']:+.2f}</b>\n"
                f"• Account Balance: <b>${st['current_balance']:.2f} / ${st['initial_balance']:.2f} USDT</b>"
            )
            await self.send_message(msg, chat_id=chat_id)

        elif cmd_lower == "/close_all":
            count = paper_trader.close_all_open_trades()
            if count == 0:
                await self.send_message("ℹ️ No active open trades to close.", chat_id=chat_id)

        elif cmd_lower == "/pause":
            paper_trader.is_running = False
            await self.send_message("🟡 <b>Bot Paused:</b> Automated paper trade execution suspended. Open positions will still be monitored.", chat_id=chat_id)

        elif cmd_lower == "/resume":
            paper_trader.is_running = True
            await self.send_message("🟢 <b>Bot Resumed:</b> Automated paper trade execution is now active 24/7.", chat_id=chat_id)

        elif cmd_lower in ("/force_long", "/force_short"):
            direction = "LONG" if cmd_lower == "/force_long" else "SHORT"
            from datetime import datetime, timezone
            dummy_market = {
                "timestamp": datetime.now(timezone.utc),
                "close": paper_trader.last_simulated_price,
                "spread": 0.15,
                "atr_14": 2.40,
                "rsi_14": 64.0 if direction == "LONG" else 36.0,
                "ema_200": paper_trader.last_simulated_price - 10 if direction == "LONG" else paper_trader.last_simulated_price + 10,
                "vwap": paper_trader.last_simulated_price - 3 if direction == "LONG" else paper_trader.last_simulated_price + 3,
                "asian_high": paper_trader.last_simulated_price - 2,
                "asian_low": paper_trader.last_simulated_price - 12,
                "high": paper_trader.last_simulated_price + 0.5,
                "low": paper_trader.last_simulated_price - 0.5,
                "force_signal": True,
                "force_direction": direction
            }
            paper_trader.process_new_market_data(dummy_market)
            await self.send_message(f"🧪 Forced test market tick for <b>{direction}</b> dispatched to engine.", chat_id=chat_id)

telegram_ui = TelegramUI()
