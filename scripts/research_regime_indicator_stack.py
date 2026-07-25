#!/usr/bin/env python3
"""Pre-registered XAU regime/indicator architecture study.

This script tests *methodology* learned from BTC/ETH research, not imported
crypto parameters.  Each model is evaluated independently before any ensemble
is considered:

    regime -> volatility -> momentum -> value location -> trigger -> risk

The models deliberately use conventional definitions (MACD 12/26/9, RSI 14,
CCI 20, Bollinger 20/2, EMA 50/200) without fitting their thresholds to the
XAU results.  Development (2019-09--2022) is the sole selection window.
Validation (2023--2024) and holdout (2025 onward) are never used to choose a
model or combine models.

A composite is created only from development-eligible *different families*;
it does not blend parameter values or retroactively choose the better signal.
If no family is eligible, no composite is backtested or promoted.  That is a
valid result, not a reason to loosen the rules.

Required input is the provenance-labelled canonical UTC M5 file made by
``reconcile_xau_m1_repairs.py``.  It is intentionally a local artifact:

    python scripts/research_regime_indicator_stack.py \
      /tmp/xau_canonical_repaired.csv --gap-guard

Execution remains an engineered OHLC approximation: $0.40 fixed spread,
$0.03 adverse slippage per fill, and 0.04% fee per side.  Actual executable
ApeX/XAU contract terms have not been verified.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import glob
import hashlib
import math
import statistics
import sys
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Deque, Dict, Iterable, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import config
from scripts.backtest_v5_csv import WilderIndicators
from scripts.gap_guard import GapGuard


UTC = timezone.utc
DEVELOPMENT_START = datetime(2019, 9, 6, tzinfo=UTC)
VALIDATION_START = datetime(2023, 1, 1, tzinfo=UTC)
HOLDOUT_START = datetime(2025, 1, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class Bar:
    """A canonical UTC five-minute candle plus its repair provenance."""

    timestamp: datetime  # candle start in canonical UTC
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str

    @property
    def decision_time(self) -> datetime:
        """The earliest time this completed candle can be acted on."""
        return self.timestamp + timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class Feature:
    """Values known at a bar's close.  No field uses a future bar."""

    bar: Bar
    atr: Optional[float]
    atr_ratio: Optional[float]
    adx: Optional[float]
    plus_di: Optional[float]
    minus_di: Optional[float]
    ema50: Optional[float]
    ema200: Optional[float]
    macd_hist: Optional[float]
    rsi: Optional[float]
    cci: Optional[float]
    bb_middle: Optional[float]
    bb_upper: Optional[float]
    bb_lower: Optional[float]
    bb_width_percentile: Optional[float]
    vwap: Optional[float]
    vwap_observations: int


@dataclass(frozen=True, slots=True)
class Strategy:
    name: str
    family: str
    variant: str
    max_hold_bars: int


@dataclass(frozen=True, slots=True)
class Signal:
    strategy: Strategy
    direction: str
    stop_distance: float


@dataclass(slots=True)
class Position:
    strategy: Strategy
    opened_at: datetime
    direction: str
    reference_price: float
    entry: float
    stop: float
    target: float
    size: float
    margin: float
    entry_fee: float
    stop_distance: float
    bars_held: int = 0
    ambiguous_ohlc_exit: bool = False


@dataclass(slots=True)
class Trade:
    strategy: str
    family: str
    window: str
    opened_at: datetime
    closed_at: datetime
    direction: str
    entry: float
    exit: float
    size: float
    stop_distance: float
    gross_pnl: float
    entry_fee: float
    exit_fee: float
    net_pnl: float
    reason: str
    bars_held: int
    ambiguous_ohlc_exit: bool
    balance_after: float

    def row(self) -> Dict[str, object]:
        return {
            "strategy": self.strategy,
            "family": self.family,
            "window": self.window,
            "opened_at_utc": self.opened_at.isoformat(),
            "closed_at_utc": self.closed_at.isoformat(),
            "direction": self.direction,
            "entry": round(self.entry, 6),
            "exit": round(self.exit, 6),
            "size_oz": round(self.size, 6),
            "stop_distance_usd": round(self.stop_distance, 6),
            "gross_pnl_usd": round(self.gross_pnl, 6),
            "entry_fee_usd": round(self.entry_fee, 6),
            "exit_fee_usd": round(self.exit_fee, 6),
            "net_pnl_usd": round(self.net_pnl, 6),
            "exit_reason": self.reason,
            "bars_held": self.bars_held,
            "ambiguous_ohlc_exit": self.ambiguous_ohlc_exit,
            "balance_after": round(self.balance_after, 6),
        }


