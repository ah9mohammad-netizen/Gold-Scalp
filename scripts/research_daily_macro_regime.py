#!/usr/bin/env python3
"""Phase 4B: daily macro-regime gates for the XAU MTF continuation model.

The macro source is a daily oil/geopolitics dataset supplied on ``main``. Only
values from the latest *prior* daily observation are visible to an intraday
XAU decision. Same-day DXY, VIX, and oil closes are never used, preventing
look-ahead bias.

This is a regime-gate study, not a macro forecast model. It tests whether
simple observable conditions can reject hostile XAU continuation entries:

* DXY five-trading-day direction agrees with gold direction;
* stress veto: prior VIX <= 25, no >3% prior-day WTI move, and WTI 7d
  volatility is not more than 1.5x its 30d baseline.

The base MTF entry/exit stays frozen. Development is 2019-2022, validation
2023-2024, and holdout 2025 onward.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.backtest_mtf_trend_pullback import (
    Result,
    Variant,
    aggregate,
    aggregate_daily,
    indicator_states,
    load_csv_parts,
    simulate,
)


@dataclass(frozen=True)
class MacroRow:
    date: date
    dxy: float
    vix: float
    wti_return: float
    wti_volatility_7d: float
    wti_volatility_30d: float


@dataclass(frozen=True)
class MacroPolicy:
    name: str
    require_dxy_direction: bool = False
    stress_veto: bool = False

    def label(self) -> str:
        pieces = []
        if self.require_dxy_direction:
            pieces.append("DXY 5d direction")
        if self.stress_veto:
            pieces.append("stress veto")
        return " + ".join(pieces) if pieces else "No daily macro gate"


@dataclass
class Evaluation:
    policy: MacroPolicy
    window: str
    result: Result

    def row(self) -> Dict[str, object]:
        row = asdict(self.policy)
        row.update(
            {
                "label": self.policy.label(),
                "window": self.window,
                "trades": self.result.trades,
                "wins": self.result.wins,
                "losses": self.result.losses,
                "time_exits": self.result.time_exits,
                "vetoed_entries": self.result.vetoed_entries,
                "final_balance": round(self.result.final_balance, 4),
                "return_pct": round(self.result.return_pct, 4),
                "profit_factor": self.result.profit_factor,
                "max_realized_drawdown": round(self.result.max_drawdown, 4),
                "fees": round(self.result.fees, 4),
            }
        )
        return row


class MacroHistory:
    def __init__(self, rows: Sequence[MacroRow]):
        self.rows = sorted(rows, key=lambda row: row.date)
        self.dates = [row.date for row in self.rows]

    def prior(self, timestamp: datetime) -> Optional[Tuple[MacroRow, Optional[float]]]:
        """Return latest row strictly before the XAU UTC decision date.

        This intentionally treats all daily close values as unknown until the
        following calendar day. On Monday, the latest available row will usually
        be Friday, which is the conservative choice for a daily source.
        """
        index = bisect.bisect_left(self.dates, timestamp.date()) - 1
        if index < 0:
            return None
        row = self.rows[index]
        dxy_5d = None
        if index >= 5 and self.rows[index - 5].dxy > 0:
            dxy_5d = row.dxy / self.rows[index - 5].dxy - 1.0
        return row, dxy_5d


def parse_float(row: Dict[str, str], name: str) -> float:
    try:
        return float(row[name])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {name} value in macro row: {row}") from exc


def load_macro(path: Path) -> MacroHistory:
    rows: List[MacroRow] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {
            "date",
            "dxy_index",
            "vix",
            "wti_return",
            "wti_volatility_7d",
            "wti_volatility_30d",
        }
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(f"Macro CSV must include {sorted(required)}")
        for raw in reader:
            rows.append(
                MacroRow(
                    date=datetime.strptime(raw["date"], "%Y-%m-%d").date(),
                    dxy=parse_float(raw, "dxy_index"),
                    vix=parse_float(raw, "vix"),
                    wti_return=parse_float(raw, "wti_return"),
                    wti_volatility_7d=parse_float(raw, "wti_volatility_7d"),
                    wti_volatility_30d=parse_float(raw, "wti_volatility_30d"),
                )
            )
    if not rows:
        raise ValueError("Macro CSV is empty")
    return MacroHistory(rows)


def make_gate(history: MacroHistory, policy: MacroPolicy):
    def allowed(timestamp: datetime, direction: str) -> bool:
        observation = history.prior(timestamp)
        if observation is None:
            return False
        row, dxy_5d = observation
        if policy.require_dxy_direction:
            if dxy_5d is None:
                return False
            if direction == "LONG" and dxy_5d >= 0:
                return False
            if direction == "SHORT" and dxy_5d <= 0:
                return False
        if policy.stress_veto:
            shock = row.wti_volatility_30d > 0 and row.wti_volatility_7d > 1.5 * row.wti_volatility_30d
            if row.vix > 25.0 or abs(row.wti_return) > 0.03 or shock:
                return False
        return True

    return allowed


def rank_development(evaluations: Sequence[Evaluation]) -> List[Evaluation]:
    def score(evaluation: Evaluation) -> Tuple[float, float, int]:
        result = evaluation.result
        if result.trades < 20:
            return (-1_000_000.0, result.return_pct, result.trades)
        pf = result.profit_factor if result.profit_factor is not None else 0.0
        return (pf, result.return_pct, result.trades)

    return sorted(evaluations, key=score, reverse=True)


def table(evaluations: Sequence[Evaluation]) -> List[str]:
    lines = [
        "| Macro policy | Trades | W/L | Macro-vetoed entries | Final | Return | PF | DD |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for evaluation in evaluations:
        result = evaluation.result
        pf = f"{result.profit_factor:.2f}" if result.profit_factor is not None else "n/a"
        lines.append(
            f"| `{evaluation.policy.label()}` | {result.trades} | {result.wins}/{result.losses} | "
            f"{result.vetoed_entries} | ${result.final_balance:.2f} | {result.return_pct:+.2f}% | "
            f"{pf} | ${result.max_drawdown:.2f} |"
        )
    return lines


def write_csv(path: Path, evaluations: Sequence[Evaluation]) -> None:
    rows = [evaluation.row() for evaluation in evaluations]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", nargs="+", help="UTC M5 XAU CSV paths or glob patterns")
    parser.add_argument("--macro", required=True, help="daily oil/geopolitics macro CSV")
    parser.add_argument("--spread", type=float, default=0.40)
    parser.add_argument("--report", default="XAU_DAILY_MACRO_REGIME_RESEARCH.md")
    parser.add_argument("--results-csv", default="XAU_DAILY_MACRO_REGIME_RESEARCH.csv")
    parser.add_argument("--data-revision", default="")
    args = parser.parse_args()
    if args.spread < 0:
        parser.error("spread must be non-negative")

    bars = load_csv_parts(args.csv)
    history = load_macro(Path(args.macro))
    m15 = indicator_states(aggregate(bars, 15))
    h1 = indicator_states(aggregate(bars, 60))
    h4 = indicator_states(aggregate(bars, 240))
    d1 = indicator_states(aggregate_daily(bars))
    trend_variant = Variant("Slow M15 pullback", True, 50, 50, 50)
    policies = [
        MacroPolicy("No macro gate"),
        MacroPolicy("DXY 5d direction", require_dxy_direction=True),
        MacroPolicy("Stress veto", stress_veto=True),
        MacroPolicy("DXY + stress", require_dxy_direction=True, stress_veto=True),
    ]
    windows = [
        ("Development (2019-09 to 2022-12)", datetime(2019, 9, 6, tzinfo=timezone.utc), datetime(2023, 1, 1, tzinfo=timezone.utc)),
        ("Validation (2023-2024)", datetime(2023, 1, 1, tzinfo=timezone.utc), datetime(2025, 1, 1, tzinfo=timezone.utc)),
        ("Holdout (2025 onward)", datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2026, 2, 1, tzinfo=timezone.utc)),
    ]

    def run(policy: MacroPolicy, window: Tuple[str, datetime, datetime]) -> Evaluation:
        name, start, end = window
        result = simulate(
            bars, m15, h1, h4, d1, trend_variant, start, end,
            args.spread, 0.20, 1.5, 2.0, 7, 17, 21, name,
            entry_allowed=make_gate(history, policy),
        )
        return Evaluation(policy, name, result)

    development = [run(policy, windows[0]) for policy in policies]
    ranked = rank_development(development)
    selected = ranked[0].policy
    unseen: List[Evaluation] = []
    for window in windows[1:]:
        unseen.append(run(policies[0], window))
        unseen.append(run(selected, window))
    all_evaluations = [*development, *unseen]
    write_csv(Path(args.results_csv), all_evaluations)

    report = [
        "# XAU daily macro-regime research",
        "",
        "## Data and anti-look-ahead policy",
        "",
        f"- Price source: {len(bars):,} XAU UTC five-minute bars; derived M15/H1/H4/D1 bars use completed M5 components only.",
        f"- Macro source: `{Path(args.macro).name}`, daily data from {history.rows[0].date.isoformat()} through {history.rows[-1].date.isoformat()}.",
        "- Every intraday decision reads the latest macro row strictly before the decision date. Same-day DXY, VIX, and oil closes are unavailable by design.",
        "- The explicit geopolitical-event labels are retained as descriptive data only in this phase. They are not used as a live-tradable veto because a daily event label may only be known after an unexpected event occurs.",
        f"- Costs: ${args.spread:.2f} spread, ${0.03:.2f} adverse slippage per fill, 0.04% fee per side.",
        "- Base strategy frozen: D1/H4/H1 EMA50 trend, M15 EMA50 pullback, M5 trigger, 2R target, 21:00 UTC force-flat. Only the daily macro gate changes.",
        "- Policies are predeclared: DXY 5-day direction agreement; stress veto using prior VIX >25, absolute prior WTI return >3%, or a WTI 7-day volatility shock above 1.5x its 30-day baseline.",
    ]
    if args.data_revision:
        report.append(f"- XAU data revision: `{args.data_revision}`.")
    report.extend(["", "## Development-only macro comparison", ""])
    report.extend(table(ranked))
    report.extend(["", "## Frozen validation and holdout", ""])
    report.extend(table(unseen))
    report.extend(
        [
            "",
            "## Decision rule",
            "",
            f"Development selected `{selected.label()}` under the 20-trade minimum. It is rejected unless both later windows achieve adequate trade count and net PF above 1 after the same fixed costs. A macro gate may reject poor environments; it cannot create a viable entry edge from an invalid base strategy.",
            "",
            f"All results are in [`{Path(args.results_csv).name}`]({Path(args.results_csv).name}).",
        ]
    )
    Path(args.report).write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"Development-selected macro policy: {selected.label()}")
    for evaluation in unseen:
        result = evaluation.result
        print(f"{evaluation.window} | {evaluation.policy.label()}: trades={result.trades} final=${result.final_balance:.2f} return={result.return_pct:+.2f}% PF={result.profit_factor}")


if __name__ == "__main__":
    main()
