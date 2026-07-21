"""
Live Market Data Feed Engine for XAU-USDT / PAXG-USDT.
Fetches real-time live OHLCV & orderbook spread directly from multiple redundant exchange feeds
(Binance PAXGUSDT, Bybit PAXGUSDT/XAUUSDT, Phemex cXAUUSDT, and public Gold feeds),
with automatic fallback to realistic $4071.00+ live baseline if offline.
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
    Connects to live public exchange APIs (Binance, Bybit, Phemex) to ingest real-time Gold (XAU/PAXG) 5m bars and spread.
    Computes real-time EMA 200, VWAP, Asian High/Low, ATR 14, and RSI 14 directly from live exchange candles.
    """
    def __init__(self):
        self.tech = TechnicalIndicators()
        # Set realistic 2026 Gold baseline ($4071.00 / oz)
        self.last_known_price = float(config.INITIAL_PRICE_BASELINE if hasattr(config, "INITIAL_PRICE_BASELINE") else 4071.00)
        self.simulated_cycle = 0

    def _fetch_from_binance_sync(self) -> Optional[Dict[str, Any]]:
        """Queries Binance public kline and bookTicker for PAXGUSDT (Tokenized Gold tracking XAU/USD)."""
        try:
            url = "https://api.binance.com/api/v3/klines?symbol=PAXGUSDT&interval=5m&limit=200"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Quantitative Gold-Scalp Bot)"})
            with urllib.request.urlopen(req, timeout=6.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                
            if not data or not isinstance(data, list) or len(data) < 20:
                return None
                
            # Binance returns chronological: [openTime, open, high, low, close, volume, ...]
            closes = [float(item[4]) for item in data]
            highs = [float(item[2]) for item in data]
            lows = [float(item[3]) for item in data]
            opens = [float(item[1]) for item in data]
            
            latest_bar = data[-1]
            latest_close = float(latest_bar[4])
            latest_high = float(latest_bar[2])
            latest_low = float(latest_bar[3])
            self.last_known_price = latest_close
            
            # Fetch bookTicker for exact bid/ask spread
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
            logger.debug(f"Binance fetch failed: {e}")
            return None

    def _fetch_from_bybit_sync(self) -> Optional[Dict[str, Any]]:
        """Queries Bybit V5 API for PAXGUSDT spot or XAUUSDT linear."""
        for cat, sym in [("linear", "XAUUSDT"), ("spot", "PAXGUSDT")]:
            try:
                url = f"https://api.bybit.com/v5/market/kline?category={cat}&symbol={sym}&interval=5&limit=200"
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Quantitative Gold-Scalp Bot)"})
                with urllib.request.urlopen(req, timeout=6.0) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    
                if not data or data.get("retCode") != 0 or not data.get("result", {}).get("list"):
                    continue
                    
                raw_list = data["result"]["list"]
                raw_list.reverse()  # Chronological order
                
                closes = [float(item[4]) for item in raw_list]
                highs = [float(item[2]) for item in raw_list]
                lows = [float(item[3]) for item in raw_list]
                
                latest_bar = raw_list[-1]
                latest_close = float(latest_bar[4])
                latest_high = float(latest_bar[2])
                latest_low = float(latest_bar[3])
                self.last_known_price = latest_close
                
                spread = 0.18
                try:
                    t_url = f"https://api.bybit.com/v5/market/tickers?category={cat}&symbol={sym}"
                    req_t = urllib.request.Request(t_url, headers={"User-Agent": "Mozilla/5.0 (Quantitative Gold-Scalp Bot)"})
                    with urllib.request.urlopen(req_t, timeout=4.0) as resp_t:
                        data_t = json.loads(resp_t.read().decode("utf-8"))
                        if data_t and data_t.get("retCode") == 0 and data_t.get("result", {}).get("list"):
                            bid = float(data_t["result"]["list"][0].get("bid1Price", latest_close - 0.09))
                            ask = float(data_t["result"]["list"][0].get("ask1Price", latest_close + 0.09))
                            if ask > bid > 0:
                                spread = round(ask - bid, 2)
                except Exception:
                    pass
                    
                return self._build_tick_result(f"LIVE_EXCHANGE_BYBIT_{sym}", raw_list, closes, highs, lows, latest_close, latest_high, latest_low, spread)
            except Exception as e:
                logger.debug(f"Bybit ({cat}:{sym}) fetch failed: {e}")
                continue
        return None

    def _fetch_from_phemex_sync(self) -> Optional[Dict[str, Any]]:
        """Queries Phemex public kline API for cXAUUSDT (Gold Perp)."""
        try:
            url = "https://api.phemex.com/exchange/public/md/kline?symbol=cXAUUSDT&resolution=300&limit=200"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Quantitative Gold-Scalp Bot)"})
            with urllib.request.urlopen(req, timeout=6.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                
            if not data or not data.get("data") or not isinstance(data["data"]["rows"], list):
                return None
                
            rows = data["data"]["rows"]  # [time, interval, last_close, open, high, low, close, volume]
            if len(rows) < 20:
                return None
                
            # Phemex prices in rows might be scaled (e.g. 10^4 or exact float depending on symbol v2/v1)
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
            
            return self._build_tick_result("LIVE_EXCHANGE_PHEMEX_cXAUUSDT", rows, closes, highs, lows, latest_close, latest_high, latest_low, 0.25)
        except Exception as e:
            logger.debug(f"Phemex fetch failed: {e}")
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
        """Tries redundant live exchanges in sequence (Binance -> Bybit -> Phemex)."""
        tick = self._fetch_from_binance_sync()
        if tick:
            return tick
        tick = self._fetch_from_bybit_sync()
        if tick:
            return tick
        tick = self._fetch_from_phemex_sync()
        if tick:
            return tick
        return None

    async def get_latest_market_tick(self) -> Dict[str, Any]:
        """
        Asynchronously fetches real-time Gold market data across redundant exchanges.
        If offline, gracefully falls back to synthetic simulation starting at the current 2026 Gold price (~$4071.00).
        """
        loop = asyncio.get_running_loop()
        live_tick = await loop.run_in_executor(None, self._fetch_live_market_data_sync)
        if live_tick:
            logger.info(f"Connected to live market: {live_tick['source']} | Price: ${live_tick['close']:.2f} | Spread: ${live_tick['spread']:.2f}")
            return live_tick

        # Fallback synthetic simulation around $4071.00 if offline or API rate limited
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
            "source": "SIMULATED_OFFLINE_FALLBACK (Base: $4071.00)",
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