@dataclass(slots=True)
class Result:
    model: str
    family: str
    window: str
    candidate_signals: int
    entries_suppressed_by_open_position: int
    entries_blocked_by_risk_guard: int
    conflicting_composite_signals: int
    trades: List[Trade]
    initial_balance: float
    final_balance: float
    max_drawdown: float
    simulated_fees: float

    @property
    def closed_trades(self) -> int:
        return len(self.trades)

    @property
    def wins(self) -> int:
        return sum(trade.net_pnl > 0 for trade in self.trades)

    @property
    def losses(self) -> int:
        return sum(trade.net_pnl < 0 for trade in self.trades)

    @property
    def net_pnl(self) -> float:
        return self.final_balance - self.initial_balance

    @property
    def return_pct(self) -> float:
        return (self.final_balance / self.initial_balance - 1.0) * 100.0 if self.initial_balance else 0.0

    @property
    def profit_factor(self) -> Optional[float]:
        gross_profit = sum(trade.net_pnl for trade in self.trades if trade.net_pnl > 0)
        gross_loss = abs(sum(trade.net_pnl for trade in self.trades if trade.net_pnl < 0))
        return gross_profit / gross_loss if gross_loss else None

    @property
    def win_rate_pct(self) -> float:
        return self.wins / self.closed_trades * 100.0 if self.closed_trades else 0.0

    def row(self) -> Dict[str, object]:
        return {
            "model": self.model,
            "family": self.family,
            "window": self.window,
            "candidate_signals": self.candidate_signals,
            "suppressed_by_open_position": self.entries_suppressed_by_open_position,
            "blocked_by_risk_guard": self.entries_blocked_by_risk_guard,
            "conflicting_composite_signals": self.conflicting_composite_signals,
            "trades": self.closed_trades,
            "wins": self.wins,
            "losses": self.losses,
            "final_balance": round(self.final_balance, 6),
            "net_pnl_usd": round(self.net_pnl, 6),
            "return_pct": round(self.return_pct, 6),
            "profit_factor": round(self.profit_factor, 6) if self.profit_factor is not None else "",
            "win_rate_pct": round(self.win_rate_pct, 6),
            "max_realized_drawdown_usd": round(self.max_drawdown, 6),
            "simulated_fees_usd": round(self.simulated_fees, 6),
        }


class EMA:
    """Streaming EMA seeded from the first full simple moving average."""

    def __init__(self, period: int):
        self.period = period
        self.alpha = 2.0 / (period + 1.0)
        self.seed: List[float] = []
        self.value: Optional[float] = None

    def update(self, value: float) -> Optional[float]:
        if self.value is None:
            self.seed.append(value)
            if len(self.seed) == self.period:
                self.value = sum(self.seed) / self.period
        else:
            self.value += self.alpha * (value - self.value)
        return self.value


class WilderRSI:
    """Streaming RSI with a Wilder seed, evaluated only after close."""

    def __init__(self, period: int = 14):
        self.period = period
        self.previous: Optional[float] = None
        self.gains: List[float] = []
        self.losses: List[float] = []
        self.average_gain: Optional[float] = None
        self.average_loss: Optional[float] = None

    def update(self, close: float) -> Optional[float]:
        if self.previous is None:
            self.previous = close
            return None
        change = close - self.previous
        gain, loss = max(change, 0.0), max(-change, 0.0)
        self.previous = close
        if self.average_gain is None or self.average_loss is None:
            self.gains.append(gain)
            self.losses.append(loss)
            if len(self.gains) == self.period:
                self.average_gain = sum(self.gains) / self.period
                self.average_loss = sum(self.losses) / self.period
            else:
                return None
        else:
            self.average_gain = (self.average_gain * (self.period - 1) + gain) / self.period
            self.average_loss = (self.average_loss * (self.period - 1) + loss) / self.period
        if self.average_loss <= 1e-12:
            return 100.0
        ratio = self.average_gain / self.average_loss
        return 100.0 - 100.0 / (1.0 + ratio)


class RollingMedian:
    """Exact trailing median with no future values and O(log n) updates."""

    def __init__(self, capacity: int):
        self.capacity = capacity
        self.values: Deque[float] = deque()
        self.ordered: List[float] = []

    def median(self) -> Optional[float]:
        if not self.ordered:
            return None
        midpoint = len(self.ordered) // 2
        if len(self.ordered) % 2:
            return self.ordered[midpoint]
        return (self.ordered[midpoint - 1] + self.ordered[midpoint]) / 2.0

    def add(self, value: float) -> None:
        if len(self.values) == self.capacity:
            outgoing = self.values.popleft()
            index = bisect.bisect_left(self.ordered, outgoing)
            # Floating values are retained directly, so this should always find
            # the exact element.  The guard makes a corrupted state explicit.
            if index == len(self.ordered):
                raise RuntimeError("RollingMedian state mismatch")
            self.ordered.pop(index)
        bisect.insort(self.ordered, value)
        self.values.append(value)

    @property
    def ready(self) -> bool:
        return len(self.values) == self.capacity


class SourceLocalSessionVWAP:
    """UTC-day VWAP that resets if repair provenance changes within a day.

    M5 original volume and aggregated M1 volume use incompatible scales.  A
    VWAP is scale-invariant when all bars in its session share the same source,
    but a seam must never silently mix those scales.  Therefore this is an
    explicitly *source-local* session VWAP, not a venue-certified VWAP.
    """

    def __init__(self) -> None:
        self.key: Optional[Tuple[datetime.date, str]] = None
        self.sum_pv = 0.0
        self.sum_volume = 0.0
        self.observations = 0

    def update(self, bar: Bar) -> Tuple[Optional[float], int]:
        key = (bar.timestamp.date(), bar.source)
        if key != self.key:
            self.key = key
            self.sum_pv = 0.0
            self.sum_volume = 0.0
            self.observations = 0
        typical_price = (bar.high + bar.low + bar.close) / 3.0
        if bar.volume > 0.0 and math.isfinite(bar.volume):
            self.sum_pv += typical_price * bar.volume
            self.sum_volume += bar.volume
        self.observations += 1
        if self.sum_volume <= 0.0:
            return None, self.observations
        return self.sum_pv / self.sum_volume, self.observations


STRATEGIES: Tuple[Strategy, ...] = (
    Strategy("Trend pullback — core", "Trend pullback", "core", 48),
    Strategy("Trend pullback — MACD + CCI", "Trend pullback", "macd_cci", 48),
    Strategy("Trend pullback — value-confirmed", "Trend pullback", "value", 48),
    Strategy("Squeeze breakout — core", "Squeeze breakout", "core", 48),
    Strategy("Squeeze breakout — value-confirmed", "Squeeze breakout", "value", 48),
    Strategy("Range reversion — core", "Range reversion", "core", 24),
    Strategy("Range reversion — value-confirmed", "Range reversion", "value", 24),
)


