"""Lean Railway configuration for the v7 paper-only XAU-USDT worker."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Tuple


def _env_bool(key: str, default: str = "false") -> bool:
    return os.getenv(key, default).lower() in ("true", "1", "yes", "on")


def _env_sessions(raw: str | None) -> List[Tuple[int, int]]:
    windows: List[Tuple[int, int]] = []
    for part in (raw or "6-20").split(","):
        part = part.strip().replace(":", "-")
        if "-" not in part:
            continue
        start, end = part.split("-", 1)
        windows.append((int(start), int(end)))
    return windows or [(6, 20)]


def _resolve_db_path() -> str:
    explicit = os.getenv("DB_PATH") or os.getenv("DATABASE_PATH")
    if explicit:
        return explicit
    if (
        os.path.isdir("/data")
        or os.getenv("RAILWAY_VOLUME_MOUNT_PATH")
        or os.getenv("RAILWAY_VOLUME_NAME")
    ):
        return "/data/history.db"
    return "history.db"


def _resolve_database_url(db_path: str) -> str:
    explicit = os.getenv("DATABASE_URL")
    if explicit:
        return explicit
    absolute = db_path if db_path.startswith("/") else os.path.abspath(db_path)
    return f"sqlite:///{absolute}"


@dataclass
class AppConfig:
    ENV: str = os.getenv("ENV", "production")
    STRATEGY_VERSION: str = os.getenv(
        "STRATEGY_VERSION", "v7-adaptive-session-scalper"
    )
    ENABLE_ADAPTIVE_SCALPER: bool = STRATEGY_VERSION.lower().startswith("v7")

    INITIAL_BALANCE_USDT: float = float(os.getenv("PAPER_BALANCE", "100.00"))
    PAPER_TRADING: bool = _env_bool("PAPER_TRADING", "true")
    SYMBOL: str = os.getenv("SYMBOL", "XAU-USDT")
    EXCHANGE_ID: str = os.getenv("EXCHANGE_ID", "bybit")
    TIMEFRAME: str = os.getenv("TIMEFRAME", "5m")
    # Closed M5 data does not need five-second downloads. One minute keeps
    # deployment/network usage low while still consuming each close promptly.
    POLL_INTERVAL_SECONDS: float = float(os.getenv("POLL_INTERVAL_SECONDS", "60"))
    ONLY_CLOSED_CANDLES: bool = _env_bool("ONLY_CLOSED_CANDLES", "true")
    MAX_DATA_STALENESS_SECONDS: float = float(
        os.getenv("MAX_DATA_STALENESS_SECONDS", "900")
    )
    ALLOW_PROXY_FEEDS: bool = _env_bool("ALLOW_PROXY_FEEDS", "false")

    MAX_LEVERAGE: int = int(os.getenv("MAX_LEVERAGE", "50"))
    RISK_PER_TRADE_PCT: float = float(os.getenv("RISK_PER_TRADE_PCT", "0.50"))
    MAX_ALLOWABLE_SPREAD_USD: float = float(os.getenv("MAX_SPREAD_USD", "0.40"))
    MAX_OPEN_TRADES: int = int(os.getenv("MAX_OPEN_TRADES", "1"))
    MAX_DAILY_LOSS_PCT: float = float(os.getenv("MAX_DAILY_LOSS_PCT", "2.0"))
    MAX_TRADES_PER_DAY: int = int(os.getenv("MAX_TRADES_PER_DAY", "4"))
    ENTRY_COOLDOWN_SECONDS: float = float(os.getenv("ENTRY_COOLDOWN_SECONDS", "600"))
    LOSS_COOLDOWN_SECONDS: float = float(os.getenv("LOSS_COOLDOWN_SECONDS", "1200"))
    MARGIN_CAP_PCT: float = float(os.getenv("MARGIN_CAP_PCT", "25.0"))

    V7_ALLOWED_SESSIONS: List[Tuple[int, int]] = field(
        default_factory=lambda: _env_sessions(os.getenv("V7_ALLOWED_SESSIONS"))
    )
    V7_RISK_CAP_PCT: float = float(os.getenv("V7_RISK_CAP_PCT", "0.50"))
    V7_MIN_SIGNAL_SCORE: int = int(os.getenv("V7_MIN_SIGNAL_SCORE", "4"))
    V7_RANGE_Z_ENTRY: float = float(os.getenv("V7_RANGE_Z_ENTRY", "1.60"))
    V7_RANGE_ADX_MAX: float = float(os.getenv("V7_RANGE_ADX_MAX", "23.0"))
    V7_TREND_ADX_MIN: float = float(os.getenv("V7_TREND_ADX_MIN", "18.0"))
    V7_ATR_SHOCK_MULTIPLE: float = float(
        os.getenv("V7_ATR_SHOCK_MULTIPLE", "2.20")
    )
    V7_RANGE_TP_RR: float = float(os.getenv("V7_RANGE_TP_RR", "1.35"))
    V7_TREND_TP_RR: float = float(os.getenv("V7_TREND_TP_RR", "1.60"))
    V7_LIQUIDITY_TP_RR: float = float(
        os.getenv("V7_LIQUIDITY_TP_RR", "1.50")
    )
    V7_BE_TRIGGER_RR: float = float(os.getenv("V7_BE_TRIGGER_RR", "1.00"))
    V7_RANGE_MAX_HOLDING_BARS: int = int(
        os.getenv("V7_RANGE_MAX_HOLDING_BARS", "8")
    )
    V7_TREND_MAX_HOLDING_BARS: int = int(
        os.getenv("V7_TREND_MAX_HOLDING_BARS", "12")
    )
    V7_MIN_STOP_COST_MULTIPLE: float = float(
        os.getenv("V7_MIN_STOP_COST_MULTIPLE", "1.25")
    )
    V7_MIN_TARGET_COST_MULTIPLE: float = float(
        os.getenv("V7_MIN_TARGET_COST_MULTIPLE", "1.50")
    )

    EMA_TREND_PERIOD: int = int(os.getenv("EMA_TREND_PERIOD", "200"))
    EMA_FAST_PERIOD: int = int(os.getenv("EMA_FAST_PERIOD", "50"))
    EMA_PULLBACK_PERIOD: int = int(os.getenv("EMA_PULLBACK_PERIOD", "21"))
    ZSCORE_PERIOD: int = int(os.getenv("ZSCORE_PERIOD", "20"))
    ATR_PERIOD: int = int(os.getenv("ATR_PERIOD", "14"))
    ATR_AVG_LOOKBACK: int = int(os.getenv("ATR_AVG_LOOKBACK", "50"))
    RSI_PERIOD: int = int(os.getenv("RSI_PERIOD", "14"))
    ADX_PERIOD: int = int(os.getenv("ADX_PERIOD", "14"))
    MIN_ATR_USD: float = float(os.getenv("MIN_ATR_USD", "0.80"))
    ASIAN_START_HOUR_UTC: int = int(os.getenv("ASIAN_START_HOUR_UTC", "0"))
    ASIAN_END_HOUR_UTC: int = int(os.getenv("ASIAN_END_HOUR_UTC", "7"))

    PAPER_EXECUTION_MODE: str = os.getenv(
        "PAPER_EXECUTION_MODE", "TAKER"
    ).strip().upper()
    PAPER_TAKER_FEE_RATE: float = float(
        os.getenv("PAPER_TAKER_FEE_RATE", "0.0004")
    )
    PAPER_MAKER_FEE_RATE: float = float(
        os.getenv("PAPER_MAKER_FEE_RATE", "0.0001")
    )
    PAPER_SLIPPAGE_USD: float = float(os.getenv("PAPER_SLIPPAGE_USD", "0.03"))

    DB_PATH: str = field(default_factory=_resolve_db_path)
    DATABASE_URL: str = field(default="")
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

    def __post_init__(self) -> None:
        if not self.DATABASE_URL:
            self.DATABASE_URL = _resolve_database_url(self.DB_PATH)
        if not self.ENABLE_ADAPTIVE_SCALPER:
            raise ValueError("Only STRATEGY_VERSION=v7-adaptive-session-scalper is supported")
        if self.INITIAL_BALANCE_USDT <= 0:
            raise ValueError("PAPER_BALANCE must be greater than zero")
        if not 0 < self.RISK_PER_TRADE_PCT <= 1:
            raise ValueError("RISK_PER_TRADE_PCT must be in (0, 1]")
        if not 0 < self.V7_RISK_CAP_PCT <= 1:
            raise ValueError("V7_RISK_CAP_PCT must be in (0, 1]")
        if not 1 <= self.MAX_LEVERAGE <= 75:
            raise ValueError("MAX_LEVERAGE must be in [1, 75]")
        if not 0 < self.MARGIN_CAP_PCT <= 100:
            raise ValueError("MARGIN_CAP_PCT must be in (0, 100]")
        if self.PAPER_EXECUTION_MODE not in ("TAKER", "MAKER_POST_ONLY"):
            raise ValueError("PAPER_EXECUTION_MODE must be TAKER or MAKER_POST_ONLY")
        if min(
            self.PAPER_TAKER_FEE_RATE,
            self.PAPER_MAKER_FEE_RATE,
            self.PAPER_SLIPPAGE_USD,
        ) < 0:
            raise ValueError("Paper costs cannot be negative")
        if self.V7_MIN_SIGNAL_SCORE < 3:
            raise ValueError("V7_MIN_SIGNAL_SCORE must be at least 3")
        # Protect existing Railway deployments that still carry the old 5s
        # variable: completed M5 bars never justify faster network polling.
        self.POLL_INTERVAL_SECONDS = max(60.0, self.POLL_INTERVAL_SECONDS)

    @property
    def paper_fee_rate(self) -> float:
        if self.PAPER_EXECUTION_MODE == "MAKER_POST_ONLY":
            return self.PAPER_MAKER_FEE_RATE
        return self.PAPER_TAKER_FEE_RATE


config = AppConfig()
