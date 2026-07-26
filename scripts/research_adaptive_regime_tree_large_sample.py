#!/usr/bin/env python3
"""Large-evidence nested walk-forward sensitivity study for a layered XAU decision tree.

This is deliberately a *research* learner, not an adaptive live bot.  It
answers a narrower question: if every decision layer has flexible but bounded
parameters, can a config selected only from past data survive subsequent
out-of-sample XAU data?

Decision tree
=============
0. Data/execution guard: canonical UTC closed candle, gap guard, engineered
   spread/fee/slippage, account risk limits.
1. Market regime: BULL, BEAR, RANGE, or TRANSITION from EMA50/EMA200, ADX,
   DI direction, and EMA separation measured in ATR.
2. Volatility suitability: ATR / trailing-ATR-median must lie inside the
   candidate's learned training-only range.
3. Location/setup branch:
   * bull/bear pullback to EMA, with optional VWAP reclaim;
   * bull/bear Bollinger squeeze breakout, with optional VWAP confirmation;
   * range Bollinger extension/reversion, with optional VWAP distance.
4. Trigger: MACD histogram, RSI recovery/extreme, CCI recovery/extreme, and
   closed-candle confirmation.
5. Execution: candidate-specific ATR stop, reward/risk target and maximum
   holding time; common adverse execution assumptions and stop-first OHLC
   policy.

The candidate bank is a deterministic balanced *fractional factorial*
design.  It covers every declared level of every threshold while avoiding an
unbounded Cartesian parameter search.  The count and parameter levels are
written to a machine-readable audit.  That is important: "all parameters are
flexible" must not mean secretly searching an effectively infinite space.

At each January/July rebalance from 2023 onward, each context chooses at most
one candidate using all prior canonical history.  Selection requires at least
40 trades, positive net PnL, PF >= 1.10, and no adequately sampled
chronological quarter with PF below 0.80.  Otherwise its learned action
is NO_TRADE.  The frozen selections trade only the next six months.  The 2025+
holdout remains forward-only: later selections may use earlier data but never
future holdout candles.

Example:
    python scripts/research_adaptive_regime_tree_large_sample.py /tmp/xau_canonical_repaired.csv --gap-guard
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import config
from scripts.gap_guard import GapGuard
from scripts.research_regime_indicator_stack import (
    Bar,
    Feature,
    build_features,
    expand_paths,
    load_canonical_bars,
    sha256_for_paths,
)

UTC = timezone.utc
RESEARCH_START = datetime(2019, 9, 6, tzinfo=UTC)
VALIDATION_START = datetime(2023, 1, 1, tzinfo=UTC)
HOLDOUT_START = datetime(2025, 1, 1, tzinfo=UTC)

CONTEXTS: Tuple[Tuple[str, str, str], ...] = (
    ("BULL_PULLBACK", "pullback", "LONG"),
    ("BEAR_PULLBACK", "pullback", "SHORT"),
    ("BULL_BREAKOUT", "breakout", "LONG"),
    ("BEAR_BREAKOUT", "breakout", "SHORT"),
    ("RANGE_REVERSION", "reversion", "BOTH"),
)


@dataclass(frozen=True, slots=True)
class TreeConfig:
    """One fully specified leaf of the flexible decision tree."""

    config_id: str
    context: str
    setup: str
    direction: str
    trend_adx_min: float
    range_adx_max: float
    trend_ema_separation_atr: float
    range_ema_separation_atr: float
    atr_ratio_min: float
    atr_ratio_max: float
    ema_touch_atr: float
    rsi_level: float
    rsi_reclaim: float
    cci_level: float
    bb_width_percentile_max: float
    breakout_range_atr: float
    require_vwap: bool
    vwap_distance_atr: float
    require_confirmation_break: bool
    # A leaf always retains at least two of the three momentum confirmations;
    # this deliberately broadens evidence without turning a setup into an
    # unfiltered candle-pattern search.
    trigger_mode: str  # RSI_MACD | RSI_CCI | CCI_MACD | ALL_THREE
    stop_atr: float
    target_rr: float
    max_hold_bars: int

    def parameter_json(self) -> str:
        data = asdict(self)
        data.pop("config_id")
        return json.dumps(data, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class Signal:
    config: TreeConfig
    direction: str


@dataclass(slots=True)
class Position:
    config: TreeConfig
    opened_at: datetime
    direction: str
    entry: float
    stop: float
    target: float
    size: float
    entry_fee: float
    stop_distance: float
    bars_held: int = 0
    ambiguous_ohlc_exit: bool = False


@dataclass(slots=True)
class Trade:
    config_id: str
    context: str
    fold: str
    opened_at: datetime
    closed_at: datetime
    direction: str
    entry: float
    exit: float
    size: float
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
            "config_id": self.config_id,
            "context": self.context,
            "fold": self.fold,
            "opened_at_utc": self.opened_at.isoformat(),
            "closed_at_utc": self.closed_at.isoformat(),
            "direction": self.direction,
            "entry": round(self.entry, 6),
            "exit": round(self.exit, 6),
            "size_oz": round(self.size, 6),
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
class Simulation:
    config_id: str
    context: str
    label: str
    start: datetime
    end: datetime
    starting_balance: float
    ending_balance: float
    candidate_signals: int
    suppressed_signals: int
    blocked_signals: int
    conflicts: int
    max_drawdown: float
    trades: List[Trade]

    @property
    def net_pnl(self) -> float:
        return self.ending_balance - self.starting_balance

    @property
    def return_pct(self) -> float:
        return (self.ending_balance / self.starting_balance - 1.0) * 100.0 if self.starting_balance else 0.0

    @property
    def profit_factor(self) -> Optional[float]:
        wins = sum(trade.net_pnl for trade in self.trades if trade.net_pnl > 0.0)
        losses = abs(sum(trade.net_pnl for trade in self.trades if trade.net_pnl < 0.0))
        return wins / losses if losses else None

    @property
    def fees(self) -> float:
        return sum(trade.entry_fee + trade.exit_fee for trade in self.trades)


@dataclass(frozen=True, slots=True)
class CandidateAssessment:
    config: TreeConfig
    fold: str
    train_start: datetime
    train_end: datetime
    trades: int
    net_pnl: float
    profit_factor: Optional[float]
    worst_sampled_segment_pf: Optional[float]
    eligible: bool
    score: Optional[float]

    def row(self, selected: bool) -> Dict[str, object]:
        return {
            "fold": self.fold,
            "train_start_utc": self.train_start.isoformat(),
            "train_end_exclusive_utc": self.train_end.isoformat(),
            "context": self.config.context,
            "config_id": self.config.config_id,
            "trades": self.trades,
            "net_pnl_usd": round(self.net_pnl, 6),
            "profit_factor": round(self.profit_factor, 6) if self.profit_factor is not None else "",
            "worst_sampled_segment_pf": round(self.worst_sampled_segment_pf, 6) if self.worst_sampled_segment_pf is not None else "",
            "eligible": self.eligible,
            "selection_score": round(self.score, 6) if self.score is not None else "",
            "selected": selected,
            "parameters_json": self.config.parameter_json(),
        }


@dataclass(frozen=True, slots=True)
class Selection:
    fold: str
    context: str
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    config: Optional[TreeConfig]
    reason: str
    assessment: Optional[CandidateAssessment]

    def row(self) -> Dict[str, object]:
        return {
            "fold": self.fold,
            "context": self.context,
            "train_start_utc": self.train_start.isoformat(),
            "train_end_exclusive_utc": self.train_end.isoformat(),
            "test_start_utc": self.test_start.isoformat(),
            "test_end_exclusive_utc": self.test_end.isoformat(),
            "learned_action": self.config.config_id if self.config else "NO_TRADE",
            "reason": self.reason,
            "training_trades": self.assessment.trades if self.assessment else 0,
            "training_net_pnl_usd": round(self.assessment.net_pnl, 6) if self.assessment else "",
            "training_pf": round(self.assessment.profit_factor, 6) if self.assessment and self.assessment.profit_factor is not None else "",
            "training_worst_sampled_segment_pf": round(self.assessment.worst_sampled_segment_pf, 6) if self.assessment and self.assessment.worst_sampled_segment_pf is not None else "",
            "parameters_json": self.config.parameter_json() if self.config else "",
        }


def balanced_levels(values: Sequence[object], count: int, seed: int) -> List[object]:
    """Deterministically balance each declared threshold level across candidates."""
    repeated = [values[index % len(values)] for index in range(count)]
    random.Random(seed).shuffle(repeated)
    return repeated


def candidate_bank(count_per_context: int) -> List[TreeConfig]:
    """Create the pre-declared large-evidence fractional-factorial bank.

    Compared with the first adaptive-tree study, these leaves deliberately
    include broader *structured* trigger combinations and softer regime/ATR
    gates.  They do not drop all confirmation: every leaf requires two or all
    three of RSI, CCI, and MACD.  This grows observations per leaf while
    retaining a falsifiable decision tree.
    """
    if count_per_context < 12:
        raise ValueError("At least twelve candidates per context are needed to cover the large-evidence levels")
    configs: List[TreeConfig] = []
    for context_index, (context, setup, direction) in enumerate(CONTEXTS):
        seed_base = 20_000 + context_index * 100
        if setup == "pullback":
            rsi_levels, rsi_reclaims, cci_levels = (45.0, 50.0, 55.0), (48.0, 50.0, 52.0), (-50.0, 0.0, 25.0)
        elif setup == "breakout":
            rsi_levels, rsi_reclaims, cci_levels = (50.0, 55.0, 60.0), (48.0, 50.0, 52.0), (0.0, 50.0, 100.0)
        else:
            rsi_levels, rsi_reclaims, cci_levels = (30.0, 35.0, 40.0), (35.0, 40.0, 45.0), (50.0, 75.0, 100.0)
        levels = {
            # Softer bounds mean the study can determine whether the signal
            # itself has support rather than starving all leaves at L1/L2.
            "trend_adx_min": balanced_levels((14.0, 18.0, 22.0), count_per_context, seed_base + 1),
            "range_adx_max": balanced_levels((16.0, 20.0, 24.0), count_per_context, seed_base + 2),
            "trend_sep": balanced_levels((0.00, 0.05, 0.15), count_per_context, seed_base + 3),
            "range_sep": balanced_levels((0.15, 0.30, 0.50), count_per_context, seed_base + 4),
            "atr_min": balanced_levels((0.30, 0.45, 0.65), count_per_context, seed_base + 5),
            "atr_max": balanced_levels((1.80, 2.20, 2.60), count_per_context, seed_base + 6),
            "touch": balanced_levels((0.00, 0.25, 0.50), count_per_context, seed_base + 7),
            "rsi_level": balanced_levels(rsi_levels, count_per_context, seed_base + 8),
            "rsi_reclaim": balanced_levels(rsi_reclaims, count_per_context, seed_base + 9),
            "cci": balanced_levels(cci_levels, count_per_context, seed_base + 10),
            "bb": balanced_levels((0.20, 0.35, 0.50), count_per_context, seed_base + 11),
            "range_atr": balanced_levels((0.60, 0.80, 1.00), count_per_context, seed_base + 12),
            "require_vwap": balanced_levels((False, True), count_per_context, seed_base + 13),
            "vwap_distance": balanced_levels((0.00, 0.20, 0.40), count_per_context, seed_base + 14),
            "confirm": balanced_levels((False, True), count_per_context, seed_base + 15),
            "trigger_mode": balanced_levels(("RSI_MACD", "RSI_CCI", "CCI_MACD", "ALL_THREE"), count_per_context, seed_base + 16),
            "stop": balanced_levels((1.00, 1.25, 1.50), count_per_context, seed_base + 17),
            "rr": balanced_levels((1.25, 1.50, 1.75), count_per_context, seed_base + 18),
            "hold": balanced_levels((48, 72, 96), count_per_context, seed_base + 19),
        }
        for index in range(count_per_context):
            configs.append(
                TreeConfig(
                    config_id=f"{context}-LS{index + 1:02d}",
                    context=context,
                    setup=setup,
                    direction=direction,
                    trend_adx_min=float(levels["trend_adx_min"][index]),
                    range_adx_max=float(levels["range_adx_max"][index]),
                    trend_ema_separation_atr=float(levels["trend_sep"][index]),
                    range_ema_separation_atr=float(levels["range_sep"][index]),
                    atr_ratio_min=float(levels["atr_min"][index]),
                    atr_ratio_max=float(levels["atr_max"][index]),
                    ema_touch_atr=float(levels["touch"][index]),
                    rsi_level=float(levels["rsi_level"][index]),
                    rsi_reclaim=float(levels["rsi_reclaim"][index]),
                    cci_level=float(levels["cci"][index]),
                    bb_width_percentile_max=float(levels["bb"][index]),
                    breakout_range_atr=float(levels["range_atr"][index]),
                    require_vwap=bool(levels["require_vwap"][index]),
                    vwap_distance_atr=float(levels["vwap_distance"][index]),
                    require_confirmation_break=bool(levels["confirm"][index]),
                    trigger_mode=str(levels["trigger_mode"][index]),
                    stop_atr=float(levels["stop"][index]),
                    target_rr=float(levels["rr"][index]),
                    max_hold_bars=int(levels["hold"][index]),
                )
            )
    return configs


def ready(feature: Feature) -> bool:
    values = (
        feature.atr, feature.atr_ratio, feature.adx, feature.plus_di, feature.minus_di,
        feature.ema50, feature.ema200, feature.macd_hist, feature.rsi, feature.cci,
        feature.bb_upper, feature.bb_lower, feature.bb_width_percentile,
    )
    return all(value is not None and math.isfinite(float(value)) for value in values)


def regime(feature: Feature, candidate: TreeConfig) -> str:
    """Layer 1, mutually exclusive and candidate-configurable."""
    if not ready(feature):
        return "UNREADY"
    assert feature.atr is not None and feature.adx is not None
    assert feature.ema50 is not None and feature.ema200 is not None
    assert feature.plus_di is not None and feature.minus_di is not None
    separation = abs(feature.ema50 - feature.ema200) / feature.atr if feature.atr > 1e-12 else 0.0
    if feature.adx >= candidate.trend_adx_min and separation >= candidate.trend_ema_separation_atr:
        if feature.ema50 > feature.ema200 and feature.bar.close > feature.ema200 and feature.plus_di > feature.minus_di:
            return "BULL"
        if feature.ema50 < feature.ema200 and feature.bar.close < feature.ema200 and feature.minus_di > feature.plus_di:
            return "BEAR"
    if feature.adx <= candidate.range_adx_max and separation <= candidate.range_ema_separation_atr:
        return "RANGE"
    return "TRANSITION"


def context_matches(candidate: TreeConfig, regime_name: str) -> bool:
    return (
        (candidate.context == "BULL_PULLBACK" and regime_name == "BULL")
        or (candidate.context == "BEAR_PULLBACK" and regime_name == "BEAR")
        or (candidate.context == "BULL_BREAKOUT" and regime_name == "BULL")
        or (candidate.context == "BEAR_BREAKOUT" and regime_name == "BEAR")
        or (candidate.context == "RANGE_REVERSION" and regime_name == "RANGE")
    )


def execution_ready(feature: Feature, candidate: TreeConfig) -> bool:
    """Layer 0/2: closed-bar time, cost floor, and candidate volatility range."""
    if not ready(feature):
        return False
    assert feature.atr is not None and feature.atr_ratio is not None
    decision = feature.bar.decision_time
    return (
        7 <= decision.hour < 20
        and feature.atr >= config.MIN_ATR_USD
        and candidate.atr_ratio_min <= feature.atr_ratio <= candidate.atr_ratio_max
    )


def vwap_ok(feature: Feature, direction: str, candidate: TreeConfig) -> bool:
    if not candidate.require_vwap:
        return True
    if feature.vwap is None or feature.vwap_observations < 12 or feature.atr is None:
        return False
    bar = feature.bar
    if candidate.setup == "pullback":
        return bar.low <= feature.vwap < bar.close if direction == "LONG" else bar.high >= feature.vwap > bar.close
    distance = candidate.vwap_distance_atr * feature.atr
    if candidate.setup == "breakout":
        return bar.close - feature.vwap >= distance if direction == "LONG" else feature.vwap - bar.close >= distance
    # A range fade seeks a sufficiently distant VWAP in the direction of its
    # expected reversion, rather than confirmation in the breakout direction.
    return feature.vwap - bar.close >= distance if direction == "LONG" else bar.close - feature.vwap >= distance


def trigger_mode_ok(candidate: TreeConfig, *, rsi: bool, cci: bool, macd: bool) -> bool:
    """Require exactly the pre-declared two-or-three indicator confirmation set."""
    requirements = {
        "RSI_MACD": (rsi, macd),
        "RSI_CCI": (rsi, cci),
        "CCI_MACD": (cci, macd),
        "ALL_THREE": (rsi, cci, macd),
    }
    try:
        return all(requirements[candidate.trigger_mode])
    except KeyError as exc:  # makes a malformed audit config fail loudly
        raise ValueError(f"Unknown trigger mode: {candidate.trigger_mode}") from exc


def pullback_signal(candidate: TreeConfig, current: Feature, previous: Feature) -> Optional[Signal]:
    direction = candidate.direction
    assert direction in ("LONG", "SHORT")
    assert current.atr is not None and current.rsi is not None and current.cci is not None and current.macd_hist is not None
    assert current.ema50 is not None and previous.ema50 is not None
    assert previous.rsi is not None and previous.cci is not None and previous.macd_hist is not None
    bar, prior = current.bar, previous.bar
    if direction == "LONG":
        touched = prior.low <= previous.ema50 + candidate.ema_touch_atr * current.atr and bar.low <= current.ema50 + candidate.ema_touch_atr * current.atr
        base = touched and bar.close > current.ema50 and bar.close > bar.open
        rsi_ok = previous.rsi <= candidate.rsi_level and current.rsi >= candidate.rsi_reclaim
        cci_ok = previous.cci <= candidate.cci_level < current.cci
        macd_ok = current.macd_hist > previous.macd_hist
        triggered = base and trigger_mode_ok(candidate, rsi=rsi_ok, cci=cci_ok, macd=macd_ok)
        if candidate.require_confirmation_break:
            triggered = triggered and bar.close > prior.high
    else:
        touched = prior.high >= previous.ema50 - candidate.ema_touch_atr * current.atr and bar.high >= current.ema50 - candidate.ema_touch_atr * current.atr
        base = touched and bar.close < current.ema50 and bar.close < bar.open
        rsi_ok = previous.rsi >= 100.0 - candidate.rsi_level and current.rsi <= 100.0 - candidate.rsi_reclaim
        cci_ok = previous.cci >= -candidate.cci_level > current.cci
        macd_ok = current.macd_hist < previous.macd_hist
        triggered = base and trigger_mode_ok(candidate, rsi=rsi_ok, cci=cci_ok, macd=macd_ok)
        if candidate.require_confirmation_break:
            triggered = triggered and bar.close < prior.low
    return Signal(candidate, direction) if triggered and vwap_ok(current, direction, candidate) else None


def breakout_signal(candidate: TreeConfig, current: Feature, previous: Feature) -> Optional[Signal]:
    direction = candidate.direction
    assert direction in ("LONG", "SHORT")
    assert current.atr is not None and current.rsi is not None and current.cci is not None and current.macd_hist is not None
    assert current.bb_upper is not None and current.bb_lower is not None
    assert previous.bb_upper is not None and previous.bb_lower is not None
    assert previous.bb_width_percentile is not None and previous.macd_hist is not None
    bar, prior = current.bar, previous.bar
    compressed = previous.bb_width_percentile <= candidate.bb_width_percentile_max
    if direction == "LONG":
        base = (
            compressed and prior.close <= previous.bb_upper and bar.close > current.bb_upper
            and bar.high - bar.low >= candidate.breakout_range_atr * current.atr
        )
        rsi_ok, cci_ok = current.rsi >= candidate.rsi_level, current.cci >= candidate.cci_level
        macd_ok = current.macd_hist > 0.0 >= previous.macd_hist
    else:
        base = (
            compressed and prior.close >= previous.bb_lower and bar.close < current.bb_lower
            and bar.high - bar.low >= candidate.breakout_range_atr * current.atr
        )
        rsi_ok, cci_ok = current.rsi <= 100.0 - candidate.rsi_level, current.cci <= -candidate.cci_level
        macd_ok = current.macd_hist < 0.0 <= previous.macd_hist
    triggered = base and trigger_mode_ok(candidate, rsi=rsi_ok, cci=cci_ok, macd=macd_ok)
    return Signal(candidate, direction) if triggered and vwap_ok(current, direction, candidate) else None


def reversion_signal(candidate: TreeConfig, current: Feature, previous: Feature) -> Optional[Signal]:
    assert current.rsi is not None and current.cci is not None and current.macd_hist is not None
    assert current.bb_upper is not None and current.bb_lower is not None
    assert previous.rsi is not None and previous.cci is not None and previous.macd_hist is not None
    assert previous.bb_upper is not None and previous.bb_lower is not None
    bar, prior = current.bar, previous.bar
    long_base = prior.close <= previous.bb_lower and bar.low <= current.bb_lower and bar.close > current.bb_lower and bar.close > bar.open
    long_rsi = previous.rsi <= candidate.rsi_level and current.rsi >= candidate.rsi_reclaim
    long_cci = previous.cci <= -candidate.cci_level < current.cci
    long_macd = current.macd_hist > previous.macd_hist
    short_base = prior.close >= previous.bb_upper and bar.high >= current.bb_upper and bar.close < current.bb_upper and bar.close < bar.open
    short_rsi = previous.rsi >= 100.0 - candidate.rsi_level and current.rsi <= 100.0 - candidate.rsi_reclaim
    short_cci = previous.cci >= candidate.cci_level > current.cci
    short_macd = current.macd_hist < previous.macd_hist
    if long_base and trigger_mode_ok(candidate, rsi=long_rsi, cci=long_cci, macd=long_macd) and vwap_ok(current, "LONG", candidate):
        return Signal(candidate, "LONG")
    if short_base and trigger_mode_ok(candidate, rsi=short_rsi, cci=short_cci, macd=short_macd) and vwap_ok(current, "SHORT", candidate):
        return Signal(candidate, "SHORT")
    return None


def signal_for(candidate: TreeConfig, current: Feature, previous: Feature) -> Optional[Signal]:
    """Evaluate all tree layers in their decision order for one candidate."""
    if not execution_ready(current, candidate):
        return None
    if not context_matches(candidate, regime(current, candidate)):
        return None
    if candidate.setup == "pullback":
        return pullback_signal(candidate, current, previous)
    if candidate.setup == "breakout":
        return breakout_signal(candidate, current, previous)
    if candidate.setup == "reversion":
        return reversion_signal(candidate, current, previous)
    raise ValueError(f"Unknown setup: {candidate.setup}")


def open_position(signal: Signal, feature: Feature, balance: float, spread: float, fee_rate: float, slippage: float) -> Optional[Position]:
    assert feature.atr is not None
    candidate = signal.config
    half = spread / 2.0
    reference = feature.bar.close
    entry = reference + half + slippage if signal.direction == "LONG" else reference - half - slippage
    cost_floor = max(spread * 2.0, config.ROUND_TRIP_COST_USD) * config.MIN_SL_COST_MULTIPLE
    stop_distance = max(config.MIN_SL_USD, candidate.stop_atr * feature.atr, cost_floor)
    dollar_risk = balance * config.RISK_PER_TRADE_PCT / 100.0
    size = round(dollar_risk / stop_distance, 4)
    if size < 0.01:
        return None
    margin_cap = balance * config.MARGIN_CAP_PCT / 100.0
    if entry * size / config.MAX_LEVERAGE > margin_cap:
        size = round(margin_cap * config.MAX_LEVERAGE / entry, 4)
        if size < 0.01:
            return None
    fee = entry * size * fee_rate
    if entry * size / config.MAX_LEVERAGE + fee > balance:
        return None
    if signal.direction == "LONG":
        stop, target = entry - stop_distance, entry + candidate.target_rr * stop_distance
    else:
        stop, target = entry + stop_distance, entry - candidate.target_rr * stop_distance
    return Position(candidate, feature.bar.decision_time, signal.direction, entry, stop, target, size, fee, stop_distance)


def resolve_exit(position: Position, bar: Bar, spread: float, slippage: float) -> Optional[Tuple[float, str]]:
    """Next-bar OHLC execution with conservative stop priority."""
    position.bars_held += 1
    half = spread / 2.0
    if position.direction == "LONG":
        executable_low, executable_high = bar.low - half, bar.high - half
        stop_hit, target_hit = executable_low <= position.stop, executable_high >= position.target
        position.ambiguous_ohlc_exit = stop_hit and target_hit
        if stop_hit:
            return min(position.stop, executable_low) - slippage, "SL_HIT"
        if target_hit:
            return position.target - slippage, "TP_HIT"
    else:
        executable_low, executable_high = bar.low + half, bar.high + half
        stop_hit, target_hit = executable_high >= position.stop, executable_low <= position.target
        position.ambiguous_ohlc_exit = stop_hit and target_hit
        if stop_hit:
            return max(position.stop, executable_high) + slippage, "SL_HIT"
        if target_hit:
            return position.target + slippage, "TP_HIT"
    return None


def adverse_close(position: Position, bar: Bar, spread: float, slippage: float) -> float:
    half = spread / 2.0
    return bar.close - half - slippage if position.direction == "LONG" else bar.close + half + slippage


def close_position(position: Position, bar: Bar, exit_price: float, reason: str, balance: float, fee_rate: float, fold: str) -> Tuple[Trade, float]:
    gross = (exit_price - position.entry) * position.size if position.direction == "LONG" else (position.entry - exit_price) * position.size
    exit_fee = exit_price * position.size * fee_rate
    net = gross - position.entry_fee - exit_fee
    balance = max(0.0, balance + net)
    return Trade(
        position.config.config_id, position.config.context, fold, position.opened_at, bar.decision_time,
        position.direction, position.entry, exit_price, position.size, gross, position.entry_fee,
        exit_fee, net, reason, position.bars_held, position.ambiguous_ohlc_exit, balance,
    ), balance


def simulate(
    features: Sequence[Feature],
    candidates: Sequence[TreeConfig],
    start: datetime,
    end: datetime,
    label: str,
    starting_balance: float,
    spread: float,
    fee_rate: float,
    slippage: float,
    gap_guard: Optional[GapGuard],
    skip_conflicts: bool,
) -> Simulation:
    """Simulate a single config or a frozen cross-context policy.

    A multi-candidate call represents a policy fold.  It holds only one position
    account-wide and intentionally skips a bar with multiple signals rather
    than using an arbitrary tie-breaker.
    """
    if not candidates:
        return Simulation("NO_TRADE", "NO_TRADE", label, start, end, starting_balance, starting_balance, 0, 0, 0, 0, 0.0, [])
    balance = starting_balance
    peak = balance
    max_drawdown = 0.0
    daily_counts: Dict[str, int] = {}
    daily_pnl: Dict[str, float] = {}
    cooldown_until: Optional[datetime] = None
    position: Optional[Position] = None
    trades: List[Trade] = []
    signals = suppressed = blocked = conflicts = 0
    last_feature: Optional[Feature] = None

    for index in range(1, len(features)):
        current, previous = features[index], features[index - 1]
        decision = current.bar.decision_time
        if decision < start or decision >= end:
            continue
        last_feature = current
        if position is not None:
            outcome = resolve_exit(position, current.bar, spread, slippage)
            if outcome is None and gap_guard is not None and gap_guard.force_flat_after(current.bar.timestamp):
                outcome = (adverse_close(position, current.bar, spread, slippage), "DATA_GAP_EXIT")
            if outcome is None and decision.hour >= 21:
                outcome = (adverse_close(position, current.bar, spread, slippage), "DAY_EXIT")
            if outcome is None and position.bars_held >= position.config.max_hold_bars:
                outcome = (adverse_close(position, current.bar, spread, slippage), "TIME_EXIT")
            if outcome is not None:
                exit_price, reason = outcome
                trade, balance = close_position(position, current.bar, exit_price, reason, balance, fee_rate, label)
                trades.append(trade)
                peak = max(peak, balance)
                max_drawdown = max(max_drawdown, peak - balance)
                day = decision.date().isoformat()
                daily_pnl[day] = daily_pnl.get(day, 0.0) + trade.net_pnl
                cooldown = config.LOSS_COOLDOWN_SECONDS if trade.net_pnl < 0.0 else config.ENTRY_COOLDOWN_SECONDS
                cooldown_until = decision + timedelta(seconds=cooldown)
                position = None

        candidates_now = [signal for candidate in candidates if (signal := signal_for(candidate, current, previous)) is not None]
        signals += len(candidates_now)
        if position is not None:
            suppressed += len(candidates_now)
            continue
        if not candidates_now or balance < 5.0:
            continue
        if skip_conflicts and len(candidates_now) > 1:
            conflicts += len(candidates_now)
            continue
        # Single-config training has exactly one signal here. The policy's
        # multiple-signal branch is skipped above, so this is deterministic.
        signal = candidates_now[0]
        day = decision.date().isoformat()
        risk_block = (
            (gap_guard is not None and not gap_guard.entry_allowed(current.bar.timestamp))
            or (cooldown_until is not None and decision < cooldown_until)
            or daily_counts.get(day, 0) >= config.MAX_TRADES_PER_DAY
            or daily_pnl.get(day, 0.0) <= -starting_balance * config.MAX_DAILY_LOSS_PCT / 100.0
        )
        if risk_block:
            blocked += 1
            continue
        position = open_position(signal, current, balance, spread, fee_rate, slippage)
        if position is None:
            blocked += 1
            continue
        daily_counts[day] = daily_counts.get(day, 0) + 1

    if position is not None and last_feature is not None:
        trade, balance = close_position(position, last_feature.bar, adverse_close(position, last_feature.bar, spread, slippage), "FOLD_END_EXIT", balance, fee_rate, label)
        trades.append(trade)
        peak = max(peak, balance)
        max_drawdown = max(max_drawdown, peak - balance)

    sole = candidates[0]
    return Simulation(
        sole.config_id if len(candidates) == 1 else "ADAPTIVE_POLICY",
        sole.context if len(candidates) == 1 else "MULTI_CONTEXT",
        label, start, end, starting_balance, balance, signals, suppressed, blocked, conflicts, max_drawdown, trades,
    )


def profit_factor(trades: Sequence[Trade]) -> Optional[float]:
    wins = sum(trade.net_pnl for trade in trades if trade.net_pnl > 0.0)
    losses = abs(sum(trade.net_pnl for trade in trades if trade.net_pnl < 0.0))
    return wins / losses if losses else None


def assessment(
    config: TreeConfig,
    fold: str,
    train: Simulation,
    min_training_trades: int,
    min_segment_trades: int,
    stability_segments: int,
) -> CandidateAssessment:
    """Score a candidate from larger history and multiple chronological checks."""
    segment_width = (train.end - train.start) / stability_segments
    segment_pfs: List[float] = []
    for index in range(stability_segments):
        segment_start = train.start + segment_width * index
        segment_end = train.start + segment_width * (index + 1)
        sample = [trade for trade in train.trades if segment_start <= trade.closed_at < segment_end]
        if len(sample) >= min_segment_trades:
            value = profit_factor(sample)
            if value is not None:
                segment_pfs.append(value)
    full_pf = train.profit_factor
    worst = min(segment_pfs) if segment_pfs else None
    eligible = (
        len(train.trades) >= min_training_trades
        and train.net_pnl > 0.0
        and full_pf is not None
        and full_pf >= 1.10
        # Evidence must occur across at least two time slices.  This stops a
        # large aggregate N concentrated in one brief market episode from
        # masquerading as regime robustness.
        and len(segment_pfs) >= 2
        and worst is not None
        and worst >= 0.80
    )
    score = min(full_pf, worst) + len(train.trades) / 1_000_000.0 if eligible and worst is not None else None
    return CandidateAssessment(config, fold, train.start, train.end, len(train.trades), train.net_pnl, full_pf, worst, eligible, score)


def select(assessments: Sequence[CandidateAssessment], fold: str, context: str, train_start: datetime, train_end: datetime, test_start: datetime, test_end: datetime) -> Selection:
    eligible = [item for item in assessments if item.eligible]
    if not eligible:
        return Selection(fold, context, train_start, train_end, test_start, test_end, None, "NO_TRADE: no candidate met count, profitability, PF, and stability gates", None)
    winner = sorted(eligible, key=lambda item: (float(item.score or -math.inf), item.net_pnl, item.trades), reverse=True)[0]
    return Selection(fold, context, train_start, train_end, test_start, test_end, winner.config, "selected from past-only sensitivity bank", winner)


def add_months(value: datetime, months: int) -> datetime:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    # All rebalance dates use day 1, but keep this helper generally safe.
    day = min(value.day, 28)
    return value.replace(year=year, month=month, day=day)


def rolling_folds(last_decision: datetime) -> List[Tuple[str, datetime, datetime, datetime, datetime]]:
    """January/July folds with *all* prior canonical history at each selection."""
    folds: List[Tuple[str, datetime, datetime, datetime, datetime]] = []
    test_start = VALIDATION_START
    while test_start <= last_decision:
        test_end = min(add_months(test_start, 6), last_decision + timedelta(minutes=5))
        fold = f"{test_start.strftime('%Y-%m')} to {(test_end - timedelta(minutes=5)).strftime('%Y-%m')}"
        folds.append((fold, RESEARCH_START, test_start, test_start, test_end))
        test_start = add_months(test_start, 6)
    return folds


def period_summary(name: str, simulations: Sequence[Simulation], start: datetime, end: datetime) -> Dict[str, object]:
    relevant = [simulation for simulation in simulations if simulation.start >= start and simulation.start < end]
    if not relevant:
        return {"period": name, "folds": 0, "trades": 0, "start_balance": "", "end_balance": "", "return_pct": "", "profit_factor": "", "fees": "", "max_dd": ""}
    trades = [trade for simulation in relevant for trade in simulation.trades]
    start_balance, end_balance = relevant[0].starting_balance, relevant[-1].ending_balance
    pf = profit_factor(trades)
    return {
        "period": name,
        "folds": len(relevant),
        "trades": len(trades),
        "start_balance": round(start_balance, 6),
        "end_balance": round(end_balance, 6),
        "return_pct": round((end_balance / start_balance - 1.0) * 100.0, 6) if start_balance else "",
        "profit_factor": round(pf, 6) if pf is not None else "",
        "fees": round(sum(simulation.fees for simulation in relevant), 6),
        "max_dd": round(max(simulation.max_drawdown for simulation in relevant), 6),
    }


def write_csv(path: Path, rows: Sequence[Dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_configs(path: Path, configs: Sequence[TreeConfig]) -> None:
    rows = []
    for candidate in configs:
        row = asdict(candidate)
        row["parameters_json"] = candidate.parameter_json()
        rows.append(row)
    write_csv(path, rows)


def write_trade_csv(path: Path, trades: Sequence[Trade]) -> None:
    """Always create a valid audit file, even when the learner chooses no trade."""
    fields = [
        "config_id", "context", "fold", "opened_at_utc", "closed_at_utc", "direction", "entry", "exit", "size_oz",
        "gross_pnl_usd", "entry_fee_usd", "exit_fee_usd", "net_pnl_usd", "exit_reason", "bars_held",
        "ambiguous_ohlc_exit", "balance_after",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(trade.row() for trade in trades)


def pf_text(value: object) -> str:
    if value in (None, ""):
        return "n/a"
    return f"{float(value):.2f}"


def markdown_policy_table(simulations: Sequence[Simulation]) -> List[str]:
    lines = [
        "| Fold | Test window | Contexts traded | Signals | Trades | Start | End | Return | PF | Max DD | Conflicts skipped |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for simulation in simulations:
        learned = len({trade.context for trade in simulation.trades})
        lines.append(
            f"| {simulation.label} | {simulation.start.date()} → {(simulation.end - timedelta(minutes=5)).date()} | {learned} | "
            f"{simulation.candidate_signals} | {len(simulation.trades)} | ${simulation.starting_balance:.2f} | ${simulation.ending_balance:.2f} | "
            f"{simulation.return_pct:+.2f}% | {pf_text(simulation.profit_factor)} | ${simulation.max_drawdown:.2f} | {simulation.conflicts} |"
        )
    return lines


def sensitivity_overview(
    assessments: Sequence[CandidateAssessment], selections: Sequence[Selection], min_training_trades: int
) -> List[str]:
    """Render enough evidence to distinguish sparse lucky PF from eligibility."""
    selected_contexts = {selection.context for selection in selections if selection.config is not None}
    lines = [
        "| Context | Candidate-fold evaluations | Largest training N | Positive-net evaluations | Best full PF (N) | Passes N/PF/PnL pre-stability | Selected in any fold? |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for context, _, _ in CONTEXTS:
        items = [item for item in assessments if item.config.context == context]
        best_pf_item = max(
            (item for item in items if item.profit_factor is not None),
            key=lambda item: float(item.profit_factor or -math.inf),
            default=None,
        )
        best_pf = (
            f"{float(best_pf_item.profit_factor):.2f} ({best_pf_item.trades})"
            if best_pf_item is not None and best_pf_item.profit_factor is not None
            else "n/a"
        )
        base_gate_passes = sum(
            item.trades >= min_training_trades
            and item.net_pnl > 0.0
            and item.profit_factor is not None
            and item.profit_factor >= 1.10
            for item in items
        )
        lines.append(
            f"| `{context}` | {len(items)} | {max((item.trades for item in items), default=0)} | "
            f"{sum(item.net_pnl > 0.0 for item in items)} | {best_pf} | {base_gate_passes} | "
            f"{'yes' if context in selected_contexts else 'no'} |"
        )
    return lines


def make_report(
    path: Path,
    bars: Sequence[Bar],
    source_hash: str,
    configs: Sequence[TreeConfig],
    assessments: Sequence[CandidateAssessment],
    selections: Sequence[Selection],
    policy: Sequence[Simulation],
    summaries: Sequence[Dict[str, object]],
    guard: Optional[GapGuard],
    args: argparse.Namespace,
) -> None:
    source_counts = Counter(bar.source for bar in bars)
    no_trade = sum(selection.config is None for selection in selections)
    learned = len(selections) - no_trade
    by_context = Counter(selection.context for selection in selections if selection.config is not None)
    lines = [
        "# Adaptive layered regime-tree — larger-evidence sensitivity study (XAU)",
        "",
        "## What ‘learn’ means here",
        "",
        "This is the larger-sample follow-up to the original adaptive-tree study; the earlier study is retained unchanged. The machine does not infer a single magic setting and it does not modify the Railway bot. At each January/July decision point it evaluates a fixed, bounded candidate bank using only preceding candles, selects at most one configuration for each context, and freezes it for the next six-month forward window. A branch with insufficient evidence learns **NO_TRADE**.",
        "",
        "## Layered decision tree",
        "",
        "```text",
        "closed canonical UTC M5 candle + gap/execution guard",
        "└─ L1 market regime (candidate thresholds): BULL / BEAR / RANGE / TRANSITION",
        "   └─ L2 volatility suitability (candidate ATR-ratio min/max)",
        "      └─ L3 location branch",
        "         ├─ bull/bear: EMA pullback (+ optional source-local VWAP reclaim)",
        "         ├─ bull/bear: Bollinger squeeze → breakout (+ optional VWAP confirmation)",
        "         └─ range: Bollinger extension → reversion (+ optional VWAP distance)",
        "            └─ L4 closed-bar trigger: a candidate-chosen two-of-three or three-of-three RSI / CCI / MACD confirmation set",
        "               └─ L5 candidate risk leaf: ATR stop, R multiple, max holding time",
        "```",
        "",
        "## Parameter sensitivity design",
        "",
        f"- Contexts: {', '.join(f'`{name}`' for name, _, _ in CONTEXTS)}.",
        f"- Candidate leaves: **{len(configs):,}** = {args.candidates_per_context} balanced fractional-factorial candidates × {len(CONTEXTS)} contexts.",
        "- Every candidate carries flexible thresholds for ADX trend/range classification, EMA separation in ATR, ATR-ratio min/max, EMA-touch tolerance, RSI/CCI levels, Bollinger compression, breakout range, VWAP requirement/distance, confirmation bar, two-of-three vs all-three indicator trigger mode, stop ATR, target R, and holding bars.",
        "- Per-leaf sample size is increased two ways: all earlier canonical history is available at each rebalance, and leaves may use a structured two-of-three RSI/CCI/MACD confirmation rather than always requiring all three. No leaf removes all momentum confirmation.",
        "- This is deliberately not an unbounded full Cartesian optimisation. All discrete levels are represented in each context; the deterministic bank is auditable in the configuration CSV. Expanding the search after seeing results would be a new experiment and requires new unseen data.",
        "",
        "## Selection guardrails",
        "",
        f"- Training lookback: expanding, from `{RESEARCH_START.date()}` through (but excluding) each rebalance; first forward fold begins 2023-01-01.",
        f"- Candidate selection: ≥{args.min_training_trades} training trades, positive net PnL after current costs, full training PF ≥1.10, and at least two of {args.stability_segments} chronological segments with ≥{args.min_segment_trades} trades; no sampled segment may have PF <0.80.",
        "- Rank: maximize the weaker of full-sample and worst sampled-segment PF; trade count only breaks ties. At most one candidate per context is selected.",
        "- Policy: one position account-wide; simultaneous context signals are skipped, never resolved with a hidden discretionary tie-break.",
        "- 2023–2024 is adaptive forward validation. 2025 onward is adaptive forward holdout: later folds may use earlier outcomes, never future holdout bars.",
        "",
        "## Data / execution assumptions",
        "",
        f"- Canonical UTC M5 bars: **{len(bars):,}**, {bars[0].timestamp.isoformat()} → {bars[-1].timestamp.isoformat()}.",
        f"- Provenance: {', '.join(f'`{source}` = {count:,}' for source, count in sorted(source_counts.items()))}.",
        f"- Input SHA-256 (file names + bytes): `{source_hash}`.",
        f"- Execution assumptions: ${args.spread:.2f} spread, ${args.slippage:.2f} adverse slippage/fill, {args.fee_rate * 100:.02f}% taker fee/side, 1% risk target, 35% margin cap, 3/day cap, daily-loss/cooldown controls, stop-first OHLC ambiguity.",
        "- VWAP is source-local and UTC-day anchored. It resets at M1-repair/M5-original seams because their volume scales are incompatible; it is not venue-certified VWAP or trade flow.",
        f"- Gap guard: {'enabled' if guard else 'disabled'}" + (f"; {guard.non_routine_gap_count} non-routine gaps block entries near the pre-gap bar and force flattening." if guard else "."),
        "",
        "## Forward adaptive-policy results",
        "",
        *markdown_policy_table(policy),
        "",
        "## Period summaries",
        "",
        "| Period | Folds | Trades | Start | End | Return | PF | Fees | Max fold DD |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for summary in summaries:
        lines.append(
            f"| {summary['period']} | {summary['folds']} | {summary['trades']} | "
            f"${float(summary['start_balance']):.2f} | ${float(summary['end_balance']):.2f} | "
            f"{float(summary['return_pct']):+.2f}% | {pf_text(summary['profit_factor'])} | "
            f"${float(summary['fees']):.2f} | ${float(summary['max_dd']):.2f} |"
        )
    lines.extend(
        ["", "## Sensitivity eligibility overview", "", *sensitivity_overview(assessments, selections, args.min_training_trades)]
    )
    lines.extend(
        [
            "",
            f"A high PF with a small training N is intentionally not promoted: every selected leaf needs at least {args.min_training_trades} observations plus the full net-PnL and multi-segment stability gates above.",
            "",
            "## Learned branch activity",
            "",
            f"- Selected branch instances: **{learned} / {len(selections)}**. NO_TRADE instances: **{no_trade} / {len(selections)}**.",
            "- Selections by context: " + (", ".join(f"`{context}` = {count}" for context, count in sorted(by_context.items())) if by_context else "none") + ".",
            "- Exact past-only candidate metrics and selected flags are in the sensitivity CSV; fold/context configurations and NO_TRADE reasons are in the selection CSV.",
            "",
            "## Interpretation boundary",
            "",
            "This study can reject a flexible architecture or identify a candidate for additional scrutiny. It cannot establish a deployable ‘profit maker’: historical bid/ask, fill sequencing, funding, actual Apex multiplier/minimum order rules, mark/index behaviour, and real venue fees remain unavailable. No result enables live trading. A positive adaptive validation/holdout result would still need a new forward-paper period with the configuration frozen before it can be considered further.",
            "",
            f"Artifacts: [`{Path(args.configs_csv).name}`]({Path(args.configs_csv).name}) · [`{Path(args.sensitivity_csv).name}`]({Path(args.sensitivity_csv).name}) · [`{Path(args.selections_csv).name}`]({Path(args.selections_csv).name}) · [`{Path(args.policy_trades_csv).name}`]({Path(args.policy_trades_csv).name}).",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", nargs="+", help="canonical provenance-labelled UTC M5 CSV file(s) or globs")
    parser.add_argument("--candidates-per-context", type=int, default=18, help="broader candidate bank; does not replace per-leaf evidence gates")
    parser.add_argument("--min-training-trades", type=int, default=40, help="minimum historical trades for a selected leaf")
    parser.add_argument("--min-segment-trades", type=int, default=5, help="minimum trades for a chronological stability segment")
    parser.add_argument("--stability-segments", type=int, default=4, help="equal chronological training segments for robustness checks")
    parser.add_argument("--spread", type=float, default=0.40)
    parser.add_argument("--slippage", type=float, default=0.03)
    parser.add_argument("--fee-rate", type=float, default=0.0004)
    parser.add_argument("--gap-guard", action="store_true")
    parser.add_argument("--report", default="XAU_ADAPTIVE_REGIME_TREE_LARGE_SAMPLE.md")
    parser.add_argument("--configs-csv", default="XAU_ADAPTIVE_REGIME_TREE_LARGE_SAMPLE_CONFIGS.csv")
    parser.add_argument("--sensitivity-csv", default="XAU_ADAPTIVE_REGIME_TREE_LARGE_SAMPLE_SENSITIVITY.csv")
    parser.add_argument("--selections-csv", default="XAU_ADAPTIVE_REGIME_TREE_LARGE_SAMPLE_SELECTIONS.csv")
    parser.add_argument("--policy-trades-csv", default="XAU_ADAPTIVE_REGIME_TREE_LARGE_SAMPLE_TRADES.csv")
    args = parser.parse_args()
    if args.candidates_per_context < 12:
        parser.error("--candidates-per-context must be at least 12")
    if args.min_training_trades < 20 or args.min_segment_trades < 3 or args.stability_segments < 2:
        parser.error("sample-size settings must be at least 20 training trades, 3 segment trades, and 2 segments")
    if args.spread < 0.0 or args.slippage < 0.0 or args.fee_rate < 0.0:
        parser.error("cost inputs must be non-negative")

    paths = expand_paths(args.csv)
    bars = load_canonical_bars([str(path) for path in paths])
    features = build_features(bars)
    guard = GapGuard(bars) if args.gap_guard else None
    configs = candidate_bank(args.candidates_per_context)
    config_by_context: Dict[str, List[TreeConfig]] = {}
    for candidate in configs:
        config_by_context.setdefault(candidate.context, []).append(candidate)
    folds = rolling_folds(features[-1].bar.decision_time)

    assessments: List[CandidateAssessment] = []
    selections: List[Selection] = []
    policy: List[Simulation] = []
    balance = float(config.INITIAL_BALANCE_USDT)
    for fold, train_start, train_end, test_start, test_end in folds:
        frozen_configs: List[TreeConfig] = []
        for context, candidates in sorted(config_by_context.items()):
            context_assessments: List[CandidateAssessment] = []
            for candidate in candidates:
                train = simulate(
                    features, [candidate], train_start, train_end, f"TRAIN {fold}", float(config.INITIAL_BALANCE_USDT),
                    args.spread, args.fee_rate, args.slippage, guard, skip_conflicts=False,
                )
                item = assessment(
                    candidate, fold, train, args.min_training_trades, args.min_segment_trades, args.stability_segments
                )
                assessments.append(item)
                context_assessments.append(item)
            choice = select(context_assessments, fold, context, train_start, train_end, test_start, test_end)
            selections.append(choice)
            if choice.config is not None:
                frozen_configs.append(choice.config)
        policy_result = simulate(
            features, frozen_configs, test_start, test_end, fold, balance,
            args.spread, args.fee_rate, args.slippage, guard, skip_conflicts=True,
        )
        policy.append(policy_result)
        balance = policy_result.ending_balance
        chosen = ", ".join(candidate.config_id for candidate in frozen_configs) or "NO_TRADE"
        print(f"{fold}: learned {chosen}; policy trades={len(policy_result.trades)} end=${balance:.2f}")

    selected_ids = {(selection.fold, selection.context, selection.config.config_id) for selection in selections if selection.config is not None}
    sensitivity_rows = [item.row((item.fold, item.config.context, item.config.config_id) in selected_ids) for item in assessments]
    write_configs(Path(args.configs_csv), configs)
    write_csv(Path(args.sensitivity_csv), sensitivity_rows)
    write_csv(Path(args.selections_csv), [selection.row() for selection in selections])
    write_trade_csv(Path(args.policy_trades_csv), [trade for simulation in policy for trade in simulation.trades])
    summaries = (
        period_summary("Adaptive validation (2023-2024)", policy, VALIDATION_START, HOLDOUT_START),
        period_summary("Adaptive holdout (2025 onward)", policy, HOLDOUT_START, features[-1].bar.decision_time + timedelta(minutes=5)),
        period_summary("All adaptive forward folds", policy, VALIDATION_START, features[-1].bar.decision_time + timedelta(minutes=5)),
    )
    make_report(Path(args.report), bars, sha256_for_paths(paths), configs, assessments, selections, policy, summaries, guard, args)
    print(f"Wrote {len(configs)} configs, {len(assessments)} sensitivity rows, {len(selections)} selections, and {sum(len(item.trades) for item in policy)} forward trades.")


if __name__ == "__main__":
    main()
