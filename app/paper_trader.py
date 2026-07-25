"""Cost-aware XAU-USDT paper execution and risk controls.

This module intentionally does **not** place live orders.  It turns a completed
candle decision into a conservative paper fill, records bid/ask spread,
slippage, and taker fees, then manages every open paper position on subsequent
completed candles.  This prevents the common backtest error of entering at a
bar close and using that same bar's earlier high/low to claim a TP or SL.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional, Set

from app.config import config
from app.database import DatabaseEngine, db
from app.engine import LayeredDecisionEngine, engine

logger = logging.getLogger("PaperTrader")


class PaperTradingEngine:
    def __init__(
        self,
        database: Optional[DatabaseEngine] = None,
        decision_engine: Optional[LayeredDecisionEngine] = None,
    ) -> None:
        self.db = database or db
        self.decision_engine = decision_engine or engine
        self.new_entries_enabled = True
        self.alert_callback: Optional[Callable[..., Any]] = None
        self.last_price = 0.0
        self.last_atr = 1.8
        self.last_spread = 0.0
        self.last_source = "NONE"
        self.last_tick_at: Optional[datetime] = None
        self._entries_blocked_until: Optional[datetime] = None
        self._entry_cooldown_seconds = float(config.ENTRY_COOLDOWN_SECONDS)
        self._loss_cooldown_seconds = float(config.LOSS_COOLDOWN_SECONDS)
        self._be_armed: Set[int] = set()
        self._last_processed_bar_ms = 0
        self._restore_state()

    def _restore_state(self) -> None:
        paused = self.db.get_state("paused", "false").lower() in ("true", "1", "yes")
        self.new_entries_enabled = not paused
        try:
            self._last_processed_bar_ms = int(self.db.get_state("last_processed_bar_ms", "0"))
        except ValueError:
            self._last_processed_bar_ms = 0

    def set_alert_callback(self, callback: Callable[..., Any]) -> None:
        self.alert_callback = callback

    def emit_alert(self, message: str) -> None:
        logger.info(message.replace("\n", " | "))
        if not self.alert_callback:
            return
        try:
            result = self.alert_callback(message)
            if asyncio.iscoroutine(result):
                try:
                    asyncio.get_running_loop().create_task(result)
                except RuntimeError:
                    asyncio.run(result)
        except Exception as exc:  # Alerts must never stop trade management.
            logger.error("Failed to emit alert: %s", exc)

    @property
    def is_running(self) -> bool:
        return self.new_entries_enabled

    @is_running.setter
    def is_running(self, value: bool) -> None:
        self.new_entries_enabled = bool(value)
        self.db.set_state("paused", "false" if value else "true")

    @staticmethod
    def _pnl_pct(pnl_usd: float, entry: float, size_oz: float, leverage: int) -> float:
        margin = (entry * size_oz) / max(int(leverage), 1)
        return round((pnl_usd / margin) * 100.0, 2) if margin > 0 else 0.0

    def _arm_entry_cooldown(self, seconds: Optional[float] = None) -> None:
        duration = self._entry_cooldown_seconds if seconds is None else seconds
        self._entries_blocked_until = datetime.now(timezone.utc) + timedelta(seconds=duration)

    def _daily_loss_breached(self, balance: float) -> bool:
        max_loss = self.db.get_initial_balance() * (config.MAX_DAILY_LOSS_PCT / 100.0)
        day_pnl = self.db.get_daily_realized_pnl()
        return day_pnl <= -max_loss or (balance <= 0 and day_pnl < 0)

    @staticmethod
    def _quote_range(
        direction: str, high: float, low: float, spread: float
    ) -> tuple[float, float]:
        """Convert a mid-price OHLC range to executable bid/ask range."""
        half_spread = max(0.0, spread) / 2.0
        if direction == "LONG":  # Closing a long sells at the bid.
            return high - half_spread, low - half_spread
        # Closing a short buys at the ask.
        return high + half_spread, low + half_spread

    def _exit_fill(
        self,
        direction: str,
        exit_reason: str,
        sl: float,
        tp: float,
        executable_high: float,
        executable_low: float,
    ) -> float:
        """Use adverse gap/slippage assumptions for a paper exit."""
        slip = config.PAPER_SLIPPAGE_USD
        if direction == "LONG":
            if exit_reason == "SL_HIT" or exit_reason == "BE_STOP":
                return round(min(sl, executable_low) - slip, 4)
            return round(tp - slip, 4)
        if exit_reason == "SL_HIT" or exit_reason == "BE_STOP":
            return round(max(sl, executable_high) + slip, 4)
        return round(tp + slip, 4)

    def _settle_trade(
        self,
        trade: Dict[str, Any],
        exit_price: float,
        exit_reason: str,
    ) -> bool:
        entry = float(trade["entry_price"])
        size = float(trade["size_oz"])
        direction = str(trade["direction"])
        leverage = int(trade["leverage"] or config.MAX_LEVERAGE)
        entry_fee = float(trade.get("entry_fee_usd") or 0.0)
        exit_fee = exit_price * size * config.PAPER_TAKER_FEE_RATE
        gross = (exit_price - entry) * size if direction == "LONG" else (entry - exit_price) * size
        net = gross - entry_fee - exit_fee
        pnl_pct = self._pnl_pct(net, entry, size, leverage)
        closed = self.db.close_trade(
            int(trade["id"]),
            exit_price,
            net,
            pnl_pct,
            exit_reason,
            gross_pnl_usd=gross,
            exit_fee_usd=exit_fee,
        )
        if not closed:
            return False
        self._be_armed.discard(int(trade["id"]))
        self._arm_entry_cooldown(self._loss_cooldown_seconds if net < 0 else None)
        self._emit_close_alert(
            int(trade["id"]),
            str(trade["symbol"]),
            direction,
            entry,
            exit_price,
            gross,
            entry_fee + exit_fee,
            net,
            pnl_pct,
            exit_reason,
        )
        return True

    def evaluate_open_trades(
        self, current_price: float, current_high: float, current_low: float, atr: float, spread: float
    ) -> None:
        """Evaluate positions once per *subsequent* closed candle.

        If both SL and TP occur in the available OHLC range, SL wins.  Without
        tick ordering, that is the conservative, non-look-ahead assumption.
        """
        for trade in self.db.get_open_trades():
            trade_id = int(trade["id"])
            direction = str(trade["direction"])
            entry = float(trade["entry_price"])
            sl = float(trade["sl_price"])
            be_level = float(trade["tp1_price"])
            tp = float(trade["tp2_price"])
            executable_high, executable_low = self._quote_range(
                direction, current_high, current_low, spread
            )

            exit_reason: Optional[str] = None
            if direction == "LONG":
                if executable_low <= sl:
                    exit_reason = "BE_STOP" if trade_id in self._be_armed and sl >= entry else "SL_HIT"
                elif executable_high >= tp:
                    exit_reason = "TP_HIT"
                elif trade_id not in self._be_armed and executable_high >= be_level:
                    self.db.update_trade_sl(trade_id, entry)
                    self._be_armed.add(trade_id)
                    self.emit_alert(
                        f"🔒 <b>BE ARMED #{trade_id}</b> LONG @ ${entry:.2f}\n"
                        f"SL → ${entry:.2f} | TP ${tp:.2f}"
                    )
                elif config.ENABLE_TRAIL and trade_id in self._be_armed:
                    trail = max(entry, current_price - max(atr * config.TRAIL_ATR_MULTIPLIER, 0.01))
                    if trail > sl:
                        self.db.update_trade_sl(trade_id, round(trail, 4))
            else:
                if executable_high >= sl:
                    exit_reason = "BE_STOP" if trade_id in self._be_armed and sl <= entry else "SL_HIT"
                elif executable_low <= tp:
                    exit_reason = "TP_HIT"
                elif trade_id not in self._be_armed and executable_low <= be_level:
                    self.db.update_trade_sl(trade_id, entry)
                    self._be_armed.add(trade_id)
                    self.emit_alert(
                        f"🔒 <b>BE ARMED #{trade_id}</b> SHORT @ ${entry:.2f}\n"
                        f"SL → ${entry:.2f} | TP ${tp:.2f}"
                    )
                elif config.ENABLE_TRAIL and trade_id in self._be_armed:
                    trail = min(entry, current_price + max(atr * config.TRAIL_ATR_MULTIPLIER, 0.01))
                    if trail < sl:
                        self.db.update_trade_sl(trade_id, round(trail, 4))

            if exit_reason:
                exit_price = self._exit_fill(
                    direction, exit_reason, sl, tp, executable_high, executable_low
                )
                self._settle_trade(trade, exit_price, exit_reason)

    def _finalize_paper_fill(self, plan: Dict[str, Any], market_data: Dict[str, Any], balance: float) -> Optional[Dict[str, Any]]:
        """Apply a taker fill to a reference-close setup before it is persisted."""
        final = dict(plan)
        direction = str(final["direction"])
        reference = float(final.get("reference_price", final["entry_price"]))
        spread = max(0.0, float(market_data.get("spread", final.get("spread", 0.0))))
        half_spread = spread / 2.0
        slippage = config.PAPER_SLIPPAGE_USD
        fill = reference + half_spread + slippage if direction == "LONG" else reference - half_spread - slippage
        if fill <= 0:
            return None
        sl_distance = float(final["sl_distance"])
        tp_distance = sl_distance * config.TP_RR_RATIO
        be_distance = sl_distance * config.BE_TRIGGER_RR
        if direction == "LONG":
            sl, tp1, tp2 = fill - sl_distance, fill + be_distance, fill + tp_distance
        else:
            sl, tp1, tp2 = fill + sl_distance, fill - be_distance, fill - tp_distance
        size = float(final["size_oz"])
        margin = fill * size / max(config.MAX_LEVERAGE, 1)
        entry_fee = fill * size * config.PAPER_TAKER_FEE_RATE
        # The margin cap must hold after the adverse entry fill, too.
        cap = balance * (config.MARGIN_CAP_PCT / 100.0)
        if margin > cap:
            size = round(cap * config.MAX_LEVERAGE / fill, 4)
            if size < 0.01:
                return None
            margin = fill * size / max(config.MAX_LEVERAGE, 1)
            entry_fee = fill * size * config.PAPER_TAKER_FEE_RATE
        if margin + entry_fee > balance:
            return None
        final.update(
            {
                "reference_price": round(reference, 4),
                "entry_price": round(fill, 4),
                "sl_price": round(sl, 4),
                "tp1_price": round(tp1, 4),
                "tp2_price": round(tp2, 4),
                "size_oz": size,
                "required_margin_usd": round(margin, 4),
                "entry_fee_usd": round(entry_fee, 6),
                "dollar_risk": round(size * sl_distance + entry_fee, 4),
                "spread": round(spread, 4),
            }
        )
        return final

    def try_open_new_trade(self, market_data: Dict[str, Any]) -> None:
        if not self.new_entries_enabled:
            return
        now = datetime.now(timezone.utc)
        force = bool(market_data.get("force_signal"))
        bar_timestamp = market_data.get("bar_timestamp_ms")
        if self._entries_blocked_until and now < self._entries_blocked_until and not force:
            return
        if len(self.db.get_open_trades()) >= config.MAX_OPEN_TRADES:
            return
        if not force and self.db.has_signal_for_bar(bar_timestamp):
            return
        if not force and self.db.count_trades_opened_today() >= config.MAX_TRADES_PER_DAY:
            logger.info("Max trades/day (%s) reached", config.MAX_TRADES_PER_DAY)
            return

        balance = self.db.get_current_balance()
        if balance < 5.0:
            logger.warning("Balance too low ($%.2f)", balance)
            return
        if not force and self._daily_loss_breached(balance):
            logger.warning("Daily loss limit reached; entries blocked")
            return

        plan = self.decision_engine.evaluate(market_data, balance)
        if not plan:
            return
        plan = self._finalize_paper_fill(plan, market_data, balance)
        if not plan:
            logger.warning("Paper fill rejected by margin/price guard")
            return
        direction = str(plan["direction"])

        plan["opened_at"] = now.isoformat()
        signal_id = self.db.save_signal(plan)
        plan["signal_id"] = signal_id
        trade_id = self.db.open_trade(plan)
        self.db.update_signal_status(signal_id, "EXECUTED")

        self.emit_alert(
            f"🚀 <b>NEW PAPER TRADE #{trade_id}</b> · <code>{config.STRATEGY_VERSION}</code>\n"
            f"Setup: <b>{plan.get('setup_name', 'SETUP')}</b> | <b>{direction}</b> {plan['symbol']}\n"
            f"Signal / fill: <b>${plan['reference_price']:.2f} → ${plan['entry_price']:.2f}</b>\n"
            f"Z: <b>{float(plan.get('zscore', 0)):+.2f}</b> | SL <b>${plan['sl_price']:.2f}</b> | "
            f"TP <b>${plan['tp2_price']:.2f}</b>\n"
            f"Size <b>{plan['size_oz']:.4f} oz</b> | Margin <b>${plan['required_margin_usd']:.2f}</b> "
            f"| Est. entry fee <b>${plan['entry_fee_usd']:.3f}</b>\n"
            f"Risk incl. entry fee: <b>${plan['dollar_risk']:.2f}</b>"
        )

    def process_new_market_data(self, market_data: Dict[str, Any]) -> bool:
        """Process a new closed bar exactly once; return whether it was consumed."""
        price = float(market_data["close"])
        high = float(market_data.get("high", price))
        low = float(market_data.get("low", price))
        atr = float(market_data.get("atr_14", self.last_atr))
        spread = max(0.0, float(market_data.get("spread", self.last_spread)))
        force = bool(market_data.get("force_signal"))
        raw_bar_timestamp = market_data.get("bar_timestamp_ms")
        try:
            bar_timestamp = int(raw_bar_timestamp) if raw_bar_timestamp else 0
        except (TypeError, ValueError):
            bar_timestamp = 0

        self.last_price, self.last_atr, self.last_spread = price, atr, spread
        self.last_source = str(market_data.get("source", self.last_source))
        self.last_tick_at = datetime.now(timezone.utc)

        if not force and bar_timestamp and bar_timestamp <= self._last_processed_bar_ms:
            return False

        # Manage first: a new decision cannot benefit from the bar that created it.
        self.evaluate_open_trades(price, high, low, atr, spread)
        self.try_open_new_trade(market_data)

        if not force and bar_timestamp:
            self._last_processed_bar_ms = bar_timestamp
            self.db.set_state("last_processed_bar_ms", str(bar_timestamp))
        return True

    def close_all_open_trades(self) -> int:
        """Telegram emergency flatten using the latest executable paper quote."""
        closed = 0
        for trade in self.db.get_open_trades():
            direction = str(trade["direction"])
            mid = self.last_price if self.last_price > 0 else float(trade["entry_price"])
            half = self.last_spread / 2.0
            exit_price = mid - half - config.PAPER_SLIPPAGE_USD if direction == "LONG" else mid + half + config.PAPER_SLIPPAGE_USD
            if self._settle_trade(trade, round(exit_price, 4), "MANUAL_CLOSE"):
                closed += 1
        if closed:
            self._arm_entry_cooldown()
            self.emit_alert(
                f"⚠️ <b>[MANUAL] Closed {closed} paper trade(s)</b>\n"
                f"💰 Balance: <b>${self.db.get_current_balance():.2f} USDT</b>"
            )
        return closed

    def _emit_close_alert(
        self,
        trade_id: int,
        symbol: str,
        direction: str,
        entry: float,
        exit_price: float,
        gross: float,
        fees: float,
        net: float,
        pnl_pct: float,
        exit_reason: str,
    ) -> None:
        labels = {
            "SL_HIT": ("🔴", "SL HIT"),
            "BE_STOP": ("🟡", "BE STOP"),
            "TP_HIT": ("🎉", "TP HIT"),
            "MANUAL_CLOSE": ("⚪", "MANUAL CLOSE"),
        }
        icon, label = labels.get(exit_reason, ("⚪", exit_reason))
        self.emit_alert(
            f"{icon} <b>[{label}] Paper Trade #{trade_id}</b>\n"
            f"{symbol} {direction}: ${entry:.2f} → ${exit_price:.2f}\n"
            f"Gross: ${gross:+.2f} | fees: −${fees:.3f}\n"
            f"Net: <b>${net:+.2f} ({pnl_pct:+.2f}%)</b>\n"
            f"💰 Realized balance: <b>${self.db.get_current_balance():.2f} USDT</b>"
        )


# Backward-compatible property used by earlier integrations.
PaperTradingEngine.last_simulated_price = property(  # type: ignore[attr-defined]
    lambda self: self.last_price,
    lambda self, value: setattr(self, "last_price", value),
)

paper_trader = PaperTradingEngine()
