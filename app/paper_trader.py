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
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional, Set

from app.config import config
from app.database import DatabaseEngine, db

logger = logging.getLogger("PaperTrader")


class PaperTradingEngine:
    def __init__(
        self,
        database: Optional[DatabaseEngine] = None,
        decision_engine: Optional[Any] = None,
    ) -> None:
        self.db = database or db
        if decision_engine is not None:
            self.decision_engine = decision_engine
        else:
            if not config.ENABLE_ADAPTIVE_SCALPER:
                raise RuntimeError(
                    "Only STRATEGY_VERSION=v7-adaptive-session-scalper is supported"
                )
            from app.adaptive_scalper_engine import adaptive_scalper_engine

            self.decision_engine = adaptive_scalper_engine
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
        loss_pct = min(config.MAX_DAILY_LOSS_PCT, 2.0) if config.ENABLE_ADAPTIVE_SCALPER else config.MAX_DAILY_LOSS_PCT
        max_loss = self.db.get_initial_balance() * (loss_pct / 100.0)
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

    @staticmethod
    def _get_fee_rate(record: Optional[Dict[str, Any]] = None) -> float:
        """Keep a trade on the fee model used when it was opened."""
        if record:
            stored = float(record.get("fee_rate") or 0.0)
            if stored > 0:
                return stored
        return config.paper_fee_rate

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
        exit_fee = exit_price * size * self._get_fee_rate(trade)
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

    @staticmethod
    def _market_exit_fill(direction: str, mid_price: float, spread: float) -> float:
        """Executable close for indicator/time/manual-style market exits."""
        half_spread = max(0.0, spread) / 2.0
        slip = config.PAPER_SLIPPAGE_USD
        if direction == "LONG":
            return round(mid_price - half_spread - slip, 4)
        return round(mid_price + half_spread + slip, 4)

    def _estimated_net_at_exit(self, trade: Dict[str, Any], exit_price: float) -> float:
        entry = float(trade["entry_price"])
        size = float(trade["size_oz"])
        direction = str(trade["direction"])
        gross = (exit_price - entry) * size if direction == "LONG" else (entry - exit_price) * size
        entry_fee = float(trade.get("entry_fee_usd") or 0.0)
        exit_fee = exit_price * size * self._get_fee_rate(trade)
        return gross - entry_fee - exit_fee

    @staticmethod
    def _bars_held(trade: Dict[str, Any], current_bar: Dict[str, Any]) -> int:
        try:
            opened_bar = int(trade.get("candle_timestamp_ms") or 0)
            current_bar_ms = int(current_bar.get("bar_timestamp_ms") or 0)
        except (TypeError, ValueError):
            opened_bar = current_bar_ms = 0
        raw = config.TIMEFRAME.strip().lower()
        period_seconds = int(raw[:-1]) * (60 if raw.endswith("m") else 3600) if raw[:-1].isdigit() else 300
        period_ms = max(60_000, period_seconds * 1000)
        if opened_bar > 0 and current_bar_ms >= opened_bar:
            return max(0, int((current_bar_ms - opened_bar) // period_ms))
        return 0

    def _cost_lock_stop(self, trade: Dict[str, Any]) -> float:
        """Replace nominal breakeven with a stop intended to cover both fees."""
        entry = float(trade["entry_price"])
        size = float(trade["size_oz"])
        direction = str(trade["direction"])
        entry_fee_per_oz = float(trade.get("entry_fee_usd") or 0.0) / max(size, 1e-9)
        exit_fee_per_oz = entry * self._get_fee_rate(trade)
        # _exit_fill applies another adverse slippage increment after the stop
        # is touched, so the trigger price must include it.
        lock_distance = entry_fee_per_oz + exit_fee_per_oz + config.PAPER_SLIPPAGE_USD + 0.01
        return round(entry + lock_distance if direction == "LONG" else entry - lock_distance, 4)

    def evaluate_open_trades(self, market_data: Dict[str, Any]) -> None:
        """Evaluate positions once per subsequent completed candle.

        Stop has priority over target when both occur in one OHLC candle.  All
        adaptive exits receive the actual indicator snapshot and an executable,
        fee-aware net-PnL estimate; the old synthetic ``zscore=0`` shortcut is
        intentionally removed.
        """
        current_price = float(market_data["close"])
        current_high = float(market_data.get("high", current_price))
        current_low = float(market_data.get("low", current_price))
        spread = max(0.0, float(market_data.get("spread", self.last_spread)))

        for trade in self.db.get_open_trades():
            trade_id = int(trade["id"])
            direction = str(trade["direction"])
            entry = float(trade["entry_price"])
            sl = float(trade["sl_price"])
            initial_sl = float(trade.get("initial_sl_price") or sl)
            be_level = float(trade["tp1_price"])
            tp = float(trade["tp2_price"])
            armed = trade_id in self._be_armed or (
                (direction == "LONG" and sl > initial_sl + 1e-6)
                or (direction == "SHORT" and sl < initial_sl - 1e-6)
            )
            if armed:
                self._be_armed.add(trade_id)
            executable_high, executable_low = self._quote_range(
                direction, current_high, current_low, spread
            )
            market_exit = self._market_exit_fill(direction, current_price, spread)
            estimated_net = self._estimated_net_at_exit(trade, market_exit)
            bars_held = self._bars_held(trade, market_data)
            self.db.record_trade_mark(
                trade,
                market_data,
                executable_close=market_exit,
                estimated_net_pnl_usd=estimated_net,
                bars_held=bars_held,
                executable_high=executable_high,
                executable_low=executable_low,
            )

            exit_reason: Optional[str] = None
            if direction == "LONG":
                if executable_low <= sl:
                    exit_reason = "BE_STOP" if armed and sl >= entry else "SL_HIT"
                elif executable_high >= tp:
                    exit_reason = "TP_HIT"
                elif not armed and executable_high >= be_level:
                    locked_sl = self._cost_lock_stop(trade)
                    self.db.update_trade_sl(trade_id, locked_sl)
                    self._be_armed.add(trade_id)
                    self.emit_alert(
                        f"🔒 <b>COST LOCK #{trade_id}</b> LONG @ ${entry:.2f}\n"
                        f"SL → ${locked_sl:.2f} | TP ${tp:.2f}"
                    )
            else:
                if executable_high >= sl:
                    exit_reason = "BE_STOP" if armed and sl <= entry else "SL_HIT"
                elif executable_low <= tp:
                    exit_reason = "TP_HIT"
                elif not armed and executable_low <= be_level:
                    locked_sl = self._cost_lock_stop(trade)
                    self.db.update_trade_sl(trade_id, locked_sl)
                    self._be_armed.add(trade_id)
                    self.emit_alert(
                        f"🔒 <b>COST LOCK #{trade_id}</b> SHORT @ ${entry:.2f}\n"
                        f"SL → ${locked_sl:.2f} | TP ${tp:.2f}"
                    )

            if exit_reason:
                exit_price = self._exit_fill(
                    direction, exit_reason, sl, tp, executable_high, executable_low
                )
                self._settle_trade(trade, exit_price, exit_reason)
                continue

            exit_bar = dict(market_data)
            exit_bar["estimated_net_pnl_usd"] = estimated_net
            adaptive_reason: Optional[str] = None
            if hasattr(self.decision_engine, "check_adaptive_exit"):
                adaptive_reason = self.decision_engine.check_adaptive_exit(
                    trade, exit_bar, bars_held
                )
            if adaptive_reason:
                self._settle_trade(trade, market_exit, adaptive_reason)

    def _finalize_paper_fill(
        self, plan: Dict[str, Any], market_data: Dict[str, Any], balance: float
    ) -> Optional[Dict[str, Any]]:
        """Apply the configured adverse paper fill and re-check cost/risk caps."""
        final = dict(plan)
        final.setdefault("rsi_at_entry", market_data.get("rsi_14"))
        direction = str(final["direction"])
        reference = float(final.get("reference_price", final["entry_price"]))
        spread = max(0.0, float(market_data.get("spread", final.get("spread", 0.0))))
        half_spread = spread / 2.0
        slippage = config.PAPER_SLIPPAGE_USD
        fill = reference + half_spread + slippage if direction == "LONG" else reference - half_spread - slippage
        if fill <= 0:
            return None

        sl_distance = float(final["sl_distance"])
        tp_rr = float(final.get("tp_rr", config.V7_TREND_TP_RR))
        be_rr = float(final.get("be_trigger_rr", config.V7_BE_TRIGGER_RR))
        tp_distance = sl_distance * tp_rr
        be_distance = sl_distance * be_rr
        if direction == "LONG":
            sl, tp1, tp2 = fill - sl_distance, fill + be_distance, fill + tp_distance
        else:
            sl, tp1, tp2 = fill + sl_distance, fill - be_distance, fill - tp_distance

        fee_rate = self._get_fee_rate(final)
        final["fee_rate"] = fee_rate
        leverage = int(final.get("leverage") or config.MAX_LEVERAGE)
        size = float(final["size_oz"])
        rt_cost_oz = fill * fee_rate * 2.0 + spread + slippage * 2.0

        # v7 provides a full stop-out budget.  Re-size after the adverse fill so
        # rounding or a changed quote cannot push price risk + costs over it.
        risk_budget = float(final.get("risk_budget_usd") or 0.0)
        if risk_budget > 0:
            max_risk_size = math.floor((risk_budget / (sl_distance + rt_cost_oz)) * 10_000) / 10_000
            size = min(size, max_risk_size)
            if size < 0.01:
                return None

        margin = fill * size / max(leverage, 1)
        entry_fee = fill * size * fee_rate
        margin_cap_pct = min(
            config.MARGIN_CAP_PCT, float(final.get("margin_cap_pct") or config.MARGIN_CAP_PCT)
        )
        cap = balance * (margin_cap_pct / 100.0)
        if margin > cap:
            size = math.floor(((cap * leverage / fill) * 10_000)) / 10_000
            if size < 0.01:
                return None
            margin = fill * size / max(leverage, 1)
            entry_fee = fill * size * fee_rate
        if margin + entry_fee > balance:
            return None

        expected_cost = rt_cost_oz * size
        final.update(
            {
                "reference_price": round(reference, 4),
                "entry_price": round(fill, 4),
                "sl_price": round(sl, 4),
                "initial_sl_price": round(sl, 4),
                "tp1_price": round(tp1, 4),
                "tp2_price": round(tp2, 4),
                "size_oz": size,
                "leverage": leverage,
                "required_margin_usd": round(margin, 4),
                "entry_fee_usd": round(entry_fee, 6),
                "dollar_risk": round(size * (sl_distance + rt_cost_oz), 4),
                "spread": round(spread, 4),
                "estimated_round_trip_cost_per_oz": round(rt_cost_oz, 6),
                "expected_cost_usd": round(expected_cost, 6),
                "expected_net_reward_usd": round(max(0.0, size * (tp_distance - rt_cost_oz)), 6),
            }
        )
        return final

    def _save_decision_audit(
        self,
        market_data: Dict[str, Any],
        status: str,
        reason: str,
        plan: Optional[Dict[str, Any]] = None,
    ) -> None:
        # Account-level blocks happen before the strategy is evaluated.  Do not
        # attach a stale setup/score from the previous candle to those rows.
        evaluation = (
            dict(getattr(self.decision_engine, "last_evaluation", {}) or {})
            if status == "REJECTED" or plan is not None
            else {}
        )
        if plan:
            evaluation.update(
                {
                    "setup_name": plan.get("setup_name"),
                    "direction": plan.get("direction"),
                    "session_name": plan.get("session_name", plan.get("killzone_session")),
                    "regime": plan.get("regime"),
                    "signal_score": plan.get("signal_score"),
                    "strategy_version": plan.get("strategy_version", config.STRATEGY_VERSION),
                }
            )
        evaluation.update(
            {
                "status": status,
                "reason": reason,
                "account_balance": self.db.get_current_balance(),
                "daily_realized_pnl": self.db.get_daily_realized_pnl(),
                "open_trade_count": len(self.db.get_open_trades()),
                "strategy_version": evaluation.get("strategy_version", config.STRATEGY_VERSION),
            }
        )
        self.db.save_decision_audit(market_data, evaluation)

    def try_open_new_trade(self, market_data: Dict[str, Any]) -> None:
        if not self.new_entries_enabled:
            self._save_decision_audit(market_data, "BLOCKED", "ENTRIES_PAUSED")
            return
        now = datetime.now(timezone.utc)
        force = bool(market_data.get("force_signal"))
        bar_timestamp = market_data.get("bar_timestamp_ms")
        if self._entries_blocked_until and now < self._entries_blocked_until and not force:
            self._save_decision_audit(market_data, "BLOCKED", "ENTRY_COOLDOWN")
            return
        if len(self.db.get_open_trades()) >= config.MAX_OPEN_TRADES:
            self._save_decision_audit(market_data, "BLOCKED", "MAX_OPEN_TRADES")
            return
        if not force and self.db.has_signal_for_bar(bar_timestamp):
            # Preserve the existing EXECUTED audit row instead of replacing it
            # with a restart/idempotency reason for the same candle.
            return
        if not force and self.db.count_trades_opened_today() >= config.MAX_TRADES_PER_DAY:
            logger.info("Max trades/day (%s) reached", config.MAX_TRADES_PER_DAY)
            self._save_decision_audit(market_data, "BLOCKED", "MAX_TRADES_PER_DAY")
            return

        balance = self.db.get_current_balance()
        if balance < 5.0:
            logger.warning("Balance too low ($%.2f)", balance)
            self._save_decision_audit(market_data, "BLOCKED", "BALANCE_TOO_LOW")
            return
        if not force and self._daily_loss_breached(balance):
            logger.warning("Daily loss limit reached; entries blocked")
            self._save_decision_audit(market_data, "BLOCKED", "DAILY_LOSS_LIMIT")
            return

        plan = self.decision_engine.evaluate(market_data, balance)
        if not plan:
            evaluation = getattr(self.decision_engine, "last_evaluation", {}) or {}
            self._save_decision_audit(
                market_data,
                str(evaluation.get("status") or "REJECTED"),
                str(evaluation.get("reason") or "NO_STRATEGY_PLAN"),
            )
            return
        raw_plan = plan
        plan = self._finalize_paper_fill(raw_plan, market_data, balance)
        if not plan:
            logger.warning("Paper fill rejected by margin/price guard")
            self._save_decision_audit(
                market_data, "FILL_REJECTED", "MARGIN_OR_RISK_GUARD", raw_plan
            )
            return
        direction = str(plan["direction"])

        plan["opened_at"] = now.isoformat()
        signal_id = self.db.save_signal(plan)
        plan["signal_id"] = signal_id
        trade_id = self.db.open_trade(plan)
        self.db.update_signal_status(signal_id, "EXECUTED")
        self._save_decision_audit(market_data, "EXECUTED", "TRADE_OPENED", plan)

        self.emit_alert(
            f"🚀 <b>NEW PAPER TRADE #{trade_id}</b> · <code>{plan.get('strategy_version', config.STRATEGY_VERSION)}</code>\n"
            f"Setup: <b>{plan.get('setup_name', 'SETUP')}</b> | <b>{direction}</b> {plan['symbol']}"
            f" | Score <b>{int(plan.get('signal_score') or 0)}</b>\n"
            f"Signal / fill: <b>${plan['reference_price']:.2f} → ${plan['entry_price']:.2f}</b>\n"
            f"Z: <b>{float(plan.get('zscore', 0)):+.2f}</b> | SL <b>${plan['sl_price']:.2f}</b> | "
            f"TP <b>${plan['tp2_price']:.2f}</b>\n"
            f"Size <b>{plan['size_oz']:.4f} oz</b> | Margin <b>${plan['required_margin_usd']:.2f}</b> "
            f"| Est. RT cost <b>${float(plan.get('expected_cost_usd') or 0):.3f}</b>\n"
            f"Full stop risk incl. costs: <b>${plan['dollar_risk']:.2f}</b>"
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

        # Keep the full closed-bar feature set.  Signals alone would omit every
        # rejected opportunity and make later strategy research selection-biased.
        self.db.save_market_bar(market_data)

        # Manage first: a new decision cannot benefit from the bar that created it.
        self.evaluate_open_trades(market_data)
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