def expand_paths(patterns: Sequence[str]) -> List[Path]:
    paths: List[Path] = []
    for pattern in patterns:
        matches = [Path(item) for item in glob.glob(pattern)]
        paths.extend(matches or [Path(pattern)])
    unique = sorted({path.resolve() for path in paths})
    if not unique:
        raise ValueError("No input files matched")
    return unique


def load_canonical_bars(patterns: Sequence[str]) -> List[Bar]:
    """Load only timezone-labelled canonical CSV files; never guess a clock."""
    bars: List[Bar] = []
    for path in expand_paths(patterns):
        if not path.exists():
            raise FileNotFoundError(path)
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            fields = set(reader.fieldnames or [])
            required = {"timestamp_utc", "open", "high", "low", "close", "volume", "source"}
            missing = required - fields
            if missing:
                raise ValueError(
                    f"{path} is not a provenance-labelled canonical CSV; missing {sorted(missing)}"
                )
            for row in reader:
                timestamp = datetime.fromisoformat(row["timestamp_utc"].replace("Z", "+00:00")).astimezone(UTC)
                bar = Bar(
                    timestamp=timestamp,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                    source=row["source"],
                )
                if min(bar.open, bar.high, bar.low, bar.close) <= 0.0 or bar.high < max(bar.open, bar.close) or bar.low > min(bar.open, bar.close):
                    raise ValueError(f"Invalid OHLC row in {path}: {row}")
                bars.append(bar)
    bars.sort(key=lambda bar: bar.timestamp)
    deduplicated: List[Bar] = []
    seen = set()
    for bar in bars:
        if bar.timestamp in seen:
            raise ValueError(f"Duplicate canonical timestamp: {bar.timestamp.isoformat()}")
        deduplicated.append(bar)
        seen.add(bar.timestamp)
    if not bars:
        raise ValueError("No bars loaded")
    return deduplicated


