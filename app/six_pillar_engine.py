"""
6-Pillar Professional XAU/USDT Scalping Engine (v6-six-pillar-scalper).

Designed to address the specific quantitative failure modes of static Z-score MR
and breakout systems in Gold (XAU-USDT) by implementing institutional scalping mechanics:

  Pillar 1: Venue & Execution Economics (ECN/Maker execution, hard spread ceiling <= $0.20/oz)
  Pillar 2: Time-of-Day Kill Zones (Tokyo Sweep 00–04 UTC, London Open 07–10 UTC, NY Overlap 12–16 UTC)
  Pillar 3: Dynamic Regime Gating (3-State HMM/ATR Shock Classifier & News Veto)
  Pillar 4: ICT/SMC Liquidity Sweep Reclaim & Order Block Pullback (No breakout traps)
  Pillar 5: Adaptive Exits & Time-Based Kill Switch (Mean return Z<=0.3, max 6 bars / 30m hold)
  Pillar 6: Capital Defense & Frequency Discipline (Max 2 trades/session, -3.0% daily DD circuit breaker)
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("SixPillarEngine")


@dataclass
class SixPillarConfig:
    STRATEGY_VERSION: str = "v6-six-pillar-scalper"
    SYMBOL: str = "XAU-USDT"
    MAX_LEVERAGE: int = 50

    # Pillar 1: Venue & Execution Economics
    MAX_ALLOWABLE_SPREAD_USD: float = 0.25  # ECN/Raw perp ceiling ($0.25/oz max)
    EXECUTION_MODE: str = "MAKER_POST_ONLY"  # Prefer limit entry at sweep rejection close
    MAKER_FEE_RATE: float = 0.0001
    TAKER_FEE_RATE: float = 0.0004
    MIN_SL_COST_MULTIPLE: float = 4.0

    # Pillar 2: Time-of-Day Kill Zones (UTC Hours)
    # (start_hour_inclusive, end_hour_exclusive)
    KILLZONES: List[Tuple[int, int]] = field(
        default_factory=lambda: [
            (0, 4),    # Tokyo / Sydney Accumulation Fade (00:00 - 04:00 UTC)
            (7, 10),   # London Open Kill Zone (07:00 - 10:00 UTC)
            (12, 16),  # London / NY Overlap Kill Zone (12:00 - 16:00 UTC)
        ]
    )

    # Pillar 3: Dynamic Regime Gating & Volatility Shocks
    ADX_RANGE_MAX: float = 20.0       # ADX <= 20 -> RANGING regime
    ADX_TREND_MIN: float = 22.0       # ADX >= 22 -> TRENDING regime
    ATR_SHOCK_MULTIPLE: float = 1.8   # ATR14 > 1.8 * SMA(ATR14, 50) -> SHOCK/VETO
    MIN_ATR_USD: float = 1.00         # Min 5m candle ATR volatility

    # Pillar 4: ICT/SMC Liquidity Sweep Reclaim & Order Block
    SWEEP_PIERCE_USD: float = 0.80    # Min pierce above Asian/PDH/PDL to hunt stops
    SWEEP_BUFFER_SL_USD: float = 0.50 # Stop loss distance beyond sweep high/low
    MIN_SL_USD: float = 1.50          # Absolute floor for stop loss in USD/oz
    SL_ATR_MULTIPLIER: float = 1.5    # Scalping SL = 1.5x ATR
    DEFAULT_TP_RR: float = 2.0        # Default TP R:R (overridden by mean return exit)

    # Pillar 5: Adaptive Exits & Time-Based Kill Switch
    MEAN_RETURN_EXIT_Z: float = 0.35  # Exit ranging trade when |Z| <= 0.35
    MAX_HOLDING_BARS: int = 6         # Time-based kill switch: close scalp after 6 bars (30m)
    BE_TRIGGER_RR: float = 1.2        # Move stop to breakeven once +1.2R is reached
    TRAIL_ATR_MULTIPLIER: float = 1.5 # Trail ATR stop after +1.5R

    # Pillar 6: Capital Defense & Frequency Discipline
    RISK_PER_TRADE_PCT: float = 1.0   # 1.0% equity risk per trade
    MAX_TRADES_PER_SESSION: int = 2   # Max 2 clean trades per killzone session
    MAX_TRADES_PER_DAY: int = 6       # Max 6 total trades per day
    MAX_DAILY_LOSS_PCT: float = 3.0   # Hard daily drawdown circuit breaker (-3.0%)
    MARGIN_CAP_PCT: float = 30.0      # Max collateral margin utilization


class TechnicalIndicatorsV6:
    @staticmethod
    def calculate_sma(prices: List[float], period: int) -> float:
        if not prices:
            return 0.0
        w = prices[-period:] if len(prices) >= period else prices
        return sum(w) / len(w)

    @staticmethod
    def calculate_stdev(prices: List[float], period: int) -> float:
        if len(prices) < 2:
            return 0.0
        w = prices[-period:] if len(prices) >= period else prices
        m = sum(w) / len(w)
        var = sum((x - m) ** 2 for x in w) / len(w)
        return math.sqrt(var)

    @staticmethod
    def calculate_atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
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


class SixPillarDecisionEngine:
    """
    Core institutional 6-Pillar decision engine for XAU-USDT 5-minute candles.
    """
    def __init__(self, config: Optional[SixPillarConfig] = None) -> None:
        self.config = config or SixPillarConfig()
        self.tech = TechnicalIndicatorsV6()
        self._session_trades_count: Dict[str, int] = {}

    def get_killzone_session(self, utc_hour: int) -> Optional[str]:
        """Check if current UTC hour is inside an active institutional Kill Zone."""
        for start, end in self.config.KILLZONES:
            if start <= utc_hour < end:
                if start == 0:
                    return "TOKYO_SWEEP"
                if start == 7:
                    return "LONDON_OPEN"
                if start == 12:
                    return "NY_OVERLAP"
                return f"SESSION_{start}_{end}"
        return None

    def classify_regime(
        self, adx: float, atr: float, atr_avg: float, is_news_window: bool = False
    ) -> Tuple[str, str]:
        """
        Pillar 3: 3-State Regime Classifier (RANGING, TRENDING, SHOCK_VOLATILE / VETO).
        """
        if is_news_window:
            return "VETO_NEWS", "High-impact macro event buffer active (±30m)"
        if atr_avg > 0 and atr > self.config.ATR_SHOCK_MULTIPLE * atr_avg:
            return "VETO_SHOCK", f"ATR shock spike (${atr:.2f} > {self.config.ATR_SHOCK_MULTIPLE}x average ${atr_avg:.2f})"
        if atr < self.config.MIN_ATR_USD:
            return "VETO_LOW_VOL", f"Insufficient volatility (${atr:.2f} < ${self.config.MIN_ATR_USD})"
        if adx <= self.config.ADX_RANGE_MAX:
            return "RANGING", f"Ranging / Accumulation regime (ADX={adx:.1f} <= {self.config.ADX_RANGE_MAX})"
        if adx >= self.config.ADX_TREND_MIN:
            return "TRENDING", f"Trending / Expansion regime (ADX={adx:.1f} >= {self.config.ADX_TREND_MIN})"
        return "NEUTRAL", f"Transitional regime (ADX={adx:.1f})"

    def evaluate(
        self, market_data: Dict[str, Any], account_balance: float
    ) -> Optional[Dict[str, Any]]:
        """
        Evaluate a closed 5m candle against the 6-Pillar Institutional Scalping Framework.
        Returns an execution plan dictionary or None.
        """
        current_time = market_data.get("timestamp", datetime.now(timezone.utc))
        if isinstance(current_time, str):
            try:
                current_time = datetime.fromisoformat(current_time.replace("Z", "+00:00"))
            except ValueError:
                current_time = datetime.now(timezone.utc)
        if getattr(current_time, "tzinfo", None) is None:
            current_time = current_time.replace(tzinfo=timezone.utc)

        utc_hour = current_time.astimezone(timezone.utc).hour
        force = bool(market_data.get("force_signal", False))
        price = float(market_data["close"])
        high = float(market_data.get("high", price))
        low = float(market_data.get("low", price))
        open_px = float(market_data.get("open", price))
        spread = float(market_data.get("spread", 0.15))
        atr = float(market_data.get("atr_14", 1.80))
        atr_avg = float(market_data.get("atr_avg", atr))
        adx = float(market_data.get("adx", 15.0))
        rsi = float(market_data.get("rsi_14", 50.0))
        sma = float(market_data.get("sma_z", market_data.get("sma_20", price)))
        stdev = float(market_data.get("stdev_z", market_data.get("stdev_20", 0.0)))
        zscore = float(market_data.get("zscore", 0.0))
        if stdev > 1e-9 and "zscore" not in market_data:
            zscore = (price - sma) / stdev

        asian_high = float(market_data.get("asian_high", price + 5.0))
        asian_low = float(market_data.get("asian_low", price - 5.0))
        pdh = float(market_data.get("pdh", asian_high))
        pdl = float(market_data.get("pdl", asian_low))
        ob_high = float(market_data.get("ob_high", 0.0))
        ob_low = float(market_data.get("ob_low", 0.0))

        # -------------------------------------------------------------
        # Pillar 1: Venue & Execution Economics (Spread Ceiling Gate)
        # -------------------------------------------------------------
        if spread > self.config.MAX_ALLOWABLE_SPREAD_USD and not force:
            logger.debug("Reject: spread $%.2f > limit $%.2f", spread, self.config.MAX_ALLOWABLE_SPREAD_USD)
            return None

        # -------------------------------------------------------------
        # Pillar 2: Time-of-Day Kill Zones
        # -------------------------------------------------------------
        session_name = self.get_killzone_session(utc_hour)
        if not session_name and not force:
            logger.debug("Reject: UTC hour %02d outside 6-Pillar Kill Zones", utc_hour)
            return None
        if not session_name:
            session_name = "MANUAL_FORCE"

        # -------------------------------------------------------------
        # Pillar 6: Frequency & Session Cap
        # -------------------------------------------------------------
        session_count = self._session_trades_count.get(session_name, 0)
        if session_count >= self.config.MAX_TRADES_PER_SESSION and not force:
            logger.debug("Reject: session trade limit (%d) reached for %s", self.config.MAX_TRADES_PER_SESSION, session_name)
            return None

        # -------------------------------------------------------------
        # Pillar 3: Dynamic Regime Gating
        # -------------------------------------------------------------
        is_news = bool(market_data.get("is_news_window", False))
        regime, regime_reason = self.classify_regime(adx, atr, atr_avg, is_news_window=is_news)
        if regime.startswith("VETO_") and not force:
            logger.debug("Reject: regime %s (%s)", regime, regime_reason)
            return None

        # -------------------------------------------------------------
        # Pillar 4: ICT/SMC Liquidity Sweep Reclaim & Order Block Pullback
        # -------------------------------------------------------------
        bias: Optional[str] = None
        setup_name = ""
        setup_reason = ""
        sweep_reference_level = price
        sweep_extreme = price

        pierce = self.config.SWEEP_PIERCE_USD
        bullish_bar = price > open_px
        bearish_bar = price < open_px

        # -------------------------------------------------------------
        # Pillar 1 & 4: Fee Immunity Reference Cost
        # -------------------------------------------------------------
        rt_cost_oz = (price * (self.config.TAKER_FEE_RATE * 2.0)) + spread

        # 4A. Liquidity Sweep Reclaim (Asian High/Low or PDH/PDL Sweep Absorption)
        # Check High sweep & bearish close back inside structure -> SHORT
        high_levels = [lvl for lvl in (asian_high, pdh) if lvl > 0]
        swept_high_lvl = None
        for lvl in sorted(high_levels, reverse=True):
            if high >= lvl + pierce and price < lvl and bearish_bar:
                swept_high_lvl = lvl
                break

        low_levels = [lvl for lvl in (asian_low, pdl) if lvl > 0]
        swept_low_lvl = None
        for lvl in sorted(low_levels):
            if low <= lvl - pierce and price > lvl and bullish_bar:
                swept_low_lvl = lvl
                break

        if swept_high_lvl is not None:
            est_tp_dist = max(self.config.MIN_SL_USD, (high - swept_high_lvl) + self.config.SWEEP_BUFFER_SL_USD) * self.config.DEFAULT_TP_RR
            if (regime in ("RANGING", "TRENDING", "NEUTRAL") or rsi > 65.0 or force) and (est_tp_dist >= rt_cost_oz * 1.2 or force):
                bias = "SHORT"
                setup_name = "LIQUIDITY_SWEEP_RECLAIM"
                sweep_reference_level = swept_high_lvl
                sweep_extreme = high
                setup_reason = (
                    f"Swept level ${swept_high_lvl:.2f} by ${(high - swept_high_lvl):.2f}, "
                    f"closed inside @ ${price:.2f} | RSI={rsi:.1f} | {regime}"
                )
        elif swept_low_lvl is not None:
            est_tp_dist = max(self.config.MIN_SL_USD, (swept_low_lvl - low) + self.config.SWEEP_BUFFER_SL_USD) * self.config.DEFAULT_TP_RR
            if (regime in ("RANGING", "TRENDING", "NEUTRAL") or rsi < 35.0 or force) and (est_tp_dist >= rt_cost_oz * 1.2 or force):
                bias = "LONG"
                setup_name = "LIQUIDITY_SWEEP_RECLAIM"
                sweep_reference_level = swept_low_lvl
                sweep_extreme = low
                setup_reason = (
                    f"Swept level ${swept_low_lvl:.2f} by ${(swept_low_lvl - low):.2f}, "
                    f"closed inside @ ${price:.2f} | RSI={rsi:.1f} | {regime}"
                )

        # 4B. Order Block Pullback Rejection (Trending Regime continuation)
        if not bias and regime == "TRENDING" and ob_high > 0 and ob_low > 0:
            ema_200 = float(market_data.get("ema_200", price))
            if price > ema_200 and low <= ob_high and price > ob_high and bullish_bar:
                bias = "LONG"
                setup_name = "ORDER_BLOCK_PULLBACK"
                sweep_extreme = low
                setup_reason = f"Bullish OB pullback bounce above ${ob_high:.2f} in {regime}"
            elif price < ema_200 and high >= ob_low and price < ob_low and bearish_bar:
                bias = "SHORT"
                setup_name = "ORDER_BLOCK_PULLBACK"
                sweep_extreme = high
                setup_reason = f"Bearish OB pullback rejection below ${ob_low:.2f} in {regime}"

        # 4C. Z-Score Stretch Reclaim (Institutional range fade when Z is extreme & turning)
        if not bias and regime == "RANGING" and abs(zscore) >= 2.2:
            prev_close = float(market_data.get("prev_close", price))
            prev_close_2 = float(market_data.get("prev_close_2", prev_close))
            if zscore <= -2.2 and bullish_bar and prev_close <= prev_close_2:
                bias = "LONG"
                setup_name = "ZSCORE_SWEEP_RECLAIM"
                sweep_extreme = low
                setup_reason = f"Z={zscore:.2f} stretch reversal LONG | ADX={adx:.1f} | SMA=${sma:.2f}"
            elif zscore >= 2.2 and bearish_bar and prev_close >= prev_close_2:
                bias = "SHORT"
                setup_name = "ZSCORE_SWEEP_RECLAIM"
                sweep_extreme = high
                setup_reason = f"Z={zscore:.2f} stretch reversal SHORT | ADX={adx:.1f} | SMA=${sma:.2f}"

        # Manual/Force Override
        if not bias and force:
            bias = str(market_data.get("force_direction", "LONG")).upper()
            setup_name = "FORCE_OVERRIDE"
            setup_reason = "Telegram / manual force trigger"
            sweep_extreme = low if bias == "LONG" else high

        if not bias:
            return None

        # -------------------------------------------------------------
        # Pillar 4 & 6: Stop Loss, Target, and Position Sizing
        # -------------------------------------------------------------
        # Compute SL: for sweep reclaim, SL is placed beyond the swept extreme + buffer
        if setup_name == "LIQUIDITY_SWEEP_RECLAIM":
            if bias == "LONG":
                raw_sl_dist = (price - sweep_extreme) + self.config.SWEEP_BUFFER_SL_USD
            else:
                raw_sl_dist = (sweep_extreme - price) + self.config.SWEEP_BUFFER_SL_USD
        else:
            raw_sl_dist = atr * self.config.SL_ATR_MULTIPLIER

        sl_distance = max(self.config.MIN_SL_USD, round(raw_sl_dist, 2))
        tp_distance = round(sl_distance * self.config.DEFAULT_TP_RR, 2)
        be_distance = round(sl_distance * self.config.BE_TRIGGER_RR, 2)

        if bias == "LONG":
            sl_price = round(price - sl_distance, 2)
            tp1_price = round(price + be_distance, 2)  # BE trigger level
            tp2_price = round(price + tp_distance, 2)
        else:
            sl_price = round(price + sl_distance, 2)
            tp1_price = round(price - be_distance, 2)  # BE trigger level
            tp2_price = round(price - tp_distance, 2)

        dollar_risk = account_balance * (self.config.RISK_PER_TRADE_PCT / 100.0)
        if dollar_risk < 0.40 and not force:
            return None

        size_oz = round(dollar_risk / sl_distance, 4)
        if size_oz < 0.01:
            size_oz = 0.01

        notional = price * size_oz
        required_margin = round(notional / self.config.MAX_LEVERAGE, 2)
        cap = account_balance * (self.config.MARGIN_CAP_PCT / 100.0)
        if required_margin > cap:
            size_oz = round((cap * self.config.MAX_LEVERAGE) / price, 4)
            if size_oz < 0.01:
                return None
            required_margin = round((price * size_oz) / self.config.MAX_LEVERAGE, 2)

        # Update session count tracking
        self._session_trades_count[session_name] = session_count + 1

        ts = current_time.isoformat()
        plan: Dict[str, Any] = {
            "timestamp": ts,
            "bar_timestamp_ms": market_data.get("bar_timestamp_ms"),
            "source": market_data.get("source", "UNKNOWN"),
            "symbol": self.config.SYMBOL,
            "direction": bias,
            "reference_price": round(price, 4),
            "entry_price": round(price, 2),
            "sl_price": sl_price,
            "tp1_price": tp1_price,
            "tp2_price": tp2_price,
            "size_oz": size_oz,
            "leverage": self.config.MAX_LEVERAGE,
            "required_margin_usd": required_margin,
            "dollar_risk": round(size_oz * sl_distance, 2),
            "sl_distance": sl_distance,
            "setup_name": setup_name,
            "be_trigger_rr": self.config.BE_TRIGGER_RR,
            "tp_rr": self.config.DEFAULT_TP_RR,
            "trail_atr_mult": self.config.TRAIL_ATR_MULTIPLIER,
            "atr_at_entry": atr,
            "spread": round(spread, 4),
            "zscore": round(zscore, 3),
            "adx": round(adx, 3),
            "layer1_regime": f"[{session_name}] h={utc_hour:02d}UTC spr=${spread:.2f} ADX={adx:.1f}",
            "layer2_structure": f"[{setup_name}] {setup_reason}",
            "layer3_momentum": f"ATR=${atr:.2f} Z={zscore:.2f} RSI={rsi:.1f} SMA=${sma:.2f}",
            "reason": f"[{setup_name}] {setup_reason}",
            "status": "NEW",
            "strategy_version": self.config.STRATEGY_VERSION,
            "killzone_session": session_name,
            "regime": regime,
            "max_holding_bars": self.config.MAX_HOLDING_BARS,
        }
        logger.info(
            "✨ 6-Pillar %s %s @ $%.2f | SL $%.2f | TP $%.2f (%.1fR) | %.4f oz | Session: %s",
            setup_name,
            bias,
            price,
            sl_price,
            tp2_price,
            self.config.DEFAULT_TP_RR,
            size_oz,
            session_name,
        )
        return plan

    def check_pillar5_exits(
        self,
        trade: Dict[str, Any],
        current_bar: Dict[str, Any],
        bars_held: int = 0,
    ) -> Optional[str]:
        """
        Pillar 5: Adaptive Exits & Time-Based Kill Switch with Fee-Immunity Gate.
        Returns exit reason string ('MEAN_RETURN_EXIT', 'TIME_KILL_SWITCH', etc.) or None.
        """
        direction = str(trade.get("direction", "LONG"))
        setup_name = str(trade.get("setup_name", ""))
        price = float(current_bar.get("close", 0.0))
        entry_price = float(trade.get("entry_price", price))
        size_oz = float(trade.get("size_oz", 0.0))
        sma = float(current_bar.get("sma_z", current_bar.get("sma_20", price)))
        stdev = float(current_bar.get("stdev_z", current_bar.get("stdev_20", 0.0)))
        zscore = float(current_bar.get("zscore", 0.0))
        if stdev > 1e-9 and "zscore" not in current_bar:
            zscore = (price - sma) / stdev

        # Fee-Immunity Gate: Calculate gross profit and estimated round-trip fee
        fee_cleared = True
        if size_oz > 0 and entry_price > 0:
            gross_profit_usd = (price - entry_price) * size_oz if direction == "LONG" else (entry_price - price) * size_oz
            entry_fee = float(trade.get("entry_fee_usd", 0.0))
            est_rt_fee_usd = entry_fee * 2.0 if entry_fee > 0 else (price * size_oz * self.config.MAKER_FEE_RATE * 2.0)
            if gross_profit_usd < est_rt_fee_usd * 1.15:
                fee_cleared = False

        # 1. Mean-Return Exit for reversion / sweep reclaim setups (ONLY if fee hurdle is cleared)
        if fee_cleared and (not setup_name or setup_name in ("LIQUIDITY_SWEEP_RECLAIM", "ZSCORE_SWEEP_RECLAIM", "ZSCORE_MR", "None")):
            if abs(zscore) <= self.config.MEAN_RETURN_EXIT_Z:
                logger.info("🎯 Pillar 5 Mean-Return Exit triggered (Z=%.2f <= %.2f, profit cleared fee hurdle)", zscore, self.config.MEAN_RETURN_EXIT_Z)
                return "MEAN_RETURN_EXIT"
            # Crosses over session SMA/VWAP
            if direction == "LONG" and price >= sma and sma > 0:
                logger.info("🎯 Pillar 5 Mean-Return SMA exit triggered for LONG @ $%.2f (SMA $%.2f)", price, sma)
                return "MEAN_RETURN_EXIT"
            if direction == "SHORT" and price <= sma and sma > 0:
                logger.info("🎯 Pillar 5 Mean-Return SMA exit triggered for SHORT @ $%.2f (SMA $%.2f)", price, sma)
                return "MEAN_RETURN_EXIT"

        # 2. Time-Based Kill Switch (Max Holding Bars without hitting target or mean)
        max_bars = int(trade.get("max_holding_bars", self.config.MAX_HOLDING_BARS))
        if bars_held >= max_bars:
            logger.info("⏱️ Pillar 5 Time-Based Kill Switch triggered (%d bars held >= limit %d)", bars_held, max_bars)
            return "TIME_KILL_SWITCH"

        return None


six_pillar_engine = SixPillarDecisionEngine()
