"""
Gold Edge v4 — Decision Engine (post-backtest overhaul).

Lessons from v3 on real 5m history (PF 0.49):
  • Early BE @ 1R destroyed expectancy
  • 4R almost never filled
  • Naked Asia breakouts were noise

v4 stack:
  L1 Session + spread
  L2 Vol + cost gate
  L3 Trend regime (EMA stack + ADX)
  L4 Structure (priority):
       EMA_PULLBACK  — trend pullback to EMA21 (primary)
       NY_ORB        — close beyond NY range + stack
       ASIA_BREAKOUT — close beyond Asia + buffer + stack (strict)
       ASIA_SWEEP    — range fade with larger pierce
  L5 Momentum confirm (RSI band, impulse bar)
  L6 Risk: SL 1.8×ATR, TP 2.0R, BE only after 1.5R
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.config import config

logger = logging.getLogger("DecisionEngine")


class TechnicalIndicators:
    @staticmethod
    def calculate_ema(prices: List[float], period: int) -> float:
        if not prices:
            return 0.0
        if len(prices) < period:
            return prices[-1]
        mult = 2 / (period + 1)
        ema = sum(prices[:period]) / period
        for p in prices[period:]:
            ema = (p - ema) * mult + ema
        return ema

    @staticmethod
    def calculate_atr(
        highs: List[float], lows: List[float], closes: List[float], period: int = 14
    ) -> float:
        if len(highs) < period + 1:
            return 1.80
        trs: List[float] = []
        for i in range(1, len(closes)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            trs.append(tr)
        if len(trs) < period:
            return sum(trs) / len(trs) if trs else 1.80
        atr = sum(trs[:period]) / period
        for tr in trs[period:]:
            atr = (atr * (period - 1) + tr) / period
        return atr

    @staticmethod
    def atr_series(
        highs: List[float], lows: List[float], closes: List[float], period: int = 14
    ) -> List[float]:
        if len(closes) < period + 1:
            return []
        trs: List[float] = []
        for i in range(1, len(closes)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            trs.append(tr)
        out: List[float] = []
        atr = sum(trs[:period]) / period
        out.append(atr)
        for tr in trs[period:]:
            atr = (atr * (period - 1) + tr) / period
            out.append(atr)
        return out

    @staticmethod
    def calculate_rsi(closes: List[float], period: int = 14) -> float:
        if len(closes) < period + 1:
            return 50.0
        gains: List[float] = []
        losses: List[float] = []
        for i in range(1, len(closes)):
            ch = closes[i] - closes[i - 1]
            gains.append(max(ch, 0.0))
            losses.append(max(-ch, 0.0))
        avg_g = sum(gains[:period]) / period
        avg_l = sum(losses[:period]) / period
        for i in range(period, len(gains)):
            avg_g = (avg_g * (period - 1) + gains[i]) / period
            avg_l = (avg_l * (period - 1) + losses[i]) / period
        if avg_l == 0:
            return 100.0
        rs = avg_g / avg_l
        return 100.0 - (100.0 / (1.0 + rs))

    @staticmethod
    def calculate_adx(
        highs: List[float],
        lows: List[float],
        closes: List[float],
        period: int = 14,
    ) -> Tuple[float, float, float]:
        n = len(closes)
        if n < period + 2:
            return 20.0, 20.0, 20.0

        plus_dm: List[float] = []
        minus_dm: List[float] = []
        trs: List[float] = []
        for i in range(1, n):
            up = highs[i] - highs[i - 1]
            down = lows[i - 1] - lows[i]
            plus_dm.append(up if up > down and up > 0 else 0.0)
            minus_dm.append(down if down > up and down > 0 else 0.0)
            trs.append(
                max(
                    highs[i] - lows[i],
                    abs(highs[i] - closes[i - 1]),
                    abs(lows[i] - closes[i - 1]),
                )
            )

        def wilder_smooth(vals: List[float], p: int) -> List[float]:
            if len(vals) < p:
                return []
            out = [sum(vals[:p])]
            for v in vals[p:]:
                out.append(out[-1] - (out[-1] / p) + v)
            return out

        atr_s = wilder_smooth(trs, period)
        p_s = wilder_smooth(plus_dm, period)
        m_s = wilder_smooth(minus_dm, period)
        if not atr_s or not p_s or not m_s:
            return 20.0, 20.0, 20.0

        dx_list: List[float] = []
        for i in range(len(atr_s)):
            atr_i = atr_s[i] if atr_s[i] != 0 else 1e-9
            pdi = 100.0 * p_s[i] / atr_i
            mdi = 100.0 * m_s[i] / atr_i
            denom = pdi + mdi
            dx = 100.0 * abs(pdi - mdi) / denom if denom else 0.0
            dx_list.append(dx)

        if len(dx_list) < period:
            adx = sum(dx_list) / len(dx_list)
        else:
            adx = sum(dx_list[:period]) / period
            for d in dx_list[period:]:
                adx = (adx * (period - 1) + d) / period

        atr_last = atr_s[-1] if atr_s[-1] != 0 else 1e-9
        plus_di = 100.0 * p_s[-1] / atr_last
        minus_di = 100.0 * m_s[-1] / atr_last
        return round(adx, 2), round(plus_di, 2), round(minus_di, 2)


class LayeredDecisionEngine:
    def __init__(self) -> None:
        self.tech = TechnicalIndicators()

    def evaluate(
        self, market_data: Dict[str, Any], account_balance: float
    ) -> Optional[Dict[str, Any]]:
        current_time = market_data.get("timestamp", datetime.now(timezone.utc))
        if isinstance(current_time, str):
            try:
                current_time = datetime.fromisoformat(current_time.replace("Z", "+00:00"))
            except ValueError:
                current_time = datetime.now(timezone.utc)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)

        force = bool(market_data.get("force_signal", False))
        price = float(market_data["close"])
        high = float(market_data.get("high", price))
        low = float(market_data.get("low", price))
        open_px = float(market_data.get("open", price))
        spread = float(market_data.get("spread", 0.15))
        atr = float(market_data.get("atr_14", 1.8))
        atr_avg = float(market_data.get("atr_avg", atr))
        rsi = float(market_data.get("rsi_14", 50.0))
        ema_200 = float(market_data.get("ema_200", price))
        ema_50 = float(market_data.get("ema_50", price))
        ema_21 = float(market_data.get("ema_21", market_data.get("ema_50", price)))
        vwap = float(market_data.get("vwap", price))
        adx = float(market_data.get("adx", 20.0))
        plus_di = float(market_data.get("plus_di", 20.0))
        minus_di = float(market_data.get("minus_di", 20.0))
        asian_high = float(market_data.get("asian_high", price + 5))
        asian_low = float(market_data.get("asian_low", price - 5))
        asian_ready = bool(market_data.get("asian_range_ready", True))
        ny_high = float(market_data.get("ny_orb_high", 0) or 0)
        ny_low = float(market_data.get("ny_orb_low", 0) or 0)
        ny_ready = bool(market_data.get("ny_orb_ready", False))
        prev_close = float(market_data.get("prev_close", price))
        prev_close_2 = float(market_data.get("prev_close_2", prev_close))
        prev_high = float(market_data.get("prev_high", high))
        prev_low = float(market_data.get("prev_low", low))

        utc_hour = current_time.astimezone(timezone.utc).hour
        body = abs(price - open_px)
        bullish_bar = price > open_px
        bearish_bar = price < open_px

        # =========================================================
        # L1 — SESSION
        # =========================================================
        session_ok = any(s <= utc_hour < e for s, e in config.ALLOWED_SESSIONS)
        if config.ENABLE_NY_ORB and utc_hour == config.NY_ORB_DECISION_HOUR_UTC:
            session_ok = True
        if not session_ok and not force:
            return None
        if spread > config.MAX_ALLOWABLE_SPREAD_USD and not force:
            return None

        # =========================================================
        # L2 — VOL + COST
        # =========================================================
        if atr < config.MIN_ATR_USD and not force:
            return None
        if atr_avg > 0 and not force:
            ratio = atr / atr_avg
            if ratio < config.ATR_VS_AVG_MIN or ratio > config.ATR_VS_AVG_MAX:
                return None

        sl_distance = max(config.MIN_SL_USD, round(atr * config.SL_ATR_MULTIPLIER, 2))
        rt_cost = max(spread * 2.0, config.ROUND_TRIP_COST_USD)
        if not force:
            if sl_distance < rt_cost * config.MIN_SL_COST_MULTIPLE:
                return None
            if sl_distance * config.TP_RR_RATIO < rt_cost * config.MIN_TP_COST_MULTIPLE:
                return None

        # =========================================================
        # L3 — TREND / STACK
        # =========================================================
        stack_bull = price > ema_21 > ema_50 > ema_200
        stack_bear = price < ema_21 < ema_50 < ema_200
        soft_bull = price > ema_50 > ema_200
        soft_bear = price < ema_50 < ema_200
        if not config.REQUIRE_EMA_STACK:
            stack_bull = soft_bull
            stack_bear = soft_bear

        di_spread = abs(plus_di - minus_di)
        is_ranging = adx <= config.ADX_RANGE_MAX
        is_trending = adx >= config.ADX_TREND_MIN

        bias: Optional[str] = None
        setup_name = ""
        layer4_reason = ""
        asian_range = max(0.0, asian_high - asian_low)
        buf = config.BREAKOUT_BUFFER_USD

        # --- Setup A: EMA pullback continuation (PRIMARY) ---
        if (
            not bias
            and config.ENABLE_EMA_PULLBACK
            and not force
            and is_trending
            and di_spread >= config.MIN_DI_SPREAD
        ):
            # Long: bull stack, pullback touched EMA21 zone, bounce bar
            near_ema = abs(low - ema_21) <= atr * 0.6 or abs(price - ema_21) <= atr * 0.5
            if (
                stack_bull
                and near_ema
                and bullish_bar
                and price > ema_21
                and prev_close <= prev_close_2  # prior bar was pullback-ish
                and plus_di > minus_di
                and 40 <= rsi <= config.RSI_OVERBOUGHT
            ):
                bias = "LONG"
                setup_name = "EMA_PULLBACK"
                layer4_reason = (
                    f"Bull stack pullback to EMA21 ${ema_21:.2f} | ADX {adx:.1f}"
                )
            near_ema_s = abs(high - ema_21) <= atr * 0.6 or abs(price - ema_21) <= atr * 0.5
            if (
                not bias
                and stack_bear
                and near_ema_s
                and bearish_bar
                and price < ema_21
                and prev_close >= prev_close_2
                and minus_di > plus_di
                and config.RSI_OVERSOLD <= rsi <= 60
            ):
                bias = "SHORT"
                setup_name = "EMA_PULLBACK"
                layer4_reason = (
                    f"Bear stack pullback to EMA21 ${ema_21:.2f} | ADX {adx:.1f}"
                )

        # --- Setup B: NY ORB (close beyond + stack) ---
        if (
            not bias
            and config.ENABLE_NY_ORB
            and not force
            and ny_ready
            and ny_high > 0
            and is_trending
            and utc_hour >= config.NY_ORB_DECISION_HOUR_UTC
        ):
            if (
                price > ny_high + buf
                and stack_bull
                and bullish_bar
                and plus_di > minus_di
                and di_spread >= config.MIN_DI_SPREAD
            ):
                bias = "LONG"
                setup_name = "NY_ORB_BREAKOUT"
                layer4_reason = f"NY ORB close ↑ ${ny_high:.2f}+buf | stack bull | ADX {adx:.1f}"
            elif (
                price < ny_low - buf
                and stack_bear
                and bearish_bar
                and minus_di > plus_di
                and di_spread >= config.MIN_DI_SPREAD
            ):
                bias = "SHORT"
                setup_name = "NY_ORB_BREAKOUT"
                layer4_reason = f"NY ORB close ↓ ${ny_low:.2f}-buf | stack bear | ADX {adx:.1f}"

        # --- Setup C: Asia breakout (STRICT — close beyond + buffer + stack) ---
        if (
            not bias
            and config.ENABLE_ASIA_BREAKOUT
            and not force
            and asian_ready
            and config.MIN_ASIAN_RANGE_USD <= asian_range <= config.MAX_ASIAN_RANGE_USD
            and is_trending
            and adx >= config.ADX_TREND_MIN
        ):
            if (
                price > asian_high + buf
                and price > vwap
                and stack_bull
                and bullish_bar
                and body >= atr * 0.25
                and plus_di > minus_di
                and di_spread >= config.MIN_DI_SPREAD
            ):
                bias = "LONG"
                setup_name = "ASIA_BREAKOUT"
                layer4_reason = (
                    f"Asia close-beyond ↑ ${asian_high:.2f}+{buf} | body ok | ADX {adx:.1f}"
                )
            elif (
                price < asian_low - buf
                and price < vwap
                and stack_bear
                and bearish_bar
                and body >= atr * 0.25
                and minus_di > plus_di
                and di_spread >= config.MIN_DI_SPREAD
            ):
                bias = "SHORT"
                setup_name = "ASIA_BREAKOUT"
                layer4_reason = (
                    f"Asia close-beyond ↓ ${asian_low:.2f}-{buf} | body ok | ADX {adx:.1f}"
                )

        # --- Setup D: Asia sweep fade (range only, larger pierce) ---
        if (
            not bias
            and config.ENABLE_SWEEP_FADE
            and not force
            and asian_ready
            and config.MIN_ASIAN_RANGE_USD <= asian_range <= config.MAX_ASIAN_RANGE_USD
            and is_ranging
        ):
            pierce = config.SWEEP_MIN_PIERCE_USD
            if (
                high >= asian_high + pierce
                and price < asian_high
                and price < ema_50
                and bearish_bar
                and prev_close <= prev_close_2
            ):
                bias = "SHORT"
                setup_name = "ASIA_SWEEP_FADE"
                layer4_reason = (
                    f"Asia high sweep+reject ${high:.2f}≥${asian_high:.2f}+{pierce} | range ADX {adx:.1f}"
                )
            elif (
                low <= asian_low - pierce
                and price > asian_low
                and price > ema_50
                and bullish_bar
                and prev_close >= prev_close_2
            ):
                bias = "LONG"
                setup_name = "ASIA_SWEEP_FADE"
                layer4_reason = (
                    f"Asia low sweep+reject ${low:.2f}≤${asian_low:.2f}-{pierce} | range ADX {adx:.1f}"
                )

        if not bias and force:
            bias = str(market_data.get("force_direction", "LONG")).upper()
            setup_name = "FORCE_OVERRIDE"
            layer4_reason = "Telegram / manual force"

        if not bias:
            return None

        # =========================================================
        # L5 — EXTRA CONFIRM (non-force)
        # =========================================================
        if not force:
            if bias == "LONG" and rsi > config.RSI_OVERBOUGHT:
                return None
            if bias == "SHORT" and rsi < config.RSI_OVERSOLD:
                return None
            # Impulse: current bar should not be a tiny doji
            if body < atr * 0.12 and setup_name != "EMA_PULLBACK":
                return None

        # =========================================================
        # L6 — RISK / EXITS
        # =========================================================
        be_distance = round(sl_distance * config.BE_TRIGGER_RR, 2)
        tp_distance = round(sl_distance * config.TP_RR_RATIO, 2)

        if bias == "LONG":
            sl_price = round(price - sl_distance, 2)
            tp1_price = round(price + be_distance, 2)  # BE arm level only
            tp2_price = round(price + tp_distance, 2)  # full TP
        else:
            sl_price = round(price + sl_distance, 2)
            tp1_price = round(price - be_distance, 2)
            tp2_price = round(price - tp_distance, 2)

        dollar_risk = account_balance * (config.RISK_PER_TRADE_PCT / 100.0)
        if dollar_risk < 0.40 and not force:
            return None

        size_oz = round(dollar_risk / sl_distance, 4)
        if size_oz < 0.01:
            size_oz = 0.01

        notional = price * size_oz
        required_margin = round(notional / config.MAX_LEVERAGE, 2)
        cap = account_balance * (config.MARGIN_CAP_PCT / 100.0)
        if required_margin > cap:
            size_oz = round((cap * config.MAX_LEVERAGE) / price, 4)
            if size_oz < 0.01:
                return None
            required_margin = round((price * size_oz) / config.MAX_LEVERAGE, 2)

        ts = current_time.isoformat()
        regime_txt = (
            f"h={utc_hour:02d}UTC spr=${spread:.2f} ADX={adx:.1f} "
            f"{'TREND' if is_trending else ('RANGE' if is_ranging else 'MID')}"
        )
        mom_txt = (
            f"ATR=${atr:.2f} RSI={rsi:.1f} DI+={plus_di:.1f} DI-={minus_di:.1f} "
            f"EMA21={ema_21:.1f} stack={'Y' if (stack_bull or stack_bear) else 'N'}"
        )

        plan: Dict[str, Any] = {
            "timestamp": ts,
            "symbol": config.SYMBOL,
            "direction": bias,
            "entry_price": round(price, 2),
            "sl_price": sl_price,
            "tp1_price": tp1_price,
            "tp2_price": tp2_price,
            "size_oz": size_oz,
            "leverage": config.MAX_LEVERAGE,
            "required_margin_usd": required_margin,
            "dollar_risk": round(size_oz * sl_distance, 2),
            "sl_distance": sl_distance,
            "setup_name": setup_name,
            "be_trigger_rr": config.BE_TRIGGER_RR,
            "tp_rr": config.TP_RR_RATIO,
            "trail_atr_mult": config.TRAIL_ATR_MULTIPLIER,
            "atr_at_entry": atr,
            "layer1_regime": regime_txt,
            "layer2_structure": f"[{setup_name}] {layer4_reason}",
            "layer3_momentum": mom_txt,
            "reason": f"[{setup_name}] {layer4_reason}",
            "status": "NEW",
            "strategy_version": config.STRATEGY_VERSION,
        }

        logger.info(
            "✨ v4 %s %s @ $%.2f | SL $%.2f | BE@$%.2f | TP $%.2f (%.1fR) | %.4f oz",
            setup_name,
            bias,
            price,
            sl_price,
            tp1_price,
            tp2_price,
            config.TP_RR_RATIO,
            size_oz,
        )
        return plan


engine = LayeredDecisionEngine()
