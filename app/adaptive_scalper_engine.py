"""v7 adaptive-session XAU-USDT forward-paper strategy.

This is a deliberately measurable rewrite, not a claim of discovered alpha.
The previous strategy combined rare binary filters with an in-memory session
counter that never rolled to a new date.  v7 instead routes three tagged setup
families through common execution and risk gates:

* liquidity-level rejection (Asian range and previous-day extremes),
* trend pullback/momentum continuation, and
* range stretch/reclaim.

The strategy is score based, but a score cannot bypass spread, volatility,
session, cost, position-size, daily-loss, or account trade-count controls.
Every accepted setup stores its family, regime, score and expected cost so that
a forward sample can reject weak branches rather than hide them in aggregate.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.config import config as app_config

logger = logging.getLogger("AdaptiveSessionScalper")


@dataclass
class AdaptiveScalperConfig:
    STRATEGY_VERSION: str = "v7-adaptive-session-scalper"
    SYMBOL: str = "XAU-USDT"
    SESSIONS: List[Tuple[int, int]] = field(default_factory=lambda: [(6, 20)])

    MAX_LEVERAGE: int = 50
    MARGIN_CAP_PCT: float = 25.0
    RISK_PER_TRADE_PCT: float = 0.50
    MAX_SPREAD_USD: float = 0.40
    MIN_ATR_USD: float = 0.80
    ATR_SHOCK_MULTIPLE: float = 2.20

    RANGE_Z_ENTRY: float = 1.60
    RANGE_ADX_MAX: float = 23.0
    TREND_ADX_MIN: float = 18.0
    MIN_SIGNAL_SCORE: int = 4

    RANGE_TP_RR: float = 1.35
    TREND_TP_RR: float = 1.60
    LIQUIDITY_TP_RR: float = 1.50
    BE_TRIGGER_RR: float = 1.00
    RANGE_MAX_HOLDING_BARS: int = 8
    TREND_MAX_HOLDING_BARS: int = 12

    FEE_RATE: float = 0.0004
    SLIPPAGE_USD: float = 0.03
    MIN_STOP_COST_MULTIPLE: float = 1.25
    MIN_TARGET_COST_MULTIPLE: float = 1.50
    MIN_NET_ADAPTIVE_EXIT_USD: float = 0.03

    @classmethod
    def from_app_config(cls) -> "AdaptiveScalperConfig":
        return cls(
            SYMBOL=app_config.SYMBOL,
            SESSIONS=list(app_config.V7_ALLOWED_SESSIONS),
            MAX_LEVERAGE=app_config.MAX_LEVERAGE,
            MARGIN_CAP_PCT=min(app_config.MARGIN_CAP_PCT, 25.0),
            RISK_PER_TRADE_PCT=min(
                app_config.RISK_PER_TRADE_PCT, app_config.V7_RISK_CAP_PCT
            ),
            MAX_SPREAD_USD=app_config.MAX_ALLOWABLE_SPREAD_USD,
            MIN_ATR_USD=app_config.MIN_ATR_USD,
            ATR_SHOCK_MULTIPLE=app_config.V7_ATR_SHOCK_MULTIPLE,
            RANGE_Z_ENTRY=app_config.V7_RANGE_Z_ENTRY,
            RANGE_ADX_MAX=app_config.V7_RANGE_ADX_MAX,
            TREND_ADX_MIN=app_config.V7_TREND_ADX_MIN,
            MIN_SIGNAL_SCORE=app_config.V7_MIN_SIGNAL_SCORE,
            RANGE_TP_RR=app_config.V7_RANGE_TP_RR,
            TREND_TP_RR=app_config.V7_TREND_TP_RR,
            LIQUIDITY_TP_RR=app_config.V7_LIQUIDITY_TP_RR,
            BE_TRIGGER_RR=app_config.V7_BE_TRIGGER_RR,
            RANGE_MAX_HOLDING_BARS=app_config.V7_RANGE_MAX_HOLDING_BARS,
            TREND_MAX_HOLDING_BARS=app_config.V7_TREND_MAX_HOLDING_BARS,
            FEE_RATE=app_config.paper_fee_rate,
            SLIPPAGE_USD=app_config.PAPER_SLIPPAGE_USD,
            MIN_STOP_COST_MULTIPLE=app_config.V7_MIN_STOP_COST_MULTIPLE,
            MIN_TARGET_COST_MULTIPLE=app_config.V7_MIN_TARGET_COST_MULTIPLE,
        )


@dataclass
class SetupCandidate:
    direction: str
    setup_name: str
    score: int
    reason: str
    extreme: float
    target_rr: float
    max_holding_bars: int


class AdaptiveSessionScalper:
    """Closed-M5 score router with conservative cost-inclusive risk sizing."""

    def __init__(self, strategy_config: Optional[AdaptiveScalperConfig] = None) -> None:
        self.config = strategy_config or AdaptiveScalperConfig.from_app_config()
        self.last_evaluation: Dict[str, Any] = {
            "status": "WAITING",
            "reason": "No closed candle evaluated yet",
        }

    @staticmethod
    def _as_utc(value: Any) -> datetime:
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                value = datetime.now(timezone.utc)
        if not isinstance(value, datetime):
            value = datetime.now(timezone.utc)
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _reject(self, reason: str, **details: Any) -> None:
        self.last_evaluation = {"status": "REJECTED", "reason": reason, **details}
        logger.debug("v7 reject: %s", reason)

    def _session_name(self, hour: int) -> Optional[str]:
        if not any(start <= hour < end for start, end in self.config.SESSIONS):
            return None
        if 6 <= hour < 11:
            return "LONDON"
        if 11 <= hour < 16:
            return "LONDON_NY_OVERLAP"
        if 16 <= hour < 20:
            return "NEW_YORK_PM"
        return "LIQUID_SESSION"

    def _regime(
        self, adx: float, atr: float, ema_21: float, ema_50: float
    ) -> Tuple[str, str]:
        separation_atr = abs(ema_21 - ema_50) / max(atr, 1e-9)
        if adx >= self.config.TREND_ADX_MIN and separation_atr >= 0.08:
            direction = "UP" if ema_21 > ema_50 else "DOWN"
            return "TRENDING", f"{direction} ADX={adx:.1f} EMAsep={separation_atr:.2f}ATR"
        if adx <= self.config.RANGE_ADX_MAX and separation_atr <= 0.45:
            return "RANGING", f"ADX={adx:.1f} EMAsep={separation_atr:.2f}ATR"
        return "TRANSITION", f"ADX={adx:.1f} EMAsep={separation_atr:.2f}ATR"

    @staticmethod
    def _dedupe_levels(levels: List[Tuple[str, float]]) -> List[Tuple[str, float]]:
        result: List[Tuple[str, float]] = []
        for name, value in levels:
            if value <= 0 or any(abs(value - existing) < 0.01 for _, existing in result):
                continue
            result.append((name, value))
        return result

    def _liquidity_candidates(
        self,
        market: Dict[str, Any],
        regime: str,
        price: float,
        open_px: float,
        high: float,
        low: float,
        atr: float,
        rsi: float,
        plus_di: float,
        minus_di: float,
    ) -> List[SetupCandidate]:
        candidates: List[SetupCandidate] = []
        range_size = max(high - low, 1e-9)
        close_location = (price - low) / range_size
        pierce = max(0.15, atr * 0.12)
        asian_ready = bool(market.get("asian_range_ready", False))

        high_levels: List[Tuple[str, float]] = [("PDH", float(market.get("pdh", 0.0) or 0.0))]
        low_levels: List[Tuple[str, float]] = [("PDL", float(market.get("pdl", 0.0) or 0.0))]
        if asian_ready:
            high_levels.append(("ASIAN_HIGH", float(market.get("asian_high", 0.0) or 0.0)))
            low_levels.append(("ASIAN_LOW", float(market.get("asian_low", 0.0) or 0.0)))

        for name, level in self._dedupe_levels(high_levels):
            if high >= level + pierce and price < level and price < open_px:
                score = 2  # objective reference + completed sweep/reclaim
                score += int(close_location <= 0.45)
                score += int(rsi >= 52.0)
                score += int(minus_di >= plus_di or regime != "TRENDING")
                candidates.append(
                    SetupCandidate(
                        "SHORT",
                        "LIQUIDITY_REJECTION",
                        score,
                        f"{name} ${level:.2f} swept by ${high - level:.2f} and reclaimed",
                        high,
                        self.config.LIQUIDITY_TP_RR,
                        self.config.RANGE_MAX_HOLDING_BARS,
                    )
                )

        for name, level in self._dedupe_levels(low_levels):
            if low <= level - pierce and price > level and price > open_px:
                score = 2
                score += int(close_location >= 0.55)
                score += int(rsi <= 48.0)
                score += int(plus_di >= minus_di or regime != "TRENDING")
                candidates.append(
                    SetupCandidate(
                        "LONG",
                        "LIQUIDITY_REJECTION",
                        score,
                        f"{name} ${level:.2f} swept by ${level - low:.2f} and reclaimed",
                        low,
                        self.config.LIQUIDITY_TP_RR,
                        self.config.RANGE_MAX_HOLDING_BARS,
                    )
                )
        return candidates

    def _trend_candidates(
        self,
        market: Dict[str, Any],
        regime: str,
        price: float,
        open_px: float,
        high: float,
        low: float,
        atr: float,
        adx: float,
        rsi: float,
        plus_di: float,
        minus_di: float,
        ema_21: float,
        ema_50: float,
        ema_200: float,
        vwap: float,
    ) -> List[SetupCandidate]:
        if regime != "TRENDING":
            return []
        candidates: List[SetupCandidate] = []
        prev_close = float(market.get("prev_close", price))
        prev_high = float(market.get("prev_high", high))
        prev_low = float(market.get("prev_low", low))
        prev_ema_21 = float(market.get("ema_21_prev", ema_21))
        bullish = price > open_px
        bearish = price < open_px

        stack_long = price > ema_21 > ema_50 and ema_50 >= ema_200
        pullback_long = low <= ema_21 + atr * 0.20 and price > ema_21 and bullish
        momentum_long = price > prev_high + atr * 0.03 and prev_close >= prev_ema_21 and bullish
        if stack_long and (pullback_long or momentum_long):
            score = 1 + int(adx >= self.config.TREND_ADX_MIN) + int(plus_di > minus_di)
            score += int(48.0 <= rsi <= 72.0) + int(price >= vwap)
            score += 1  # a reclaim or previous-high continuation trigger is mandatory
            setup = "TREND_PULLBACK_RECLAIM" if pullback_long else "MOMENTUM_CONTINUATION"
            reason = (
                f"bull EMA stack; {'EMA21 pullback reclaimed' if pullback_long else 'prior high broken'}; "
                f"ADX={adx:.1f} DI+/-={plus_di:.1f}/{minus_di:.1f}"
            )
            candidates.append(
                SetupCandidate(
                    "LONG", setup, score, reason, min(low, prev_low),
                    self.config.TREND_TP_RR, self.config.TREND_MAX_HOLDING_BARS,
                )
            )

        stack_short = price < ema_21 < ema_50 and ema_50 <= ema_200
        pullback_short = high >= ema_21 - atr * 0.20 and price < ema_21 and bearish
        momentum_short = price < prev_low - atr * 0.03 and prev_close <= prev_ema_21 and bearish
        if stack_short and (pullback_short or momentum_short):
            score = 1 + int(adx >= self.config.TREND_ADX_MIN) + int(minus_di > plus_di)
            score += int(28.0 <= rsi <= 52.0) + int(price <= vwap)
            score += 1
            setup = "TREND_PULLBACK_RECLAIM" if pullback_short else "MOMENTUM_CONTINUATION"
            reason = (
                f"bear EMA stack; {'EMA21 pullback rejected' if pullback_short else 'prior low broken'}; "
                f"ADX={adx:.1f} DI+/-={plus_di:.1f}/{minus_di:.1f}"
            )
            candidates.append(
                SetupCandidate(
                    "SHORT", setup, score, reason, max(high, prev_high),
                    self.config.TREND_TP_RR, self.config.TREND_MAX_HOLDING_BARS,
                )
            )
        return candidates

    def _range_candidates(
        self,
        market: Dict[str, Any],
        regime: str,
        price: float,
        open_px: float,
        high: float,
        low: float,
        rsi: float,
        zscore: float,
        vwap: float,
    ) -> List[SetupCandidate]:
        if regime != "RANGING":
            return []
        candidates: List[SetupCandidate] = []
        prev_close = float(market.get("prev_close", price))
        prev_high = float(market.get("prev_high", high))
        prev_low = float(market.get("prev_low", low))
        candle_range = max(high - low, 1e-9)
        close_location = (price - low) / candle_range

        long_trigger = price > open_px and price > prev_close and (low <= prev_low or close_location >= 0.65)
        if zscore <= -self.config.RANGE_Z_ENTRY and long_trigger:
            score = 2 + 1  # stretch plus a completed reclaim bar
            score += int(rsi <= 45.0)
            score += int(price <= vwap)
            score += int(close_location >= 0.65)
            candidates.append(
                SetupCandidate(
                    "LONG",
                    "RANGE_STRETCH_RECLAIM",
                    score,
                    f"Z={zscore:.2f} downside stretch reclaimed; RSI={rsi:.1f}",
                    min(low, prev_low),
                    self.config.RANGE_TP_RR,
                    self.config.RANGE_MAX_HOLDING_BARS,
                )
            )

        short_trigger = price < open_px and price < prev_close and (high >= prev_high or close_location <= 0.35)
        if zscore >= self.config.RANGE_Z_ENTRY and short_trigger:
            score = 2 + 1
            score += int(rsi >= 55.0)
            score += int(price >= vwap)
            score += int(close_location <= 0.35)
            candidates.append(
                SetupCandidate(
                    "SHORT",
                    "RANGE_STRETCH_RECLAIM",
                    score,
                    f"Z={zscore:.2f} upside stretch rejected; RSI={rsi:.1f}",
                    max(high, prev_high),
                    self.config.RANGE_TP_RR,
                    self.config.RANGE_MAX_HOLDING_BARS,
                )
            )
        return candidates

    def evaluate(self, market_data: Dict[str, Any], account_balance: float) -> Optional[Dict[str, Any]]:
        """Return one cost-aware plan from a completed M5 candle, or ``None``."""
        now = self._as_utc(market_data.get("timestamp"))
        force = bool(market_data.get("force_signal", False))
        price = float(market_data["close"])
        open_px = float(market_data.get("open", price))
        high = float(market_data.get("high", price))
        low = float(market_data.get("low", price))
        spread = max(0.0, float(market_data.get("spread", self.config.MAX_SPREAD_USD)))
        atr = float(market_data.get("atr_14", 0.0))
        atr_avg = float(market_data.get("atr_avg", atr))
        adx = float(market_data.get("adx", 0.0))
        rsi = float(market_data.get("rsi_14", 50.0))
        plus_di = float(market_data.get("plus_di", 20.0))
        minus_di = float(market_data.get("minus_di", 20.0))
        ema_21 = float(market_data.get("ema_21", price))
        ema_50 = float(market_data.get("ema_50", price))
        ema_200 = float(market_data.get("ema_200", ema_50))
        vwap = float(market_data.get("vwap", price))
        sma = float(market_data.get("sma_z", market_data.get("sma_20", price)))
        stdev = float(market_data.get("stdev_z", market_data.get("stdev_20", 0.0)))
        zscore = float(market_data.get("zscore", 0.0))
        if "zscore" not in market_data and stdev > 1e-9:
            zscore = (price - sma) / stdev

        session = self._session_name(now.hour)
        if session is None and not force:
            self._reject("OUTSIDE_V7_SESSION", hour_utc=now.hour)
            return None
        session = session or "MANUAL_FORCE"
        if spread > self.config.MAX_SPREAD_USD and not force:
            self._reject("SPREAD_TOO_WIDE", spread=spread)
            return None
        if atr < self.config.MIN_ATR_USD and not force:
            self._reject("VOLATILITY_TOO_LOW", atr=atr)
            return None
        if atr_avg > 0 and atr > atr_avg * self.config.ATR_SHOCK_MULTIPLE and not force:
            self._reject("ATR_SHOCK_VETO", atr=atr, atr_avg=atr_avg)
            return None
        if bool(market_data.get("is_news_window", False)) and not force:
            self._reject("NEWS_WINDOW_VETO")
            return None

        regime, regime_reason = self._regime(adx, atr, ema_21, ema_50)
        candidates: List[SetupCandidate] = []
        candidates.extend(
            self._liquidity_candidates(
                market_data, regime, price, open_px, high, low, atr, rsi, plus_di, minus_di
            )
        )
        candidates.extend(
            self._trend_candidates(
                market_data, regime, price, open_px, high, low, atr, adx, rsi,
                plus_di, minus_di, ema_21, ema_50, ema_200, vwap,
            )
        )
        candidates.extend(
            self._range_candidates(
                market_data, regime, price, open_px, high, low, rsi, zscore, vwap
            )
        )

        if force:
            direction = str(market_data.get("force_direction", "LONG")).upper()
            candidates = [
                SetupCandidate(
                    direction,
                    "FORCE_OVERRIDE",
                    99,
                    "Telegram paper-execution plumbing test",
                    low if direction == "LONG" else high,
                    self.config.TREND_TP_RR,
                    self.config.RANGE_MAX_HOLDING_BARS,
                )
            ]

        eligible = [c for c in candidates if c.score >= self.config.MIN_SIGNAL_SCORE or force]
        candidate_snapshot = [
            {
                "setup_name": candidate.setup_name,
                "direction": candidate.direction,
                "score": candidate.score,
                "reason": candidate.reason,
            }
            for candidate in candidates
        ]
        if not eligible:
            best = max((c.score for c in candidates), default=0)
            self._reject(
                "NO_SETUP_SCORE",
                regime=regime,
                best_score=best,
                required_score=self.config.MIN_SIGNAL_SCORE,
                candidates=candidate_snapshot,
            )
            return None

        eligible.sort(key=lambda c: (c.score, c.setup_name == "LIQUIDITY_REJECTION"), reverse=True)
        best = eligible[0]
        tied_directions = {c.direction for c in eligible if c.score == best.score}
        if len(tied_directions) > 1 and not force:
            self._reject(
                "AMBIGUOUS_OPPOSING_SETUPS",
                score=best.score,
                regime=regime,
                candidates=candidate_snapshot,
            )
            return None

        # Full round-trip cost per ounce from the actual paper execution model:
        # entry + exit fee, full spread, and adverse slippage on both fills.
        rt_cost_oz = (
            price * self.config.FEE_RATE * 2.0
            + spread
            + self.config.SLIPPAGE_USD * 2.0
        )
        structure_distance = (
            price - best.extreme if best.direction == "LONG" else best.extreme - price
        )
        atr_floor = atr * (1.15 if best.setup_name.startswith("TREND") or best.setup_name == "MOMENTUM_CONTINUATION" else 1.20)
        raw_stop = max(structure_distance + atr * 0.12, atr_floor)
        sl_distance = max(raw_stop, rt_cost_oz * self.config.MIN_STOP_COST_MULTIPLE)
        tp_distance = sl_distance * best.target_rr
        if tp_distance < rt_cost_oz * self.config.MIN_TARGET_COST_MULTIPLE and not force:
            self._reject(
                "TARGET_CANNOT_CLEAR_COST",
                target_distance=tp_distance,
                round_trip_cost_per_oz=rt_cost_oz,
            )
            return None

        risk_budget = account_balance * (self.config.RISK_PER_TRADE_PCT / 100.0)
        # A stop-out budget includes both price risk and estimated round-trip
        # costs.  This fixes the old behavior where fees could exceed the 1R
        # price loss while position sizing still claimed one-percent risk.
        size = math.floor((risk_budget / (sl_distance + rt_cost_oz)) * 10_000) / 10_000
        if size < 0.01:
            self._reject("SIZE_BELOW_MINIMUM", risk_budget=risk_budget)
            return None

        required_margin = price * size / max(self.config.MAX_LEVERAGE, 1)
        margin_cap = account_balance * self.config.MARGIN_CAP_PCT / 100.0
        if required_margin > margin_cap:
            size = math.floor(
                ((margin_cap * self.config.MAX_LEVERAGE / price) * 10_000)
            ) / 10_000
            if size < 0.01:
                self._reject("MARGIN_CAP_SIZE_BELOW_MINIMUM")
                return None
            required_margin = price * size / self.config.MAX_LEVERAGE

        if best.direction == "LONG":
            sl_price = price - sl_distance
            tp1_price = price + sl_distance * self.config.BE_TRIGGER_RR
            tp2_price = price + tp_distance
        else:
            sl_price = price + sl_distance
            tp1_price = price - sl_distance * self.config.BE_TRIGGER_RR
            tp2_price = price - tp_distance

        estimated_cost = rt_cost_oz * size
        estimated_net_reward = max(0.0, (tp_distance - rt_cost_oz) * size)
        dollar_risk = (sl_distance + rt_cost_oz) * size
        plan: Dict[str, Any] = {
            "timestamp": now.isoformat(),
            "bar_timestamp_ms": market_data.get("bar_timestamp_ms"),
            "source": market_data.get("source", "UNKNOWN"),
            "symbol": self.config.SYMBOL,
            "direction": best.direction,
            "reference_price": round(price, 4),
            "entry_price": round(price, 4),
            "sl_price": round(sl_price, 4),
            "initial_sl_price": round(sl_price, 4),
            "tp1_price": round(tp1_price, 4),
            "tp2_price": round(tp2_price, 4),
            "size_oz": size,
            "leverage": self.config.MAX_LEVERAGE,
            "margin_cap_pct": self.config.MARGIN_CAP_PCT,
            "required_margin_usd": round(required_margin, 4),
            "risk_budget_usd": round(risk_budget, 6),
            "dollar_risk": round(dollar_risk, 6),
            "sl_distance": round(sl_distance, 6),
            "setup_name": best.setup_name,
            "signal_score": best.score,
            "be_trigger_rr": self.config.BE_TRIGGER_RR,
            "tp_rr": best.target_rr,
            "trail_atr_mult": 0.0,
            "atr_at_entry": atr,
            "spread": round(spread, 4),
            "fee_rate": self.config.FEE_RATE,
            "estimated_round_trip_cost_per_oz": round(rt_cost_oz, 6),
            "expected_cost_usd": round(estimated_cost, 6),
            "expected_net_reward_usd": round(estimated_net_reward, 6),
            "zscore": round(zscore, 4),
            "adx": round(adx, 4),
            "rsi_at_entry": round(rsi, 4),
            "layer1_regime": f"[{session}] {regime_reason}",
            "layer2_structure": f"[{best.setup_name}] score={best.score}: {best.reason}",
            "layer3_momentum": (
                f"ATR=${atr:.2f} Z={zscore:.2f} RSI={rsi:.1f} "
                f"DI+/-={plus_di:.1f}/{minus_di:.1f}"
            ),
            "reason": best.reason,
            "status": "NEW",
            "strategy_version": self.config.STRATEGY_VERSION,
            "session_name": session,
            "killzone_session": session,
            "regime": regime,
            "max_holding_bars": best.max_holding_bars,
        }
        self.last_evaluation = {
            "status": "ACCEPTED",
            "reason": best.setup_name,
            "setup_name": best.setup_name,
            "score": best.score,
            "regime": regime,
            "direction": best.direction,
            "session_name": session,
            "candidates": candidate_snapshot,
        }
        logger.info(
            "v7 %s %s score=%d @ %.2f | SL %.2f | TP %.2f | cost $%.3f | risk $%.3f",
            best.setup_name,
            best.direction,
            best.score,
            price,
            sl_price,
            tp2_price,
            estimated_cost,
            dollar_risk,
        )
        return plan

    def check_adaptive_exit(
        self,
        trade: Dict[str, Any],
        current_bar: Dict[str, Any],
        bars_held: int,
    ) -> Optional[str]:
        """Apply setup-specific exits using real current-bar indicators.

        ``estimated_net_pnl_usd`` is calculated by the paper executor using an
        executable bid/ask + slippage exit.  Value exits are not allowed to turn
        a small gross win into another fee loss.
        """
        setup = str(trade.get("setup_name") or "")
        direction = str(trade.get("direction") or "LONG")
        price = float(current_bar.get("close", 0.0))
        sma = float(current_bar.get("sma_z", current_bar.get("sma_20", price)))
        stdev = float(current_bar.get("stdev_z", current_bar.get("stdev_20", 0.0)))
        zscore = float(current_bar.get("zscore", 0.0))
        if "zscore" not in current_bar and stdev > 1e-9:
            zscore = (price - sma) / stdev
        estimated_net = float(current_bar.get("estimated_net_pnl_usd", -math.inf))
        ema_50 = float(current_bar.get("ema_50", price))
        open_px = float(current_bar.get("open", price))
        max_bars = int(
            trade.get("max_holding_bars") or self.config.RANGE_MAX_HOLDING_BARS
        )

        if bars_held >= 2 and setup in (
            "RANGE_STRETCH_RECLAIM",
            "LIQUIDITY_REJECTION",
        ):
            reached_value = abs(zscore) <= 0.30
            crossed_value = (direction == "LONG" and price >= sma) or (
                direction == "SHORT" and price <= sma
            )
            if (
                (reached_value or crossed_value)
                and estimated_net >= self.config.MIN_NET_ADAPTIVE_EXIT_USD
            ):
                return "VALUE_TARGET_EXIT"

        if bars_held >= 2 and setup in (
            "TREND_PULLBACK_RECLAIM",
            "MOMENTUM_CONTINUATION",
        ):
            if direction == "LONG" and price < ema_50 and price < open_px:
                return "TREND_FAILURE_EXIT"
            if direction == "SHORT" and price > ema_50 and price > open_px:
                return "TREND_FAILURE_EXIT"

        if bars_held >= max_bars:
            return "TIME_EXIT"
        return None


adaptive_scalper_engine = AdaptiveSessionScalper()
