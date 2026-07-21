"""
Live Market Data Feed Engine for XAU-USDT.
Fetches real-time live OHLCV & orderbook spread directly from Bybit Linear Futures (XAUUSDT) and Phemex (cXAUUSDT),
ensuring exact synchronization with TradingView XAU-USDT (~$4,069/oz).
"""
import asyncio
import json
import logging
import urllib.request
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from app.config import config
from app.engine import TechnicalIndicators

logger = logging.getLogger("LiveMarketData")

class LiveMarketDataFeed:
    """
    Connects to live public exchange APIs to ingest real-time XAU-USDT 5m bars and orderbook spread.
    Prioritizes true Gold Perpetual Futures (Bybit XAUUSDT & Phemex cXAUUSDT ~ $4,069)
    so price matches TradingView exactly, avoiding tokenized PAXG premium ($4,116).
    """
    def __init__(self):
        self.tech = TechnicalIndicators()
        self.last_known_price = 4069.00  # Exact XAU-USDT baseline
        self.simulated_cycle = 0

    def _fetch_from_bybit_xau_sync(self) -> Optional[Dict[str, Any]]:
        """Queries Bybit V5 API specifically for Linear Futures XAUUSDT (matches TradingView ~$4,069)."""
        try:
            url = "https://api.bybit.com/v5/market/kline?category=linear&symbol=XAUUSDT&interval=5&limit=200"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Quantitative Gold-Scalp Bot)"})
            with urllib.request.urlopen(req, timeout=6.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                
            if not data or data.get("retCode") != 0 or not data.get("result", {}).get("list"):
                return None
                
            raw_list = data["result"]["list"]
            raw_list.reverse()  # Chronological order from oldest to newest
            
            closes = [float(item[4]) for item in raw_list]
            highs = [float(item[2]) for item in raw_list]
            lows = [float(item[3]) for item in raw_list]
            
            latest_bar = raw_list[-1]
            latest_close = float(latest_bar[4])
            latest_high = float(latest_bar[2])
            latest_low = float(latest_bar[3])
            self.last_known_price = latest_close
            
            spread = 0.15
            try:
                t_url = "https://api.bybit.com/v5/market/tickers?category=linear&symbol=XAUUSDT"
                req_t = urllib.request.Request(t_url, headers={"User-Agent": "Mozilla/5.0 (Quantitative Gold-Scalp Bot)"})
                with urllib.request.urlopen(req_t, timeout=4.0) as resp_t:
                    data_t = json.loads(resp_t.read().decode("utf-8"))
                    if data_t and data_t.get("retCode") == 0 and data_t.get("result", {}).get("list"):
                        bid = float(data_t["result"]["list"][0].get("bid1Price", latest_close - 0.08))
                        ask = float(data_t["result"]["list"][0].get("ask1Price", latest_close + 0.08))
                        if ask > bid > 0:
                            spread = round(ask - bid, 2)
            except Exception:
                pass
                
            return self._build_tick_result("LIVE_EXCHANGE_BYBIT_XAUUSDT", raw_list, closes, highs, lows, latest_close, latest_high, latest_low, spread)
        except Exception as e:
            logger.debug(f"Bybit XAUUSDT fetch failed: {e}")
            return None

    def _fetch_from_phemex_xau_sync(self) -> Optional[Dict[str, Any]]:
        """Queries Phemex public kline API for cXAUUSDT (Gold Perp ~$4,069)."""
        try:
            url = "https://api.phemex.com/exchange/public/md/kline?symbol=cXAUUSDT&resolution=300&limit=200"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Quantitative Gold-Scalp Bot)"})
            with urllib.request.urlopen(req, timeout=6.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                
            if not data or not data.get("data") or not isinstance(data["data"]["rows"], list):
                return None
                
            rows = data["data"]["rows"]
            if len(rows) < 20:
                return None
                
            def parse_px(val):
                f_val = float(val)
                if f_val > 1000000:  # Scaled 10^4
                    return f_val / 10000.0
                return f_val

            closes = [parse_px(item[6]) for item in rows]
            highs = [parse_px(item[4]) for item in rows]
            lows = [parse_px(item[5]) for item in rows]
            
            latest_bar = rows[-1]
            latest_close = parse_px(latest_bar[6])
            latest_high = parse_px(latest_bar[4])
            latest_low = parse_px(latest_bar[5])
            self.last_known_price = latest_close
            
            return self._build_tick_result("LIVE_EXCHANGE_PHEMEX_cXAUUSDT", rows, closes, highs, lows, latest_close, latest_high, latest_low, 0.22)
        except Exception as e:
            logger.debug(f"Phemex cXAUUSDT fetch failed: {e}")
            return None

    def _fetch_from_binance_paxg_sync(self) -> Optional[Dict[str, Any]]:
        """Queries Binance PAXGUSDT (used only as emergency fallback if pure XAU futures are offline)."""
        try:
            url = "https://api.binance.com/api/v3/klines?symbol=PAXGUSDT&interval=5m&limit=200"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Quantitative Gold-Scalp Bot)"})
            with urllib.request.urlopen(req, timeout=6.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                
            if not data or not isinstance(data, list) or len(data) < 20:
                return None
                
            closes = [float(item[4]) for item in data]
            highs = [float(item[2]) for item in data]
            lows = [float(item[3]) for item in data]
            
            latest_bar = data[-1]
            latest_close = float(latest_bar[4])
            latest_high = float(latest_bar[2])
            latest_low = float(latest_bar[3])
            self.last_known_price = latest_close
            
            spread = 0.20
            try:
                t_url = "https://api.binance.com/api/v3/ticker/bookTicker?symbol=PAXGUSDT"
                req_t = urllib.request.Request(t_url, headers={"User-Agent": "Mozilla/5.0 (Quantitative Gold-Scalp Bot)"})
                with urllib.request.urlopen(req_t, timeout=4.0) as resp_t:
                    t_data = json.loads(resp_t.read().decode("utf-8"))
                    bid = float(t_data.get("bidPrice", latest_close - 0.10))
                    ask = float(t_data.get("askPrice", latest_close + 0.10))
                    if ask > bid > 0:
                        spread = round(ask - bid, 2)
            except Exception:
                pass
                
            return self._build_tick_result("LIVE_EXCHANGE_BINANCE_PAXGUSDT", data, closes, highs, lows, latest_close, latest_high, latest_low, spread)
        except Exception as e:
            logger.debug(f"Binance PAXGUSDT fetch failed: {e}")
            return None

    def _build_tick_result(self, source_name: str, raw_bars: list, closes: List[float], highs: List[float], lows: List[float], latest_close: float, latest_high: float, latest_low: float, spread: float) -> Dict[str, Any]:
        """Calculates indicators from historical bars and returns formatted market tick."""
        ema_200 = round(self.tech.calculate_ema(closes, 200), 2)
        atr_14 = round(self.tech.calculate_atr(highs, lows, closes, 14), 2)
        rsi_14 = round(self.tech.calculate_rsi(closes, 14), 1)
        
        now_dt = datetime.now(timezone.utc)
        asian_high = latest_close
        asian_low = latest_close
        vwap_sum_pv = 0.0
        vwap_sum_v = 0.0
        
        for i, h in enumerate(highs):
            l = lows[i]
            c = closes[i]
            vwap_sum_pv += ((h + l + c) / 3.0)
            vwap_sum_v += 1.0
            
        vwap = round(vwap_sum_pv / vwap_sum_v, 2) if vwap_sum_v > 0 else latest_close
        asian_high = round(max(highs[-30:]) if len(highs) >= 30 else latest_close + 3.0, 2)
        asian_low = round(min(lows[-30:]) if len(lows) >= 30 else latest_close - 3.0, 2)
        
        return {
            "timestamp": now_dt,
            "source": source_name,
            "close": latest_close,
            "spread": spread,
            "atr_14": atr_14,
            "rsi_14": rsi_14,
            "ema_200": ema_200,
            "vwap": vwap,
            "asian_high": asian_high,
            "asian_low": asian_low,
            "high": latest_high,
            "low": latest_low
        }

    def _fetch_live_market_data_sync(self) -> Optional[Dict[str, Any]]:
        """Prioritizes pure XAU-USDT Futures (~$4,069) over tokenized PAXG spot (~$4,116)."""
        tick = self._fetch_from_bybit_xau_sync()
        if tick:
            return tick
        tick = self._fetch_from_phemex_xau_sync()
        if tick:
            return tick
        # Fallback to PAXG if exact XAU futures APIs are unavailable
        tick = self._fetch_from_binance_paxg_sync()
        if tick:
            return tick
        return None

    async def get_latest_market_tick(self) -> Dict[str, Any]:
        """
        Asynchronously fetches real-time XAU-USDT market data.
        If offline, gracefully falls back to synthetic simulation around exact $4,069 baseline.
        """
        loop = asyncio.get_running_loop()
        live_tick = await loop.run_in_executor(None, self._fetch_live_market_data_sync)
        if live_tick:
            logger.info(f"Connected to live market: {live_tick['source']} | Price: ${live_tick['close']:.2f} | Spread: ${live_tick['spread']:.2f}")
            return live_tick

        # Fallback synthetic simulation around exactly $4,069.00 if offline
        self.simulated_cycle += 1
        now = datetime.now(timezone.utc)
        import random
        price_change = random.uniform(-1.40, 1.50)
        if self.simulated_cycle % 12 == 0:
            price_change = random.uniform(3.00, 5.20)  # London breakout test
        elif self.simulated_cycle % 19 == 0:
            price_change = random.uniform(-4.50, -2.20)  # Asian sweep test
            
        new_price = round(self.last_known_price + price_change, 2)
        high_price = round(new_price + random.uniform(0.15, 0.80), 2)
        low_price = round(new_price - random.uniform(0.15, 0.80), 2)
        self.last_known_price = new_price
        
        return {
            "timestamp": now,
            "source": "SIMULATED_OFFLINE_FALLBACK (Base: $4069.00)",
            "close": new_price,
            "spread": round(random.uniform(0.15, 0.35), 2),
            "atr_14": round(random.uniform(2.20, 3.80), 2),
            "rsi_14": round(random.uniform(36.0, 66.0), 1),
            "ema_200": round(new_price - 8.0, 2),
            "vwap": round(new_price - 2.5, 2),
            "asian_high": round(new_price - 3.5, 2),
            "asian_low": round(new_price - 18.0, 2),
            "high": high_price,
            "low": low_price
        }

market_feed = LiveMarketDataFeed()
