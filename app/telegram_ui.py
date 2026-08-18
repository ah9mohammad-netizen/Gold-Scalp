"""
Telegram Bot UI & Bidirectional Communication Engine.

Commands: /status /balance /get_db /signals /trades /stats
          /close_all /pause /resume /force_long /force_short /help
Push alerts on trade open / SL / TP hits.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.config import config
from app.database import db
from app.market_data import market_feed
from app.paper_trader import paper_trader

logger = logging.getLogger("TelegramUI")


class TelegramUI:
    def __init__(self) -> None:
        self.token = (config.TELEGRAM_BOT_TOKEN or "").strip()
        self.chat_id = (config.TELEGRAM_CHAT_ID or "").strip()
        self.base_url = f"https://api.telegram.org/bot{self.token}/" if self.token else ""
        self.last_update_id = 0
        self.is_polling = False

    # ------------------------------------------------------------------
    # Low-level HTTP
    # ------------------------------------------------------------------
    def _send_request(self, method: str, data: Dict[str, Any], timeout: float = 25.0) -> Optional[Dict[str, Any]]:
        if not self.token:
            return None
        try:
            url = self.base_url + method
            req_data = json.dumps(data).encode("utf-8")
            req = urllib.request.Request(
                url, data=req_data, headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            logger.debug("Telegram API %s failed: %s", method, exc)
            return None

    def _send_document_sync(
        self, chat_id: str, file_path: str, caption: str = ""
    ) -> Optional[Dict[str, Any]]:
        if not self.token or not chat_id:
            logger.info("[TELEGRAM LOG] Would send DB file: %s", file_path)
            return None
        if not os.path.exists(file_path):
            logger.error("Cannot send database file — missing: %s", file_path)
            return None

        try:
            boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
            url = self.base_url + "sendDocument"
            with open(file_path, "rb") as f:
                file_bytes = f.read()

            filename = os.path.basename(file_path) or "history.db"
            parts = []

            def add_field(name: str, value: str) -> None:
                parts.append(f"--{boundary}\r\n".encode())
                parts.append(
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
                )
                parts.append(f"{value}\r\n".encode())

            add_field("chat_id", str(chat_id))
            if caption:
                add_field("caption", caption[:1024])
                add_field("parse_mode", "HTML")

            parts.append(f"--{boundary}\r\n".encode())
            parts.append(
                (
                    f'Content-Disposition: form-data; name="document"; '
                    f'filename="{filename}"\r\n'
                ).encode()
            )
            parts.append(b"Content-Type: application/x-sqlite3\r\n\r\n")
            parts.append(file_bytes)
            parts.append(b"\r\n")
            parts.append(f"--{boundary}--\r\n".encode())
            body = b"".join(parts)

            req = urllib.request.Request(
                url,
                data=body,
                headers={
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                    "Content-Length": str(len(body)),
                },
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            logger.error("Telegram sendDocument failed: %s", exc)
            return None

    async def send_message(
        self, text: str, parse_mode: str = "HTML", chat_id: Optional[str] = None
    ) -> None:
        target = chat_id or self.chat_id
        if not self.token or not target:
            logger.info("[TELEGRAM LOG - NO TOKEN]\n%s", text)
            return

        # Telegram message hard limit ~4096 chars
        chunks = [text[i : i + 3900] for i in range(0, len(text), 3900)] or [text]
        loop = asyncio.get_running_loop()
        for chunk in chunks:
            await loop.run_in_executor(
                None,
                lambda c=chunk: self._send_request(
                    "sendMessage",
                    {
                        "chat_id": target,
                        "text": c,
                        "parse_mode": parse_mode,
                        "disable_web_page_preview": True,
                    },
                ),
            )

    async def send_document(
        self, file_path: str, caption: str = "", chat_id: Optional[str] = None
    ) -> None:
        target = chat_id or self.chat_id
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, lambda: self._send_document_sync(target, file_path, caption)
        )

    # ------------------------------------------------------------------
    # Polling loop
    # ------------------------------------------------------------------
    async def poll_updates_loop(self) -> None:
        if not self.token:
            logger.info(
                "TELEGRAM_BOT_TOKEN not set — UI commands disabled (alerts log only)."
            )
            # Keep task alive so gather doesn't exit
            while True:
                await asyncio.sleep(3600)
            return

        self.is_polling = True
        logger.info("Telegram UI long-polling started...")
        while self.is_polling:
            try:
                loop = asyncio.get_running_loop()
                updates_resp = await loop.run_in_executor(
                    None,
                    lambda: self._send_request(
                        "getUpdates",
                        {
                            "offset": self.last_update_id + 1,
                            "timeout": 20,
                            "allowed_updates": ["message"],
                        },
                        timeout=30.0,
                    ),
                )
                if updates_resp and updates_resp.get("ok"):
                    for update in updates_resp.get("result", []):
                        self.last_update_id = update["update_id"]
                        msg = update.get("message") or {}
                        text = (msg.get("text") or "").strip()
                        if not text:
                            continue
                        sender_chat = str(msg.get("chat", {}).get("id", ""))
                        # Optional chat lock: if TELEGRAM_CHAT_ID set, only that chat
                        if self.chat_id and sender_chat and sender_chat != str(self.chat_id):
                            logger.warning(
                                "Ignoring command from unauthorized chat %s", sender_chat
                            )
                            continue
                        await self.handle_command(text, sender_chat or self.chat_id)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Telegram polling error: %s", exc)
                await asyncio.sleep(5.0)

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------
    async def handle_command(self, command: str, chat_id: str) -> None:
        logger.info("Telegram command: %s from %s", command, chat_id)
        cmd_lower = command.lower().split()[0].split("@")[0]

        if cmd_lower in ("/start", "/help"):
            effective_risk = (
                min(config.RISK_PER_TRADE_PCT, config.V7_RISK_CAP_PCT)
                if config.ENABLE_ADAPTIVE_SCALPER
                else config.RISK_PER_TRADE_PCT
            )
            family = (
                "Adaptive liquidity/trend/range session router"
                if config.ENABLE_ADAPTIVE_SCALPER
                else "Legacy research strategy"
            )
            msg = (
                "🪙 <b>XAU-USDT Gold Edge Paper Research</b>\n"
                f"<code>{config.STRATEGY_VERSION}</code>\n\n"
                f"{family}\n"
                f"Risk cap {effective_risk:.2f}% · fees {config.PAPER_EXECUTION_MODE} · "
                f"max {config.MAX_TRADES_PER_DAY}/day\n"
                "Forward-paper experiment; no validated profit claim.\n\n"
                "<b>Commands</b>\n"
                "• /status — bot, price, strategy, DB\n"
                "• /balance — equity & risk\n"
                "• /get_db — download <code>history.db</code>\n"
                "• /signals · /trades · /stats\n"
                "• /close_all · /pause · /resume\n"
                "• /force_long · /force_short — test entry\n"
            )
            await self.send_message(msg, chat_id=chat_id)

        elif cmd_lower in ("/get_db", "/export_db", "/download_data", "/history"):
            st = db.get_statistics()
            if not os.path.exists(db.db_path):
                await self.send_message(
                    f"❌ Database file not found at <code>{db.db_path}</code>", chat_id=chat_id
                )
                return
            # SQLite WAL keeps recent writes in history.db-wal. Export a backup,
            # rather than uploading only the main file and losing recent records.
            try:
                snapshot = db.create_export_snapshot()
                size_kb = os.path.getsize(snapshot) / 1024.0
                caption = (
                    "📦 <b>XAU-USDT Trading History (`history.db`)</b>\n\n"
                    f"• Persistent path: <code>{db.db_path}</code>\n"
                    f"• Consistent export: <b>{size_kb:.1f} KB</b>\n"
                    f"• Closed trades: <b>{st['total_trades']}</b>\n"
                    f"• Realized balance: <b>${st['current_balance']:.2f} USDT</b>\n"
                    "Includes signals, fills, fee/slippage fields and account history."
                )
                await self.send_message(
                    "⏳ Creating and uploading a consistent <code>history.db</code> snapshot...",
                    chat_id=chat_id,
                )
                await self.send_document(snapshot, caption=caption, chat_id=chat_id)
            except Exception as exc:
                logger.exception("Database export failed")
                await self.send_message(f"❌ DB export failed: <code>{exc}</code>", chat_id=chat_id)
            finally:
                if 'snapshot' in locals():
                    # A reader can briefly create SQLite sidecar files; remove
                    # the dedicated temporary export directory as a whole.
                    shutil.rmtree(os.path.dirname(snapshot), ignore_errors=True)

        elif cmd_lower == "/status":
            open_trades = db.get_open_trades()
            snapshot = db.get_account_snapshot(market_feed.last_known_price)
            size_kb = (
                os.path.getsize(db.db_path) / 1024.0 if os.path.exists(db.db_path) else 0.0
            )
            price = market_feed.last_known_price
            price_str = f"${price:.2f} / oz" if price > 0 else "waiting for live tick…"
            tick_age = ""
            if paper_trader.last_tick_at:
                age = (datetime.now(timezone.utc) - paper_trader.last_tick_at).total_seconds()
                tick_age = f" ({int(age)}s ago)"
            lt = market_feed.last_tick or {}
            evaluation = getattr(paper_trader.decision_engine, "last_evaluation", {}) or {}
            gate_text = str(evaluation.get("reason", "n/a"))
            gate_score = evaluation.get("score", evaluation.get("best_score"))
            if gate_score is not None:
                gate_text += f" (score {gate_score})"
            effective_risk = (
                min(config.RISK_PER_TRADE_PCT, config.V7_RISK_CAP_PCT)
                if config.ENABLE_ADAPTIVE_SCALPER
                else config.RISK_PER_TRADE_PCT
            )
            msg = (
                "⚙️ <b>Gold Edge Paper Status</b>\n\n"
                f"• Strategy: <code>{config.STRATEGY_VERSION}</code>\n"
                f"• Mode: <b>{'PAPER ($100)' if config.PAPER_TRADING else 'LIVE'}</b>\n"
                f"• New entries: <b>{'🟢 ON' if paper_trader.new_entries_enabled else '🟡 PAUSED'}</b>\n"
                f"• Symbol: <b>{config.SYMBOL}</b> · Lev <b>{config.MAX_LEVERAGE}x</b>\n"
                f"• Last price: <b>{price_str}</b>{tick_age}\n"
                f"• Feed: <b>{market_feed.last_valid_source}</b> "
                f"(<code>{lt.get('source_symbol', 'n/a')}</code>)\n"
                f"• Closed bar: <code>{lt.get('bar_closed_at', 'waiting')}</code>\n"
                f"• ADX: <b>{float(lt.get('adx', 0)):.1f}</b> · "
                f"Z: <b>{float(lt.get('zscore', 0)):.2f}</b> · "
                f"ATR: <b>${float(lt.get('atr_14', 0)):.2f}</b>\n"
                f"• SMA{config.ZSCORE_PERIOD}: <b>${float(lt.get('sma_z', 0)):.2f}</b>\n"
                f"• Open: <b>{len(open_trades)}</b> · Today: "
                f"<b>{db.count_trades_opened_today()}/{config.MAX_TRADES_PER_DAY}</b>\n"
                f"• Last decision: <code>{gate_text}</code>\n"
                f"• Risk cap: <b>{effective_risk:.2f}%</b> · fee model: "
                f"<b>{config.PAPER_EXECUTION_MODE}</b>\n"
                f"• Equity: <b>${snapshot['equity']:.2f}</b> (open PnL ${snapshot['unrealized_pnl_usd']:+.2f})\n"
                f"• DB: <code>{db.db_path}</code> ({size_kb:.1f} KB)"
            )
            await self.send_message(msg, chat_id=chat_id)

        elif cmd_lower == "/balance":
            account = db.get_account_snapshot(market_feed.last_known_price)
            initial = db.get_initial_balance()
            pnl = account["balance"] - initial
            ret = (pnl / initial) * 100.0 if initial else 0.0
            day_pnl = db.get_daily_realized_pnl()
            effective_risk = (
                min(config.RISK_PER_TRADE_PCT, config.V7_RISK_CAP_PCT)
                if config.ENABLE_ADAPTIVE_SCALPER
                else config.RISK_PER_TRADE_PCT
            )
            msg = (
                "💰 <b>Paper Trading Account</b>\n\n"
                f"• Initial: <b>${initial:.2f} USDT</b>\n"
                f"• Realized balance: <b>${account['balance']:.2f} USDT</b>\n"
                f"• Open PnL (fee-aware): <b>${account['unrealized_pnl_usd']:+.2f}</b>\n"
                f"• Marked equity: <b>${account['equity']:.2f}</b>\n"
                f"• Used / free margin: <b>${account['used_margin_usd']:.2f}</b> / "
                f"<b>${account['free_margin_usd']:.2f}</b>\n"
                f"• Realized total: <b>${pnl:+.2f} ({ret:+.2f}%)</b>\n"
                f"• Today realized: <b>${day_pnl:+.2f}</b>\n"
                f"• Risk cap / trade: <b>{effective_risk:.2f}% "
                f"(~${account['equity'] * effective_risk / 100:.2f}, including estimated costs)</b>"
            )
            await self.send_message(msg, chat_id=chat_id)

        elif cmd_lower == "/signals":
            signals = db.get_recent_signals(limit=5)
            if not signals:
                await self.send_message(
                    "📡 No signals in <code>history.db</code> yet.", chat_id=chat_id
                )
                return
            lines = ["📡 <b>Recent Signals (top 5)</b>\n"]
            for s in signals:
                ts = s["timestamp"]
                dt = ts.split("T")[1][:8] if "T" in ts else ts[:19]
                z = s.get("zscore")
                z_text = f" | Z {float(z):+.2f}" if z is not None else ""
                setup = s.get("setup_name") or "LEGACY"
                score = s.get("signal_score")
                score_text = f" S{int(score)}" if score is not None else ""
                lines.append(
                    f"• [{dt}] <b>{s['direction']}</b> <code>{setup}{score_text}</code> "
                    f"@ ${float(s['entry_price']):.2f} | SL ${float(s['sl_price']):.2f} "
                    f"| TP ${float(s['tp2_price']):.2f}{z_text} | <b>{s['status']}</b>"
                )
            await self.send_message("\n".join(lines), chat_id=chat_id)

        elif cmd_lower == "/trades":
            open_t = db.get_open_trades()
            closed_t = db.get_recent_trades(limit=5)
            lines = ["📊 <b>Trades (`history.db`)</b>\n"]
            if open_t:
                lines.append("🟢 <b>OPEN</b>")
                for t in open_t:
                    lines.append(
                        f"• #{t['id']} <b>{t['direction']}</b> {t['symbol']} "
                        f"| Entry ${float(t['entry_price']):.2f} "
                        f"| {float(t['size_oz'])} oz "
                        f"| SL ${float(t['sl_price']):.2f} "
                        f"| TP1 ${float(t['tp1_price']):.2f}"
                    )
            else:
                lines.append("🟢 <i>No open trades.</i>")

            lines.append("\n🏁 <b>RECENT CLOSED</b>")
            if closed_t:
                for t in closed_t:
                    pnl = float(t.get("pnl_usd") or 0.0)
                    emoji = "✅" if pnl >= 0 else "❌"
                    setup = t.get("setup_name") or "LEGACY"
                    lines.append(
                        f"• {emoji} #{t['id']} <b>{t['direction']}</b> <code>{setup}</code> "
                        f"[{t['exit_reason']}] | Exit ${float(t['exit_price'] or 0):.2f} "
                        f"| PnL <b>${pnl:+.2f} ({float(t.get('pnl_pct') or 0):+.2f}%)</b>"
                    )
            else:
                lines.append("<i>No closed trades yet.</i>")
            await self.send_message("\n".join(lines), chat_id=chat_id)

        elif cmd_lower == "/stats":
            st = db.get_statistics()
            breakdown = st.get("exit_breakdown") or {}
            bd = (
                ", ".join(f"{k}:{v}" for k, v in breakdown.items())
                if breakdown
                else "n/a"
            )
            setup_breakdown = st.get("setup_breakdown") or {}
            setup_text = (
                " | ".join(
                    f"{name}: {values['trades']}t/{values['wins']}w/${values['pnl_usd']:+.2f}"
                    for name, values in setup_breakdown.items()
                )
                if setup_breakdown
                else "n/a"
            )
            msg = (
                "📈 <b>Performance Statistics</b>\n\n"
                f"• Trades: <b>{st['total_trades']}</b> "
                f"(W {st['wins']} / L {st['losses']})\n"
                f"• Win rate: <b>{st['win_rate']}%</b>\n"
                f"• Profit factor: <b>{st['profit_factor']}</b>\n"
                f"• Net PnL: <b>${st['total_pnl_usd']:+.2f} "
                f"({st['total_return_pct']:+.2f}%)</b>\n"
                f"• Simulated fees: <b>${st['total_fees_usd']:.2f}</b>\n"
                f"• Best / Worst: <b>${st['best_trade_usd']:+.2f}</b> / "
                f"<b>${st['worst_trade_usd']:+.2f}</b>\n"
                f"• Equity: <b>${st['current_balance']:.2f}</b> / "
                f"${st['initial_balance']:.2f} USDT\n"
                f"• Exits: <code>{bd}</code>\n"
                f"• Setups (trades/wins/PnL): <code>{setup_text}</code>\n"
                f"• DB: <code>{st['db_path']}</code>"
            )
            await self.send_message(msg, chat_id=chat_id)

        elif cmd_lower == "/close_all":
            count = paper_trader.close_all_open_trades()
            if count == 0:
                await self.send_message("ℹ️ No open trades to close.", chat_id=chat_id)

        elif cmd_lower == "/pause":
            paper_trader.is_running = False
            await self.send_message(
                "🟡 <b>Paused:</b> no new entries. Open positions still managed for SL/TP.",
                chat_id=chat_id,
            )

        elif cmd_lower == "/resume":
            paper_trader.is_running = True
            await self.send_message(
                "🟢 <b>Resumed:</b> automated paper entries active.",
                chat_id=chat_id,
            )

        elif cmd_lower in ("/force_long", "/force_short"):
            if market_feed.last_known_price <= 0:
                await self.send_message(
                    "⚠️ No live price yet — wait for first market tick.",
                    chat_id=chat_id,
                )
                return
            direction = "LONG" if cmd_lower == "/force_long" else "SHORT"
            px = market_feed.last_known_price
            base = market_feed.last_tick or {}
            dummy = {
                "timestamp": datetime.now(timezone.utc),
                "bar_timestamp_ms": base.get("bar_timestamp_ms"),
                "source": "TELEGRAM_FORCE",
                "close": px,
                "open": px - 0.5 if direction == "LONG" else px + 0.5,
                "spread": float(base.get("spread", 0.15)),
                "atr_14": float(base.get("atr_14", 2.40)),
                "atr_avg": float(base.get("atr_avg", 2.0)),
                "rsi_14": 55.0,
                "ema_200": px - 20 if direction == "LONG" else px + 20,
                "ema_50": px - 10 if direction == "LONG" else px + 10,
                "ema_21": px - 5 if direction == "LONG" else px + 5,
                "sma_z": px + 10 if direction == "LONG" else px - 10,
                "stdev_z": 3.0,
                "zscore": -2.5 if direction == "LONG" else 2.5,
                "vwap": px - 3 if direction == "LONG" else px + 3,
                "adx": 15.0,
                "plus_di": 18.0,
                "minus_di": 18.0,
                "asian_high": px + 5,
                "asian_low": px - 5,
                "asian_range_ready": True,
                "ny_orb_high": 0,
                "ny_orb_low": 0,
                "ny_orb_ready": False,
                "prev_close": px - 0.3 if direction == "LONG" else px + 0.3,
                "prev_close_2": px - 0.6 if direction == "LONG" else px + 0.6,
                "prev_high": px + 0.2,
                "prev_low": px - 0.2,
                "high": px + 0.5,
                "low": px - 0.5,
                "force_signal": True,
                "force_direction": direction,
            }
            paper_trader.process_new_market_data(dummy)
            await self.send_message(
                f"🧪 Forced <b>{direction}</b> paper plumbing test ({config.STRATEGY_VERSION}) at ${px:.2f}.",
                chat_id=chat_id,
            )

        else:
            await self.send_message(
                "Unknown command. Type /help for the list.", chat_id=chat_id
            )


telegram_ui = TelegramUI()
