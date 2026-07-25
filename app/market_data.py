"""Live, closed-candle market data for the XAU-USDT paper service.

No generated prices are used.  The preferred feeds are the direct XAU-USDT
perpetuals.  PAXG is deliberately excluded unless ``ALLOW_PROXY_FEEDS=true``;
it tracks gold but is not the requested contract and must never be a silent
substitution.  REST polling is intentionally conservative: the strategy only
receives a bar after that bar has closed.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import ssl
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.config import config
from app.engine import TechnicalIndicators

logger = logging.getLogger("LiveMarketData")

try:
    import ccxt  # type: ignore

    CCXT_AVAILABLE = True
except ImportError:
    CCXT_AVAILABLE = False


def _http_get_json(url: str, timeout: float = 8.0) -> Optional[Any]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Gold-Scalp/5.1 (paper-research; closed-candle)",
            "Accept": "application/json",
        },
    )
    try:
        context = ssl.create_default_context()
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        logger.debug("GET failed %s: %s", url, exc)
        return None


def _timeframe_seconds(value: str) -> int:
    raw = value.strip().lower()
    try:
        if raw.endswith("m"):
            return max(60, int(raw[:-1]) * 60)
        if raw.endswith("h"):
            return int(raw[:-1]) * 3600
    except ValueError:
        pass
    raise ValueError("TIMEFRAME must look like 5m or 1h")


def _bar_hour_utc(timestamp_ms: float) -> int:
    return datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc).hour


def _bar_date_utc(timestamp_ms: float) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d")


class LiveMarketDataFeed:
    def __init__(self) -> None:
        self.tech = TechnicalIndicators()
        self.last_known_price = 0.0
        self.last_valid_source = "NONE"
        self.last_tick: Optional[Dict[str, Any]] = None
        self.consecutive_failures = 0
        self.timeframe_seconds = _timeframe_seconds(config.TIMEFRAME)

    def _closed_rows(self, rows: List[list]) -> List[list]:
        """Validate, sort and remove the live/incomplete candle."""
        cleaned: List[list] = []
        seen: set[int] = set()
        for row in rows:
            try:
                ts = int(float(row[0]))
                o, h, l, c = (float(row[i]) for i in range(1, 5))
                v = float(row[5] or 0.0)
            except (IndexError, TypeError, ValueError):
                continue
            if (
                ts in seen
                or not all(math.isfinite(x) for x in (o, h, l, c, v))
                or min(o, h, l, c) <= 0
                or h < max(o, c, l)
                or l > min(o, c, h)
            ):
                continue
            seen.add(ts)
            cleaned.append([ts, o, h, l, c, max(v, 0.0)])
        cleaned.sort(key=lambda item: item[0])
        if config.ONLY_CLOSED_CANDLES:
            now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            period_ms = self.timeframe_seconds * 1000
            # A small boundary buffer avoids accepting an exchange's stale
            # still-open candle exactly at the minute transition.
            cleaned = [row for row in cleaned if row[0] + period_ms <= now_ms - 1000]
        return cleaned

    def _build_tick_result(
        self,
        source_name: str,
        source_symbol: str,
        ohlcv: List[list],
        bid: float = 0.0,
        ask: float = 0.0,
        is_proxy: bool = False,
    ) -> Optional[Dict[str, Any]]:
        rows = self._closed_rows(ohlcv)
        required = max(config.EMA_TREND_PERIOD, config.ATR_AVG_LOOKBACK + config.ATR_PERIOD + 2, 60)
        if len(rows) < required:
            logger.debug("%s has %d valid closed candles; need %d", source_name, len(rows), required)
            return None
        timestamps = [float(row[0]) for row in rows]
        opens = [float(row[1]) for row in rows]
        highs = [float(row[2]) for row in rows]
        lows = [float(row[3]) for row in rows]
        closes = [float(row[4]) for row in rows]
        volumes = [float(row[5]) for row in rows]
        latest_close = closes[-1]
        latest_bar_ms = int(timestamps[-1])
        bar_age = datetime.now(timezone.utc).timestamp() - (
            latest_bar_ms / 1000.0 + self.timeframe_seconds
        )
        if bar_age > config.MAX_DATA_STALENESS_SECONDS:
            logger.warning("Rejecting stale %s candle (%.0fs old)", source_name, bar_age)
            return None

        # The ticker is newer than the candle. It is used only for current
        # spread/fill assumptions, never to calculate indicators.
        if not (ask > bid > 0):
            estimated_spread = min(config.MAX_ALLOWABLE_SPREAD_USD, max(0.01, latest_close * 0.00005))
            bid, ask = latest_close - estimated_spread / 2, latest_close + estimated_spread / 2
        spread = max(0.0, ask - bid)

        ema_200 = self.tech.calculate_ema(closes, config.EMA_TREND_PERIOD)
        ema_50 = self.tech.calculate_ema(closes, config.EMA_FAST_PERIOD)
        ema_21 = self.tech.calculate_ema(closes, config.EMA_PULLBACK_PERIOD)
        atr_14 = self.tech.calculate_atr(highs, lows, closes, config.ATR_PERIOD)
        rsi_14 = self.tech.calculate_rsi(closes, config.RSI_PERIOD)
        adx, plus_di, minus_di = self.tech.calculate_adx(highs, lows, closes, config.ADX_PERIOD)
        sma_z = self.tech.calculate_sma(closes, config.ZSCORE_PERIOD)
        stdev_z = self.tech.calculate_stdev(closes, config.ZSCORE_PERIOD)
        zscore = (latest_close - sma_z) / stdev_z if stdev_z > 1e-9 else 0.0
        atr_values = self.tech.atr_series(highs, lows, closes, config.ATR_PERIOD)
        atr_window = atr_values[-config.ATR_AVG_LOOKBACK :] or [atr_14]
        atr_avg = sum(atr_window) / len(atr_window)

        # Indicators based on the current UTC day's closed bars only.
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        day_indexes = [i for i, ts in enumerate(timestamps) if _bar_date_utc(ts) == today]
        if not day_indexes:
            day_indexes = list(range(max(0, len(rows) - 72), len(rows)))
        vwap_num = vwap_den = 0.0
        for i in day_indexes:
            typical = (highs[i] + lows[i] + closes[i]) / 3.0
            volume = volumes[i] or 1.0
            vwap_num += typical * volume
            vwap_den += volume
        vwap = vwap_num / vwap_den if vwap_den else latest_close

        asian = [
            i
            for i, ts in enumerate(timestamps)
            if _bar_date_utc(ts) == today
            and config.ASIAN_START_HOUR_UTC <= _bar_hour_utc(ts) < config.ASIAN_END_HOUR_UTC
        ]
        asian_high = max((highs[i] for i in asian), default=max(highs[-min(72, len(highs)) :]))
        asian_low = min((lows[i] for i in asian), default=min(lows[-min(72, len(lows)) :]))
        now_hour = datetime.now(timezone.utc).hour

        ny_orb = [
            i
            for i, ts in enumerate(timestamps)
            if _bar_date_utc(ts) == today
            and config.NY_ORB_START_HOUR_UTC <= _bar_hour_utc(ts) < config.NY_ORB_END_HOUR_UTC
        ]
        tick: Dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                (latest_bar_ms / 1000.0) + self.timeframe_seconds, tz=timezone.utc
            ),
            "bar_timestamp_ms": latest_bar_ms,
            "bar_closed_at": datetime.fromtimestamp(
                (latest_bar_ms / 1000.0) + self.timeframe_seconds, tz=timezone.utc
            ).isoformat(),
            "source": source_name,
            "source_symbol": source_symbol,
            "is_proxy": is_proxy,
            "close": round(latest_close, 4),
            "open": round(opens[-1], 4),
            "high": round(highs[-1], 4),
            "low": round(lows[-1], 4),
            "bid": round(bid, 4),
            "ask": round(ask, 4),
            "spread": round(spread, 4),
            "atr_14": round(atr_14, 4),
            "atr_avg": round(atr_avg, 4),
            "rsi_14": round(rsi_14, 3),
            "adx": round(adx, 3),
            "plus_di": round(plus_di, 3),
            "minus_di": round(minus_di, 3),
            "ema_200": round(ema_200, 4),
            "ema_50": round(ema_50, 4),
            "ema_21": round(ema_21, 4),
            "sma_z": round(sma_z, 4),
            "sma_20": round(sma_z, 4),
            "stdev_z": round(stdev_z, 6),
            "stdev_20": round(stdev_z, 6),
            "zscore": round(zscore, 4),
            "vwap": round(vwap, 4),
            "asian_high": round(asian_high, 4),
            "asian_low": round(asian_low, 4),
            "asian_range_ready": len(asian) >= 6 and now_hour >= config.ASIAN_END_HOUR_UTC,
            "ny_orb_high": round(max((highs[i] for i in ny_orb), default=0.0), 4),
            "ny_orb_low": round(min((lows[i] for i in ny_orb), default=0.0), 4),
            "ny_orb_ready": len(ny_orb) >= 6 and now_hour >= config.NY_ORB_DECISION_HOUR_UTC,
            "prev_close": round(closes[-2], 4),
            "prev_close_2": round(closes[-3], 4),
            "prev_high": round(highs[-2], 4),
            "prev_low": round(lows[-2], 4),
        }
        self.last_known_price = latest_close
        self.last_valid_source = source_name
        self.last_tick = tick
        self.consecutive_failures = 0
        return tick

    def _bybit_interval(self) -> str:
        """Translate the configured CCXT-style timeframe to Bybit's interval."""
        raw = config.TIMEFRAME.strip().lower()
        if raw.endswith("m"):
            return raw[:-1]
        if raw.endswith("h"):
            return str(int(raw[:-1]) * 60)
        raise ValueError(f"Unsupported Bybit timeframe: {config.TIMEFRAME}")

    @staticmethod
    def _bybit_ticker() -> Tuple[float, float]:
        data = _http_get_json(
            "https://api.bybit.com/v5/market/tickers?category=linear&symbol=XAUUSDT", timeout=5.0
        )
        try:
            row = data["result"]["list"][0]
            return float(row.get("bid1Price") or 0), float(row.get("ask1Price") or 0)
        except (KeyError, IndexError, TypeError, ValueError):
            return 0.0, 0.0

    def _fetch_bybit_rest_sync(self) -> Optional[Dict[str, Any]]:
        data = _http_get_json(
            "https://api.bybit.com/v5/market/kline?category=linear&symbol=XAUUSDT"
            f"&interval={self._bybit_interval()}&limit=300"
        )
        if not data or data.get("retCode") != 0:
            return None
        # API returns reverse chronological rows.
        rows = list(reversed(data.get("result", {}).get("list") or []))
        ohlcv = [[r[0], r[1], r[2], r[3], r[4], r[5]] for r in rows]
        bid, ask = self._bybit_ticker()
        return self._build_tick_result("BYBIT_LINEAR", "XAUUSDT", ohlcv, bid, ask)

    def _fetch_okx_rest_sync(self) -> Optional[Dict[str, Any]]:
        data = _http_get_json(
            "https://www.okx.com/api/v5/market/candles?instId=XAU-USDT-SWAP"
            f"&bar={config.TIMEFRAME}&limit=300"
        )
        if not data or data.get("code") != "0":
            return None
        rows = list(reversed(data.get("data") or []))
        ohlcv = [[r[0], r[1], r[2], r[3], r[4], r[5]] for r in rows]
        ticker = _http_get_json(
            "https://www.okx.com/api/v5/market/ticker?instId=XAU-USDT-SWAP", timeout=5.0
        )
        try:
            item = ticker["data"][0]
            bid, ask = float(item.get("bidPx") or 0), float(item.get("askPx") or 0)
        except (KeyError, IndexError, TypeError, ValueError):
            bid, ask = 0.0, 0.0
        return self._build_tick_result("OKX_SWAP", "XAU-USDT-SWAP", ohlcv, bid, ask)

    def _fetch_ccxt_direct_sync(self) -> Optional[Dict[str, Any]]:
        if not CCXT_AVAILABLE:
            return None
        # Keep the configured exchange first, then use the other direct venue.
        venues = [("bybit", "XAU/USDT:USDT"), ("okx", "XAU/USDT:USDT")]
        venues.sort(key=lambda item: item[0] != config.EXCHANGE_ID.lower())
        for exchange_id, symbol in venues:
            try:
                exchange_class = getattr(ccxt, exchange_id)
                exchange = exchange_class({"timeout": 8000, "enableRateLimit": True})
                rows = exchange.fetch_ohlcv(symbol, timeframe=config.TIMEFRAME, limit=300)
                ticker = exchange.fetch_ticker(symbol)
                bid, ask = float(ticker.get("bid") or 0), float(ticker.get("ask") or 0)
                tick = self._build_tick_result(
                    f"CCXT_{exchange_id.upper()}", symbol, rows, bid, ask
                )
                if tick:
                    return tick
            except Exception as exc:
                logger.debug("CCXT direct %s unavailable: %s", exchange_id, exc)
        return None

    def _fetch_paxg_proxy_sync(self) -> Optional[Dict[str, Any]]:
        if not config.ALLOW_PROXY_FEEDS:
            return None
        data = _http_get_json(
            f"https://api.binance.com/api/v3/klines?symbol=PAXGUSDT&interval={config.TIMEFRAME}&limit=300"
        )
        if not isinstance(data, list):
            return None
        ticker = _http_get_json("https://api.binance.com/api/v3/ticker/bookTicker?symbol=PAXGUSDT")
        try:
            bid, ask = float(ticker.get("bidPrice") or 0), float(ticker.get("askPrice") or 0)
        except (AttributeError, TypeError, ValueError):
            bid, ask = 0.0, 0.0
        return self._build_tick_result("BINANCE_PAXG_PROXY", "PAXGUSDT", data, bid, ask, is_proxy=True)

    def _fetch_live_market_data_sync(self) -> Optional[Dict[str, Any]]:
        preferred = [self._fetch_bybit_rest_sync, self._fetch_okx_rest_sync]
        if config.EXCHANGE_ID.lower() == "okx":
            preferred.reverse()
        for fetcher in (*preferred, self._fetch_ccxt_direct_sync, self._fetch_paxg_proxy_sync):
            try:
                tick = fetcher()
                if tick:
                    return tick
            except Exception as exc:
                logger.debug("%s failed: %s", fetcher.__name__, exc)
        return None

    async def get_latest_market_tick(self) -> Optional[Dict[str, Any]]:
        loop = asyncio.get_running_loop()
        tick = await loop.run_in_executor(None, self._fetch_live_market_data_sync)
        if not tick:
            self.consecutive_failures += 1
            logger.warning("No valid live XAU feed (streak=%d); no synthetic fallback", self.consecutive_failures)
            return None
        logger.info(
            "Closed %s %s | $%.2f | spr $%.3f | ATR $%.2f | ADX %.1f | Z %.2f",
            tick["source"],
            tick["bar_closed_at"],
            tick["close"],
            tick["spread"],
            tick["atr_14"],
            tick["adx"],
            tick["zscore"],
        )
        return tick


market_feed = LiveMarketDataFeed()