def sha256_for_paths(paths: Sequence[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    return digest.hexdigest()


def build_features(bars: Sequence[Bar]) -> List[Feature]:
    """Build closed-bar indicators once, preserving source-local VWAP seams."""
    trend_wilder = WilderIndicators(period=14, z_period=20, atr_average=50)
    ema12, ema26, macd_signal = EMA(12), EMA(26), EMA(9)
    ema50, ema200 = EMA(50), EMA(200)
    rsi = WilderRSI(14)
    typicals: Deque[float] = deque(maxlen=20)
    closes: Deque[float] = deque(maxlen=20)
    atr_history = RollingMedian(96)
    width_history: Deque[float] = deque(maxlen=96)
    vwap = SourceLocalSessionVWAP()
    features: List[Feature] = []

    for bar in bars:
        # WilderIndicators only needs timestamp/OHLCV fields; this local Bar
        # intentionally has the same names without discarding provenance here.
        wilder = trend_wilder.update(bar)
        close_ema12 = ema12.update(bar.close)
        close_ema26 = ema26.update(bar.close)
        macd_line = close_ema12 - close_ema26 if close_ema12 is not None and close_ema26 is not None else None
        macd_average = macd_signal.update(macd_line) if macd_line is not None else None
        macd_hist = macd_line - macd_average if macd_line is not None and macd_average is not None else None
        ema50_value, ema200_value = ema50.update(bar.close), ema200.update(bar.close)
        rsi_value = rsi.update(bar.close)

        typical = (bar.high + bar.low + bar.close) / 3.0
        typicals.append(typical)
        closes.append(bar.close)
        cci: Optional[float] = None
        bb_middle = bb_upper = bb_lower = bb_width_percentile = None
        if len(typicals) == 20:
            typical_mean = sum(typicals) / 20.0
            mean_deviation = sum(abs(value - typical_mean) for value in typicals) / 20.0
            cci = (typical - typical_mean) / (0.015 * mean_deviation) if mean_deviation > 1e-12 else 0.0
            close_mean = sum(closes) / 20.0
            close_stdev = math.sqrt(sum((value - close_mean) ** 2 for value in closes) / 20.0)
            bb_middle = close_mean
            bb_upper = close_mean + 2.0 * close_stdev
            bb_lower = close_mean - 2.0 * close_stdev
            width = (bb_upper - bb_lower) / close_mean if close_mean > 0.0 else 0.0
            if len(width_history) == width_history.maxlen:
                # Rank against prior widths only, so the current close cannot
                # dilute its own compression/expansion classification.
                bb_width_percentile = sum(value <= width for value in width_history) / len(width_history)
            width_history.append(width)

        atr = float(wilder["atr_14"]) if wilder is not None else None
        atr_ratio: Optional[float] = None
        previous_atr_median = atr_history.median() if atr_history.ready else None
        if atr is not None and previous_atr_median and previous_atr_median > 1e-12:
            atr_ratio = atr / previous_atr_median
        if atr is not None:
            atr_history.add(atr)

        vwap_value, vwap_observations = vwap.update(bar)
        features.append(
            Feature(
                bar=bar,
                atr=atr,
                atr_ratio=atr_ratio,
                adx=float(wilder["adx"]) if wilder is not None else None,
                plus_di=float(wilder["plus_di"]) if wilder is not None else None,
                minus_di=float(wilder["minus_di"]) if wilder is not None else None,
                ema50=ema50_value,
                ema200=ema200_value,
                macd_hist=macd_hist,
                rsi=rsi_value,
                cci=cci,
                bb_middle=bb_middle,
                bb_upper=bb_upper,
                bb_lower=bb_lower,
                bb_width_percentile=bb_width_percentile,
                vwap=vwap_value,
                vwap_observations=vwap_observations,
            )
        )
    return features


def is_tradeable_base(feature: Feature) -> bool:
    """Shared non-optimised execution/volatility gate for every family."""
    values = (
        feature.atr,
        feature.atr_ratio,
        feature.adx,
        feature.plus_di,
        feature.minus_di,
        feature.ema50,
        feature.ema200,
        feature.macd_hist,
        feature.rsi,
        feature.cci,
        feature.bb_upper,
        feature.bb_lower,
        feature.bb_middle,
    )
    if any(value is None or not math.isfinite(float(value)) for value in values):
        return False
    # A decision is made only at the completed bar's end.  07:00--20:00 UTC is
    # an explicit, fixed liquidity convention for this experiment, not a
    # daylight-saving-adjusted or development-selected session.
    decision = feature.bar.decision_time
    if not 7 <= decision.hour < 20:
        return False
    assert feature.atr is not None and feature.atr_ratio is not None
    return (
        feature.atr >= config.MIN_ATR_USD
        and config.ATR_VS_AVG_MIN <= feature.atr_ratio <= config.ATR_VS_AVG_MAX
    )


def trend_pullback_signal(strategy: Strategy, current: Feature, previous: Feature) -> Optional[Signal]:
    """Trend regime, EMA pullback/recovery, then optional MACD/CCI/value gates."""
    if not is_tradeable_base(current):
        return None
    assert current.atr is not None and current.adx is not None
    assert current.ema50 is not None and current.ema200 is not None
    assert current.plus_di is not None and current.minus_di is not None
    assert current.rsi is not None and previous.rsi is not None
    assert current.macd_hist is not None and previous.macd_hist is not None
    assert current.cci is not None and previous.cci is not None

    bar, prior = current.bar, previous.bar
    previous_ema50 = previous.ema50
    long_core = (
        previous_ema50 is not None
        and current.ema50 > current.ema200
        and bar.close > current.ema200
        and current.adx >= 20.0
        and current.plus_di > current.minus_di
        and prior.low <= previous_ema50
    )
    long_core = bool(long_core) and (
        bar.low <= current.ema50
        and bar.close > current.ema50
        and bar.close > bar.open
        and bar.close > prior.high
        and previous.rsi < 50.0 <= current.rsi <= 68.0
    )
    short_core = (
        previous_ema50 is not None
        and current.ema50 < current.ema200
        and bar.close < current.ema200
        and current.adx >= 20.0
        and current.minus_di > current.plus_di
        and prior.high >= previous_ema50
    )
    short_core = bool(short_core) and (
        bar.high >= current.ema50
        and bar.close < current.ema50
        and bar.close < bar.open
        and bar.close < prior.low
        and previous.rsi > 50.0 >= current.rsi >= 32.0
    )

    direction = "LONG" if long_core else "SHORT" if short_core else None
    if direction is None:
        return None
    if strategy.variant in {"macd_cci", "value"}:
        momentum_ok = (
            current.macd_hist > 0.0 and current.macd_hist > previous.macd_hist and previous.cci <= 0.0 < current.cci
            if direction == "LONG"
            else current.macd_hist < 0.0 and current.macd_hist < previous.macd_hist and previous.cci >= 0.0 > current.cci
        )
        if not momentum_ok:
            return None
    if strategy.variant == "value":
        if current.vwap is None or current.vwap_observations < 12:
            return None
        value_ok = bar.low <= current.vwap < bar.close if direction == "LONG" else bar.high >= current.vwap > bar.close
        if not value_ok:
            return None
    return Signal(strategy, direction, max(config.MIN_SL_USD, 1.5 * current.atr))


def squeeze_breakout_signal(strategy: Strategy, current: Feature, previous: Feature) -> Optional[Signal]:
    """Compression-to-expansion breakout; value variant adds CCI/VWAP only."""
    if not is_tradeable_base(current):
        return None
    assert current.atr is not None and current.adx is not None
    assert current.ema50 is not None and current.ema200 is not None
    assert current.rsi is not None and current.macd_hist is not None
    assert previous.macd_hist is not None and previous.bb_width_percentile is not None
    assert current.bb_upper is not None and current.bb_lower is not None
    assert previous.bb_upper is not None and previous.bb_lower is not None
    assert current.cci is not None

    bar, prior = current.bar, previous.bar
    compressed = previous.bb_width_percentile <= 0.25
    long_core = (
        compressed
        and current.ema50 > current.ema200
        and current.adx >= 18.0
        and prior.close <= previous.bb_upper
        and bar.close > current.bb_upper
        and bar.high - bar.low >= current.atr
        and current.macd_hist > 0.0 > previous.macd_hist
        and 55.0 <= current.rsi <= 78.0
    )
    short_core = (
        compressed
        and current.ema50 < current.ema200
        and current.adx >= 18.0
        and prior.close >= previous.bb_lower
        and bar.close < current.bb_lower
        and bar.high - bar.low >= current.atr
        and current.macd_hist < 0.0 < previous.macd_hist
        and 22.0 <= current.rsi <= 45.0
    )
    direction = "LONG" if long_core else "SHORT" if short_core else None
    if direction is None:
        return None
    if strategy.variant == "value":
        if current.vwap is None or current.vwap_observations < 12:
            return None
        value_ok = (
            current.cci > 100.0 and bar.close > current.vwap
            if direction == "LONG"
            else current.cci < -100.0 and bar.close < current.vwap
        )
        if not value_ok:
            return None
    return Signal(strategy, direction, max(config.MIN_SL_USD, 1.5 * current.atr))


def range_reversion_signal(strategy: Strategy, current: Feature, previous: Feature) -> Optional[Signal]:
    """Explicitly isolated BB/RSI/CCI range fade, not a trend signal."""
    if not is_tradeable_base(current):
        return None
    assert current.atr is not None and current.adx is not None
    assert current.rsi is not None and previous.rsi is not None
    assert current.cci is not None and previous.cci is not None
    assert current.bb_upper is not None and current.bb_lower is not None
    assert previous.bb_upper is not None and previous.bb_lower is not None

    bar, prior = current.bar, previous.bar
    long_core = (
        current.adx <= 18.0
        and prior.close <= previous.bb_lower
        and bar.low <= current.bb_lower
        and bar.close > current.bb_lower
        and bar.close > bar.open
        and previous.rsi < 35.0 <= current.rsi < 55.0
        and previous.cci < -100.0 <= current.cci
    )
    short_core = (
        current.adx <= 18.0
        and prior.close >= previous.bb_upper
        and bar.high >= current.bb_upper
        and bar.close < current.bb_upper
        and bar.close < bar.open
        and previous.rsi > 65.0 >= current.rsi > 45.0
        and previous.cci > 100.0 >= current.cci
    )
    direction = "LONG" if long_core else "SHORT" if short_core else None
    if direction is None:
        return None
    if strategy.variant == "value":
        if current.vwap is None or current.vwap_observations < 12:
            return None
        value_ok = (
            current.vwap > bar.close and current.vwap - bar.close >= 0.5 * current.atr
            if direction == "LONG"
            else current.vwap < bar.close and bar.close - current.vwap >= 0.5 * current.atr
        )
        if not value_ok:
            return None
    return Signal(strategy, direction, max(config.MIN_SL_USD, 1.5 * current.atr))


def signal_for(strategy: Strategy, current: Feature, previous: Feature) -> Optional[Signal]:
    if strategy.family == "Trend pullback":
        return trend_pullback_signal(strategy, current, previous)
    if strategy.family == "Squeeze breakout":
        return squeeze_breakout_signal(strategy, current, previous)
    if strategy.family == "Range reversion":
        return range_reversion_signal(strategy, current, previous)
    raise ValueError(f"Unknown strategy family: {strategy.family}")


def open_position(signal: Signal, feature: Feature, balance: float, spread: float, fee_rate: float, slippage: float) -> Optional[Position]:
    """Use the same adverse close-fill model as the paper backtest baseline."""
    reference = feature.bar.close
    half_spread = spread / 2.0
    entry = reference + half_spread + slippage if signal.direction == "LONG" else reference - half_spread - slippage
    stop_distance = max(signal.stop_distance, max(spread * 2.0, config.ROUND_TRIP_COST_USD) * config.MIN_SL_COST_MULTIPLE)
    dollar_risk = balance * config.RISK_PER_TRADE_PCT / 100.0
    size = round(dollar_risk / stop_distance, 4)
    if size < 0.01:
        return None
    margin_cap = balance * config.MARGIN_CAP_PCT / 100.0
    margin = entry * size / config.MAX_LEVERAGE
    if margin > margin_cap:
        size = round(margin_cap * config.MAX_LEVERAGE / entry, 4)
        if size < 0.01:
            return None
        margin = entry * size / config.MAX_LEVERAGE
    entry_fee = entry * size * fee_rate
    if margin + entry_fee > balance:
        return None
    if signal.direction == "LONG":
        stop, target = entry - stop_distance, entry + config.TP_RR_RATIO * stop_distance
    else:
        stop, target = entry + stop_distance, entry - config.TP_RR_RATIO * stop_distance
    return Position(
        strategy=signal.strategy,
        opened_at=feature.bar.decision_time,
        direction=signal.direction,
        reference_price=reference,
        entry=entry,
        stop=stop,
        target=target,
        size=size,
        margin=margin,
        entry_fee=entry_fee,
        stop_distance=stop_distance,
    )


def resolve_ohlc_exit(position: Position, bar: Bar, spread: float, slippage: float) -> Optional[Tuple[float, str]]:
    """Resolve a subsequent bar conservatively: stop first if both levels touch."""
    position.bars_held += 1
    half_spread = spread / 2.0
    if position.direction == "LONG":
        executable_low, executable_high = bar.low - half_spread, bar.high - half_spread
        stop_hit, target_hit = executable_low <= position.stop, executable_high >= position.target
        position.ambiguous_ohlc_exit = stop_hit and target_hit
        if stop_hit:
            return min(position.stop, executable_low) - slippage, "SL_HIT"
        if target_hit:
            return position.target - slippage, "TP_HIT"
    else:
        executable_low, executable_high = bar.low + half_spread, bar.high + half_spread
        stop_hit, target_hit = executable_high >= position.stop, executable_low <= position.target
        position.ambiguous_ohlc_exit = stop_hit and target_hit
        if stop_hit:
            return max(position.stop, executable_high) + slippage, "SL_HIT"
        if target_hit:
            return position.target + slippage, "TP_HIT"
    return None


def close_position(
    position: Position,
    bar: Bar,
    exit_price: float,
    reason: str,
    balance: float,
    fee_rate: float,
    window: str,
) -> Tuple[Trade, float]:
    gross = (exit_price - position.entry) * position.size if position.direction == "LONG" else (position.entry - exit_price) * position.size
    exit_fee = exit_price * position.size * fee_rate
    net = gross - position.entry_fee - exit_fee
    balance = max(0.0, balance + net)
    trade = Trade(
        strategy=position.strategy.name,
        family=position.strategy.family,
        window=window,
        opened_at=position.opened_at,
        closed_at=bar.decision_time,
        direction=position.direction,
        entry=position.entry,
        exit=exit_price,
        size=position.size,
        stop_distance=position.stop_distance,
        gross_pnl=gross,
        entry_fee=position.entry_fee,
        exit_fee=exit_fee,
        net_pnl=net,
        reason=reason,
        bars_held=position.bars_held,
        ambiguous_ohlc_exit=position.ambiguous_ohlc_exit,
        balance_after=balance,
    )
    return trade, balance


def adverse_close_exit(position: Position, bar: Bar, spread: float, slippage: float) -> float:
    half_spread = spread / 2.0
    return bar.close - half_spread - slippage if position.direction == "LONG" else bar.close + half_spread + slippage


def choose_composite_signal(signals: Sequence[Signal]) -> Optional[Signal]:
    """Allow a composite only when one signal is present (no hidden tie-break)."""
    return signals[0] if len(signals) == 1 else None


def simulate(
    features: Sequence[Feature],
    strategies: Sequence[Strategy],
    window_name: str,
    start: datetime,
    end: Optional[datetime],
    spread: float,
    fee_rate: float,
    slippage: float,
    gap_guard: Optional[GapGuard],
    composite: bool = False,
) -> Result:
    """Simulate one model/ensemble through an isolated chronological window."""
    if not strategies:
        raise ValueError("simulate requires at least one strategy")
    model = " + ".join(strategy.name for strategy in strategies) if composite else strategies[0].name
    family = "Composite (frozen development selection)" if composite else strategies[0].family
    balance = initial = float(config.INITIAL_BALANCE_USDT)
    peak = balance
    max_drawdown = 0.0
    daily_counts: Dict[str, int] = {}
    daily_pnl: Dict[str, float] = {}
    cooldown_until: Optional[datetime] = None
    position: Optional[Position] = None
    trades: List[Trade] = []
    candidate_signals = 0
    suppressed = 0
    blocked = 0
    conflicts = 0
    last_feature_in_window: Optional[Feature] = None

    for index in range(1, len(features)):
        current, previous = features[index], features[index - 1]
        decision = current.bar.decision_time
        if decision < start or (end is not None and decision >= end):
            continue
        last_feature_in_window = current

        # Entry occurs at the preceding completed close, so this is the first
        # OHLC range eligible to touch its stop/target.
        if position is not None:
            outcome = resolve_ohlc_exit(position, current.bar, spread, slippage)
            if outcome is None and gap_guard is not None and gap_guard.force_flat_after(current.bar.timestamp):
                outcome = (adverse_close_exit(position, current.bar, spread, slippage), "DATA_GAP_EXIT")
            # Intraday study: exit after the 20:55--21:00 UTC completed bar;
            # this avoids assuming a fill path through the daily closure.
            if outcome is None and decision.hour >= 21:
                outcome = (adverse_close_exit(position, current.bar, spread, slippage), "DAY_EXIT")
            if outcome is None and position.bars_held >= position.strategy.max_hold_bars:
                outcome = (adverse_close_exit(position, current.bar, spread, slippage), "TIME_EXIT")
            if outcome is not None:
                exit_price, reason = outcome
                trade, balance = close_position(position, current.bar, exit_price, reason, balance, fee_rate, window_name)
                trades.append(trade)
                peak = max(peak, balance)
                max_drawdown = max(max_drawdown, peak - balance)
                daily_key = decision.date().isoformat()
                daily_pnl[daily_key] = daily_pnl.get(daily_key, 0.0) + trade.net_pnl
                cooldown_seconds = config.LOSS_COOLDOWN_SECONDS if trade.net_pnl < 0.0 else config.ENTRY_COOLDOWN_SECONDS
                cooldown_until = decision + timedelta(seconds=cooldown_seconds)
                position = None

        raw_signals = [signal for strategy in strategies if (signal := signal_for(strategy, current, previous)) is not None]
        candidate_signals += len(raw_signals)
        if position is not None:
            suppressed += len(raw_signals)
            continue
        if not raw_signals or balance < 5.0:
            continue
        if composite and len(raw_signals) > 1:
            conflicts += len(raw_signals)
            continue
        signal = choose_composite_signal(raw_signals) if composite else raw_signals[0]
        if signal is None:
            continue
        date_key = decision.date().isoformat()
        risk_blocked = (
            (gap_guard is not None and not gap_guard.entry_allowed(current.bar.timestamp))
            or (cooldown_until is not None and decision < cooldown_until)
            or daily_counts.get(date_key, 0) >= config.MAX_TRADES_PER_DAY
            or daily_pnl.get(date_key, 0.0) <= -initial * config.MAX_DAILY_LOSS_PCT / 100.0
        )
        if risk_blocked:
            blocked += 1
            continue
        position = open_position(signal, current, balance, spread, fee_rate, slippage)
        if position is None:
            blocked += 1
            continue
        daily_counts[date_key] = daily_counts.get(date_key, 0) + 1

    # A holding result at an arbitrary split endpoint would make windows
    # incomparable.  Mark to the final observed close, with the same adverse
    # quote/slippage convention as all other discretionary exits.
    if position is not None and last_feature_in_window is not None:
        final_bar = last_feature_in_window.bar
        trade, balance = close_position(
            position,
            final_bar,
            adverse_close_exit(position, final_bar, spread, slippage),
            "WINDOW_END_EXIT",
            balance,
            fee_rate,
            window_name,
        )
        trades.append(trade)
        peak = max(peak, balance)
        max_drawdown = max(max_drawdown, peak - balance)

    return Result(
        model=model,
        family=family,
        window=window_name,
        candidate_signals=candidate_signals,
        entries_suppressed_by_open_position=suppressed,
        entries_blocked_by_risk_guard=blocked,
        conflicting_composite_signals=conflicts,
        trades=trades,
        initial_balance=initial,
        final_balance=balance,
        max_drawdown=max_drawdown,
        simulated_fees=sum(trade.entry_fee + trade.exit_fee for trade in trades),
    )


def development_eligible(result: Result) -> bool:
    """Pre-stated eligibility: depth, current-cost profitability, and PF buffer."""
    return (
        result.closed_trades >= 30
        and result.profit_factor is not None
        and result.profit_factor >= 1.10
        and result.net_pnl > 0.0
    )


def select_family_winners(development: Sequence[Result], strategies: Sequence[Strategy]) -> List[Strategy]:
    """Choose at most one eligible model per family from development only."""
    strategy_by_name = {strategy.name: strategy for strategy in strategies}
    grouped: Dict[str, List[Result]] = {}
    for result in development:
        if development_eligible(result):
            grouped.setdefault(result.family, []).append(result)
    selected: List[Strategy] = []
    for family in sorted(grouped):
        winner = sorted(
            grouped[family],
            key=lambda result: (
                float(result.profit_factor or 0.0),
                result.net_pnl,
                result.closed_trades,
            ),
            reverse=True,
        )[0]
        selected.append(strategy_by_name[winner.model])
    return selected


def pf_text(value: Optional[float]) -> str:
    return f"{value:.2f}" if value is not None else "n/a"


def results_table(results: Iterable[Result]) -> List[str]:
    lines = [
        "| Model | Window | Signals | Trades | Final | Return | PF | Win rate | Max DD | Fees |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for result in results:
        lines.append(
            f"| `{result.model}` | {result.window} | {result.candidate_signals} | {result.closed_trades} | "
            f"${result.final_balance:.2f} | {result.return_pct:+.2f}% | {pf_text(result.profit_factor)} | "
            f"{result.win_rate_pct:.1f}% | ${result.max_drawdown:.2f} | ${result.simulated_fees:.2f} |"
        )
    return lines


def write_csv(path: Path, results: Sequence[Result]) -> None:
    rows = [result.row() for result in results]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_trade_csv(path: Path, results: Sequence[Result]) -> None:
    rows = [trade.row() for result in results for trade in result.trades]
    fields = [
        "strategy", "family", "window", "opened_at_utc", "closed_at_utc", "direction", "entry", "exit", "size_oz",
        "stop_distance_usd", "gross_pnl_usd", "entry_fee_usd", "exit_fee_usd", "net_pnl_usd", "exit_reason",
        "bars_held", "ambiguous_ohlc_exit", "balance_after",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def report(
    path: Path,
    bars: Sequence[Bar],
    source_hash: str,
    guard: Optional[GapGuard],
    development: Sequence[Result],
    validation: Sequence[Result],
    holdout: Sequence[Result],
    selected: Sequence[Strategy],
    composites: Sequence[Result],
    args: argparse.Namespace,
) -> None:
    source_counts = Counter(bar.source for bar in bars)
    total_composite_results = list(composites)
    lines = [
        "# XAU regime + MACD/RSI/CCI/BB/VWAP architecture study",
        "",
        "## Research question",
        "",
        "Can a regime-first architecture transferred *methodologically* from public BTC/ETH indicator research survive a cost-aware XAU walk-forward test? This is not a parameter transfer and not a promise of a profitable bot.",
        "",
        "## Locked protocol before reading validation/holdout results",
        "",
        "- Families are evaluated separately: trend pullback, squeeze breakout, and range reversion.",
        "- Feature roles: EMA/ADX/DI = regime; ATR ratio = volatility gate; MACD/RSI/CCI = momentum/recovery; Bollinger Bands = compression/extension; VWAP = value location.",
        "- Conventional indicator definitions are fixed: EMA 50/200; MACD 12/26/9; RSI 14; CCI 20; Bollinger 20/2; Wilder ATR/ADX 14. They were not tuned against XAU outcomes in this study.",
        "- Entry occurs only after a completed M5 candle. The first eligible stop/target bar is the following M5 candle. If both touch in one OHLC bar, the stop is chosen first.",
        "- All models share the exact same risk/execution lifecycle: 07:00–20:00 UTC decisions; flat after the 20:55–21:00 UTC candle; 1% account risk target, 35% margin cap, 3 trades/day cap, configured cooldown/daily-loss guard, 1.5×ATR stop subject to the existing $2.00/cost floor, fixed 2R target, and a 4h trend/breakout or 2h range maximum holding time.",
        f"- Costs are engineering assumptions only: ${args.spread:.2f} execution spread, ${args.slippage:.2f} adverse slippage per fill, {args.fee_rate * 100:.02f}% fee per side.",
        "- Development selection is limited to 2019-09–2022. A family is eligible only with ≥30 closed development trades, net profit after current costs, and PF ≥1.10. At most one eligible variant per family is selected. Validation and holdout cannot alter this selection.",
        "- A composite takes only the frozen selected families, risks one normal position at a time, and skips an ambiguous simultaneous multi-signal rather than using a post-hoc tie-break.",
        "",
        "## Data and provenance",
        "",
        f"- Canonical UTC M5 bars: **{len(bars):,}** from {bars[0].timestamp.isoformat()} through {bars[-1].timestamp.isoformat()}.",
        f"- Source provenance: {', '.join(f'`{source}` = {count:,}' for source, count in sorted(source_counts.items()))}.",
        f"- Input SHA-256 (file names + bytes): `{source_hash}`.",
        "- Original M5 server labels were normalized with `Europe/Helsinki` IANA rules; complete native M1 aggregates repair only missing M5 intervals. This study refuses raw timezone-unlabelled CSVs.",
        "- VWAP is a **source-local UTC-day VWAP**. Original M5 volumes and M1-aggregated volumes have incompatible magnitudes, so VWAP resets at a provenance seam and never mixes volume scales. It is a location proxy, not venue-certified traded volume/VWAP.",
        "- Historical bid/ask, trade-side flow, order-book depth, funding, and actual Apex contract specifications were unavailable and therefore not inferred from this file.",
        f"- Gap guard: {'enabled' if guard else 'disabled'}" + (f"; {guard.non_routine_gap_count} non-routine gaps block pre-gap entries and force a last-observable-close exit." if guard else "."),
        "",
        "## Development-only independent families",
        "",
        *results_table(development),
        "",
        "## Frozen validation diagnostics (all independent models)",
        "",
        *results_table(validation),
        "",
        "## Frozen holdout diagnostics (all independent models)",
        "",
        *results_table(holdout),
        "",
        "## Development selection and composite",
        "",
    ]
    if not selected:
        lines.extend(
            [
                "No family met the pre-stated development eligibility rule. **No composite was created.** Combining rejected or under-sampled signals would manufacture complexity, not evidence.",
            ]
        )
    else:
        lines.extend(
            [
                "Frozen selected family representatives: " + ", ".join(f"`{strategy.name}`" for strategy in selected) + ".",
                "",
                *results_table(total_composite_results),
            ]
        )
    lines.extend(
        [
            "",
            "## Blind spots retained deliberately",
            "",
            "- **Trend pullback:** EMAs and ADX are lagging; a recovery through a value reference can be the first leg of a trend failure. A stop on OHLC data does not know intrabar path beyond the conservative stop-first rule.",
            "- **Squeeze breakout:** Bollinger compression is not a causal forecast. News shocks and false breakouts can pass momentum filters, while a 5-minute candle hides fill sequencing and transient spread widening.",
            "- **Range reversion:** It is explicitly vulnerable to volatility expansion and persistent directional moves. The earlier canonical Z-score range baseline already failed, so this family is a falsification test rather than a presumed improvement.",
            "- **VWAP:** The available volume is source-specific rather than venue-verified. Source-local reset avoids mixing scales but does not convert it into actual execution-venue volume.",
            "- **Portfolio/execution:** All results depend on unverified spread, fee, multiplier, size, liquidation, index/mark, and funding assumptions. A positive OHLC backtest would still require independent forward paper validation; a negative one is a rejection signal.",
            "",
            "## Promotion rule",
            "",
            "Nothing in this report changes the Railway bot or enables live trading. A candidate may move only to a separately reviewed forward-paper phase if the frozen composite (or a single family when no composite is justified) has adequate trade counts, PF above 1 after verified costs in both unseen windows, acceptable drawdown, and no material provenance/gap failure. Otherwise it remains rejected.",
            "",
            f"Machine-readable metrics: [`{Path(args.results_csv).name}`]({Path(args.results_csv).name}). Trade-level audit: [`{Path(args.trades_csv).name}`]({Path(args.trades_csv).name}).",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", nargs="+", help="provenance-labelled canonical UTC M5 CSV file(s) or globs")
    parser.add_argument("--spread", type=float, default=0.40, help="fixed execution spread in USD")
    parser.add_argument("--slippage", type=float, default=0.03, help="adverse slippage per fill in USD")
    parser.add_argument("--fee-rate", type=float, default=0.0004, help="taker fee per side, e.g. 0.0004 = 0.04%%")
    parser.add_argument("--gap-guard", action="store_true", help="enable canonical universal gap guard")
    parser.add_argument("--report", default="XAU_REGIME_INDICATOR_STACK.md")
    parser.add_argument("--results-csv", default="XAU_REGIME_INDICATOR_STACK.csv")
    parser.add_argument("--trades-csv", default="XAU_REGIME_INDICATOR_STACK_TRADES.csv")
    args = parser.parse_args()
    if args.spread < 0.0 or args.slippage < 0.0 or args.fee_rate < 0.0:
        parser.error("spread, slippage, and fee rate must be non-negative")

    paths = expand_paths(args.csv)
    bars = load_canonical_bars([str(path) for path in paths])
    features = build_features(bars)
    guard = GapGuard(bars) if args.gap_guard else None
    source_hash = sha256_for_paths(paths)
    windows = (
        ("Development (2019-09 to 2022-12)", DEVELOPMENT_START, VALIDATION_START),
        ("Validation (2023-2024)", VALIDATION_START, HOLDOUT_START),
        ("Holdout (2025 onward)", HOLDOUT_START, None),
    )

    by_window: Dict[str, List[Result]] = {name: [] for name, _, _ in windows}
    for window_name, start, end in windows:
        for strategy in STRATEGIES:
            by_window[window_name].append(
                simulate(features, [strategy], window_name, start, end, args.spread, args.fee_rate, args.slippage, guard)
            )
    development = by_window[windows[0][0]]
    validation = by_window[windows[1][0]]
    holdout = by_window[windows[2][0]]
    selected = select_family_winners(development, STRATEGIES)

    composites: List[Result] = []
    if selected:
        for window_name, start, end in windows:
            composites.append(
                simulate(
                    features, selected, window_name, start, end, args.spread, args.fee_rate, args.slippage, guard, composite=True
                )
            )

    all_results = [*development, *validation, *holdout, *composites]
    write_csv(Path(args.results_csv), all_results)
    write_trade_csv(Path(args.trades_csv), all_results)
    report(Path(args.report), bars, source_hash, guard, development, validation, holdout, selected, composites, args)

    print(f"Loaded {len(bars):,} canonical UTC M5 bars; built {len(features):,} feature rows.")
    if selected:
        print("Development-selected families: " + "; ".join(strategy.name for strategy in selected))
        for result in composites:
            print(f"Composite | {result.window}: trades={result.closed_trades} return={result.return_pct:+.2f}% PF={pf_text(result.profit_factor)}")
    else:
        print("No family met the pre-stated development eligibility rule; no composite created.")


if __name__ == "__main__":
    main()
