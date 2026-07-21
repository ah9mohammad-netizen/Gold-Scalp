"""
Quantitative Layered Decision Engine for XAU-USDT Scalping & Breakouts.
Evaluates Session/Spread -> Structural Breakout/Sweep -> Volatility/Momentum -> Dynamic Risk ($100 sizing).
"""
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any
from app.config import config

logger = logging.getLogger("DecisionEngine")

class TechnicalIndicators:
    @staticmethod
    def calculate_ema(prices: List[float], period: int) -> float:
        if len(prices) < period:
            return prices[-1] if prices else 0.0
        multiplier = 2 / (period + 1)
        ema = sum(prices[:period]) / period
        for price in prices[period:]:
            ema = (price - ema) * multiplier + ema
        return ema

    @staticmethod
    def calculate_atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
        if len(highs) < period + 1:
            return 1.80  # Default fallback ATR for XAU-USDT ($1.80/oz)
        trs = []
        for i in range(1, len(closes)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1])
            )
            trs.append(tr)
        if len(trs) < period:
            return sum(trs) / len(trs) if trs else 1.80
        atr = sum(trs[:period]) / period
        for tr in trs[period:]:
            atr = (atr * (period - 1) + tr) / period
        return atr

    @staticmethod
    def calculate_rsi(closes: List[float], period: int = 14) -> float:
        if len(closes) < period + 1:
            return 50.0
        gains, losses = [], []
        for i in range(1, len(closes)):
            change = closes[i] - closes[i - 1]
            if change > 0:
                gains.append(change)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(change))
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))


