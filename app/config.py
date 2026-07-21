"""
Configuration — XAU-USDT Gold Edge v5 (research-validated on real 5m history).

After testing 25+ strategy families on 443k bars (2019-2026):
  DEAD: EMA cross, Donchian, Supertrend, Asia/London/NY breakouts, Hermes 5R
  WEAK: EMA pullback, PDH/PDL, RSI MR
  BEST: Z-Score mean reversion in ranging markets (N30-style)

v5 core:
  • Z-Score ±2.2 fade when ADX ≤ 18 (strict range)
  • Turn confirmation bar
  • SL 2.5×ATR, TP 2.0R (fixed RR, not early BE)
  • Sessions 07–17 UTC, max 3/day, 1% risk
  • Trend/breakout setups OFF by default
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Tuple


def _env_bool(key: str, default: str = "false") -> bool:
    return os.getenv(key, default).lower() in ("true", "1", "yes", "on")


def _env_sessions(raw: str | None) -> List[Tuple[int, int]]:
    if not raw:
        # Liquid hours for MR fades (London through NY)
        return [(7, 17)]
    windows: List[Tuple[int, int]] = []
    for part in raw.split(","):
        part = part.strip().replace(":", "-")
        if "-" not in part:
            continue
        a, b = part.split("-", 1)
        windows.append((int(a), int(b)))
    return windows or [(7, 17)]


def _resolve_db_path() -> str:
    explicit = os.getenv("DB_PATH") or os.getenv("DATABASE_PATH")
    if explicit:
        return explicit
    on_vol = (
        os.path.isdir("/data")
        or bool(os.getenv("RAILWAY_VOLUME_MOUNT_PATH"))
        or bool(os.getenv("RAILWAY_VOLUME_NAME"))
    )
    if on_vol:
        for c in ("/data/history.db", "/data/History.db"):
            if os.path.exists(c):
                return c
        return "/data/history.db"
    for c in ("history.db", "History.db"):
        if os.path.exists(c):
            return c
    return "history.db"


def _resolve_database_url(db_path: str) -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    if db_path.startswith("/"):
        return f"sqlite:///{db_path}"
    return f"sqlite:///{os.path.abspath(db_path)}"


@dataclass
class AppConfig:
    ENV: str = os.getenv("ENV", "production")
    RAILWAY_ENVIRONMENT: str = os.getenv("RAILWAY_ENVIRONMENT", "")
    STRATEGY_VERSION: str = "v5-zscore-mr"

    INITIAL_BALANCE_USDT: float = float(os.getenv("PAPER_BALANCE", "100.00"))
    SYMBOL: str = os.getenv("SYMBOL", "XAU-USDT")
    EXCHANGE_ID: str = os.getenv("EXCHANGE_ID", "bybit")
    TIMEFRAME: str = os.getenv("TIMEFRAME", "5m")

    # Book risk
    MAX_LEVERAGE: int = int(os.getenv("MAX_LEVERAGE", "50"))
    RISK_PER_TRADE_PCT: float = float(os.getenv("RISK_PER_TRADE_PCT", "1.0"))
    MAX_ALLOWABLE_SPREAD_USD: float = float(os.getenv("MAX_SPREAD_USD", "0.40"))
    MAX_OPEN_TRADES: int = int(os.getenv("MAX_OPEN_TRADES", "1"))
    MAX_DAILY_LOSS_PCT: float = float(os.getenv("MAX_DAILY_LOSS_PCT", "4.0"))
    MAX_TRADES_PER_DAY: int = int(os.getenv("MAX_TRADES_PER_DAY", "3"))
    ENTRY_COOLDOWN_SECONDS: float = float(os.getenv("ENTRY_COOLDOWN_SECONDS", "600"))
    LOSS_COOLDOWN_SECONDS: float = float(os.getenv("LOSS_COOLDOWN_SECONDS", "1200"))
    MARGIN_CAP_PCT: float = float(os.getenv("MARGIN_CAP_PCT", "35.0"))

    # Sessions
    ALLOWED_SESSIONS: List[Tuple[int, int]] = field(
        default_factory=lambda: _env_sessions(os.getenv("ALLOWED_SESSIONS"))
    )
    # Kept for market_data / optional secondary setups
    ASIAN_START_HOUR_UTC: int = int(os.getenv("ASIAN_START_HOUR_UTC", "0"))
    ASIAN_END_HOUR_UTC: int = int(os.getenv("ASIAN_END_HOUR_UTC", "7"))
    NY_ORB_START_HOUR_UTC: int = int(os.getenv("NY_ORB_START_HOUR_UTC", "13"))
    NY_ORB_END_HOUR_UTC: int = int(os.getenv("NY_ORB_END_HOUR_UTC", "16"))
    NY_ORB_DECISION_HOUR_UTC: int = int(os.getenv("NY_ORB_DECISION_HOUR_UTC", "16"))

    # Indicators
    EMA_TREND_PERIOD: int = int(os.getenv("EMA_TREND_PERIOD", "200"))
    EMA_FAST_PERIOD: int = int(os.getenv("EMA_FAST_PERIOD", "50"))
    EMA_PULLBACK_PERIOD: int = int(os.getenv("EMA_PULLBACK_PERIOD", "21"))
    ZSCORE_PERIOD: int = int(os.getenv("ZSCORE_PERIOD", "20"))
    ATR_PERIOD: int = int(os.getenv("ATR_PERIOD", "14"))
    ATR_AVG_LOOKBACK: int = int(os.getenv("ATR_AVG_LOOKBACK", "50"))
    RSI_PERIOD: int = int(os.getenv("RSI_PERIOD", "14"))
    RSI_OVERBOUGHT: float = float(os.getenv("RSI_OVERBOUGHT", "72.0"))
    RSI_OVERSOLD: float = float(os.getenv("RSI_OVERSOLD", "28.0"))
    ADX_PERIOD: int = int(os.getenv("ADX_PERIOD", "14"))

    # Z-Score MR (PRIMARY — research best)
    ZSCORE_ENTRY: float = float(os.getenv("ZSCORE_ENTRY", "2.2"))
    ADX_RANGE_MAX: float = float(os.getenv("ADX_RANGE_MAX", "18.0"))  # strict range only
    REQUIRE_TURN_CONFIRM: bool = _env_bool("REQUIRE_TURN_CONFIRM", "true")
    ENABLE_ZSCORE_MR: bool = _env_bool("ENABLE_ZSCORE_MR", "true")

    # Optional secondary (OFF — failed research)
    ADX_TREND_MIN: float = float(os.getenv("ADX_TREND_MIN", "28.0"))
    MIN_DI_SPREAD: float = float(os.getenv("MIN_DI_SPREAD", "8.0"))
    SWEEP_MIN_PIERCE_USD: float = float(os.getenv("SWEEP_MIN_PIERCE_USD", "0.80"))
    MIN_ASIAN_RANGE_USD: float = float(os.getenv("MIN_ASIAN_RANGE_USD", "5.00"))
    MAX_ASIAN_RANGE_USD: float = float(os.getenv("MAX_ASIAN_RANGE_USD", "35.00"))
    BREAKOUT_BUFFER_USD: float = float(os.getenv("BREAKOUT_BUFFER_USD", "0.40"))
    REQUIRE_CLOSE_BEYOND: bool = _env_bool("REQUIRE_CLOSE_BEYOND", "true")
    REQUIRE_EMA_STACK: bool = _env_bool("REQUIRE_EMA_STACK", "true")
    ENABLE_EMA_PULLBACK: bool = _env_bool("ENABLE_EMA_PULLBACK", "false")
    ENABLE_SWEEP_FADE: bool = _env_bool("ENABLE_SWEEP_FADE", "false")
    ENABLE_ASIA_BREAKOUT: bool = _env_bool("ENABLE_ASIA_BREAKOUT", "false")
    ENABLE_NY_ORB: bool = _env_bool("ENABLE_NY_ORB", "false")

    # Cost / vol
    ROUND_TRIP_COST_USD: float = float(os.getenv("ROUND_TRIP_COST_USD", "0.40"))
    MIN_SL_COST_MULTIPLE: float = float(os.getenv("MIN_SL_COST_MULTIPLE", "5.0"))
    MIN_TP_COST_MULTIPLE: float = float(os.getenv("MIN_TP_COST_MULTIPLE", "8.0"))
    MIN_ATR_USD: float = float(os.getenv("MIN_ATR_USD", "0.80"))
    ATR_VS_AVG_MIN: float = float(os.getenv("ATR_VS_AVG_MIN", "0.40"))
    ATR_VS_AVG_MAX: float = float(os.getenv("ATR_VS_AVG_MAX", "2.00"))

    # Exits — fixed RR, NO early BE (research: BE killed trend systems;
    # for MR, wide SL + 2R TP worked best)
    SL_ATR_MULTIPLIER: float = float(os.getenv("SL_ATR_MULTIPLIER", "2.5"))
    MIN_SL_USD: float = float(os.getenv("MIN_SL_USD", "2.00"))
    TP_RR_RATIO: float = float(os.getenv("TP_RR_RATIO", "2.0"))
    # BE disabled by default (set high so it never arms before TP)
    BE_TRIGGER_RR: float = float(os.getenv("BE_TRIGGER_RR", "9.0"))
    TRAIL_ATR_MULTIPLIER: float = float(os.getenv("TRAIL_ATR_MULTIPLIER", "2.5"))
    ENABLE_TRAIL: bool = _env_bool("ENABLE_TRAIL", "false")
    TP1_RR_RATIO: float = float(os.getenv("TP1_RR_RATIO", "9.0"))
    TP2_RR_RATIO: float = float(os.getenv("TP2_RR_RATIO", "2.0"))

    DB_PATH: str = field(default_factory=_resolve_db_path)
    DATABASE_URL: str = field(default="")

    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

    PAPER_TRADING: bool = _env_bool("PAPER_TRADING", "true")
    POLL_INTERVAL_SECONDS: float = float(os.getenv("POLL_INTERVAL_SECONDS", "5.0"))

    APEX_API_KEY: str = os.getenv("APEX_API_KEY", "")
    APEX_API_SECRET: str = os.getenv("APEX_API_SECRET", "")
    APEX_PASSPHRASE: str = os.getenv("APEX_PASSPHRASE", "")

    def __post_init__(self) -> None:
        if not self.DATABASE_URL:
            self.DATABASE_URL = _resolve_database_url(self.DB_PATH)
        if os.getenv("TP_RR_RATIO") and not os.getenv("TP2_RR_RATIO"):
            self.TP2_RR_RATIO = self.TP_RR_RATIO


config = AppConfig()