class LayeredDecisionEngine:
    """
    Evaluates market conditions across 4 structural tiers:
    1. Regime & Session Filter (UTC windows, spread ceiling)
    2. Structural Liquidity (Asian high/low sweeps, VWAP & 200 EMA alignment)
    3. Momentum & Volatility (ATR check, RSI check)
    4. Dynamic Risk & Sizing (Risk dollars / SL distance -> Margin validation for $100 account)
    """
    def __init__(self):
        self.tech = TechnicalIndicators()

    def evaluate(self, market_data: Dict[str, Any], account_balance: float) -> Optional[Dict[str, Any]]:
        """
        Runs the full decision engine. Returns a complete trading plan if all layers pass.
        """
        current_time = market_data.get("timestamp", datetime.now(timezone.utc))
        price = market_data["close"]
        spread = market_data["spread"]
        atr = market_data["atr_14"]
        rsi = market_data["rsi_14"]
        ema_200 = market_data["ema_200"]
        vwap = market_data["vwap"]
        asian_high = market_data["asian_high"]
        asian_low = market_data["asian_low"]
        high = market_data["high"]
        low = market_data["low"]

        # -------------------------------------------------------------
        # LAYER 1: REGIME & SESSION WINDOWS
        # -------------------------------------------------------------
        current_utc_hour = current_time.astimezone(timezone.utc).hour
        session_valid = any(start <= current_utc_hour < end for start, end in config.ALLOWED_SESSIONS)
        
        # In simulated/test mode or if spread is acceptable
        if not session_valid and not market_data.get("force_signal", False):
            logger.debug(f"Layer 1 Skipped: Outside active session ({current_utc_hour}:00 UTC)")
            return None
            
        if spread > config.MAX_ALLOWABLE_SPREAD_USD:
            logger.warning(f"Layer 1 Skipped: Spread ${spread:.2f} exceeds limit ${config.MAX_ALLOWABLE_SPREAD_USD:.2f}")
            return None

        # -------------------------------------------------------------
        # LAYER 2: STRUCTURAL LIQUIDITY & ORDER FLOW ALIGNMENT
        # -------------------------------------------------------------
        trend_bullish = price > ema_200
        trend_bearish = price < ema_200
        bias = None
        layer2_reason = ""

        # Check Asian High sweep & bearish rejection
        if high >= asian_high and price < asian_high and trend_bearish:
            bias = "SHORT"
            layer2_reason = f"Asian High Sweep Rejection (${high:.2f} >= ${asian_high:.2f}) + Bearish EMA"
        # Check Asian Low sweep & bullish rejection
        elif low <= asian_low and price > asian_low and trend_bullish:
            bias = "LONG"
            layer2_reason = f"Asian Low Sweep Rejection (${low:.2f} <= ${asian_low:.2f}) + Bullish EMA"
        # Check London Momentum Breakout Long
        elif trend_bullish and price > vwap and price > asian_high:
            bias = "LONG"
            layer2_reason = f"London Breakout above Asian High (${asian_high:.2f}) & VWAP"
        # Check London Momentum Breakout Short
        elif trend_bearish and price < vwap and price < asian_low:
            bias = "SHORT"
            layer2_reason = f"London Breakout below Asian Low (${asian_low:.2f}) & VWAP"
        elif market_data.get("force_signal", False):
            # Allow force_signal for testing / Telegram override
            bias = market_data.get("force_direction", "LONG")
            layer2_reason = "Manual / Override Structural Trigger"

        if not bias:
            return None

        # -------------------------------------------------------------
        # LAYER 3: MOMENTUM & VOLATILITY CONFIRMATION
        # -------------------------------------------------------------
        if atr < 1.00:
            logger.debug(f"Layer 3 Skipped: ATR ${atr:.2f} below $1.00 minimum")
            return None

        if bias == "LONG" and rsi > config.RSI_OVERBOUGHT:
            logger.debug(f"Layer 3 Skipped: RSI {rsi:.1f} overbought for LONG")
            return None
        if bias == "SHORT" and rsi < config.RSI_OVERSOLD:
            logger.debug(f"Layer 3 Skipped: RSI {rsi:.1f} oversold for SHORT")
            return None

        # -------------------------------------------------------------
        # LAYER 4: DYNAMIC RISK ENGINE & EXACT $100 SIZING
        # -------------------------------------------------------------
        sl_distance = round(atr * config.SL_ATR_MULTIPLIER, 2)
        if sl_distance < 1.00:
            sl_distance = 1.00  # Minimum $1.00 stop loss on XAU-USDT

        if bias == "LONG":
            sl_price = round(price - sl_distance, 2)
            tp1_price = round(price + (sl_distance * config.TP1_RR_RATIO), 2)
            tp2_price = round(price + (sl_distance * config.TP2_RR_RATIO), 2)
        else:  # SHORT
            sl_price = round(price + sl_distance, 2)
            tp1_price = round(price - (sl_distance * config.TP1_RR_RATIO), 2)
            tp2_price = round(price - (sl_distance * config.TP2_RR_RATIO), 2)

        # Dollar risk calculation based on risk % (e.g. 1.5% of $100 = $1.50)
        dollar_risk = account_balance * (config.RISK_PER_TRADE_PCT / 100.0)
        if dollar_risk < 1.00:
            dollar_risk = 1.50  # Ensure meaningful entry size when account is near $100

        # Exact contract size (troy ounces / units on crypto perps)
        size_oz = round(dollar_risk / sl_distance, 4)
        if size_oz < 0.01:
            size_oz = 0.01  # Minimum contract size on Bybit/Binance XAU-USDT

        # Check required margin at max leverage
        notional_value_usd = price * size_oz
        required_margin_usd = round(notional_value_usd / config.MAX_LEVERAGE, 2)

        if required_margin_usd > account_balance * 0.40:
            # Scale down if required margin exceeds 40% of available capital
            max_safe_margin = account_balance * 0.40
            size_oz = round((max_safe_margin * config.MAX_LEVERAGE) / price, 4)
            required_margin_usd = round((price * size_oz) / config.MAX_LEVERAGE, 2)

        trade_plan = {
            "timestamp": current_time.isoformat(),
            "symbol": config.SYMBOL,
            "direction": bias,
            "entry_price": price,
            "sl_price": sl_price,
            "tp1_price": tp1_price,
            "tp2_price": tp2_price,
            "size_oz": size_oz,
            "leverage": config.MAX_LEVERAGE,
            "required_margin_usd": required_margin_usd,
            "dollar_risk": round(size_oz * sl_distance, 2),
            "sl_distance": sl_distance,
            "layer1_regime": f"Active Session (Spread: ${spread:.2f})",
            "layer2_structure": layer2_reason,
            "layer3_momentum": f"Confirmed (ATR: ${atr:.2f}, RSI: {rsi:.1f})",
            "status": "NEW"
        }

        logger.info(f"✨ Valid {bias} Signal Generated on {config.SYMBOL} at ${price:.2f}")
        return trade_plan

engine = LayeredDecisionEngine()
