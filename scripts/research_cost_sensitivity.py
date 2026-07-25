#!/usr/bin/env python3
"""Diagnose whether v5 failure is caused by execution assumptions alone.

Signals are frozen by keeping the decision spread/cost gate at $0.40 in every
scenario. Only simulated execution spread, fee rate, and slippage change.
This prevents a cost sensitivity study from quietly changing the signal set.

The study is diagnostic. A profitable zero-cost row is not a deployable
strategy; it only shows how much gross edge exists before real execution.
"""
from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import backtest_v5_csv as v5
from scripts.gap_guard import GapGuard


@dataclass(frozen=True)
class Scenario:
    name: str
    execution_spread: float
    fee_per_side: float
    slippage_per_fill: float

    def label(self) -> str:
        return (
            f"{self.name}: exec spread ${self.execution_spread:.2f}, "
            f"fee {self.fee_per_side * 100:.02f}%/side, slip ${self.slippage_per_fill:.2f}/fill"
        )


def write_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", nargs="+", help="canonical UTC M5 CSV paths or globs")
    parser.add_argument("--decision-spread", type=float, default=0.40)
    parser.add_argument("--report", default="XAU_COST_SENSITIVITY.md")
    parser.add_argument("--results-csv", default="XAU_COST_SENSITIVITY.csv")
    parser.add_argument("--data-revision", default="")
    args = parser.parse_args()
    if args.decision_spread < 0:
        parser.error("decision spread must be non-negative")

    bars = v5.load_csv_parts(args.csv)
    v5.bars_list = bars
    guard = GapGuard(bars)
    scenarios = [
        Scenario("Zero execution friction", 0.00, 0.0000, 0.00),
        Scenario("Low friction", 0.10, 0.0001, 0.01),
        Scenario("Moderate friction", 0.20, 0.0002, 0.02),
        Scenario("Current model", 0.40, 0.0004, 0.03),
    ]
    windows: List[Tuple[str, datetime | None, datetime | None]] = [
        ("Development (2019-09 to 2022-12)", datetime(2019, 9, 6, tzinfo=timezone.utc), datetime(2023, 1, 1, tzinfo=timezone.utc)),
        ("Validation (2023-2024)", datetime(2023, 1, 1, tzinfo=timezone.utc), datetime(2025, 1, 1, tzinfo=timezone.utc)),
        ("Holdout (2025 onward)", datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2026, 2, 1, tzinfo=timezone.utc)),
    ]
    rows: List[Dict[str, object]] = []
    for scenario in scenarios:
        for name, start, end in windows:
            result = v5.run_window(
                bars,
                start,
                end,
                args.decision_spread,
                gap_guard=guard,
                execution_spread=scenario.execution_spread,
                fee_rate=scenario.fee_per_side,
                slippage=scenario.slippage_per_fill,
            )
            rows.append(
                {
                    "scenario": scenario.name,
                    "execution_spread": scenario.execution_spread,
                    "fee_per_side": scenario.fee_per_side,
                    "slippage_per_fill": scenario.slippage_per_fill,
                    "window": name,
                    "trades": result["closed_trades"],
                    "final_balance": result["final_realized_balance"],
                    "return_pct": result["return_pct"],
                    "profit_factor": result["profit_factor"],
                    "win_rate_pct": result["win_rate_pct"],
                    "max_drawdown_usd": result["max_realized_drawdown_usd"],
                    "simulated_fees_usd": result["simulated_fees_usd"],
                }
            )
    write_csv(Path(args.results_csv), rows)
    report = [
        "# XAU v5 execution-cost sensitivity",
        "",
        "## Method",
        "",
        f"- Canonical UTC M5 source: {len(bars):,} bars with M1 repairs and universal gap guard.",
        f"- Signal-decision spread is frozen at ${args.decision_spread:.2f} in every scenario, so the decision/cost gate and signal set do not change.",
        "- Only simulated fill spread, fee per side, and adverse slippage change.",
        "- Zero-friction is a gross-edge diagnostic only; it is not an execution assumption or deployable result.",
    ]
    if args.data_revision:
        report.append(f"- Data revision: `{args.data_revision}`.")
    report.extend(
        [
            "",
            "## Results",
            "",
            "| Scenario | Window | Trades | Final | Return | PF | Win rate | Max DD | Fees |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in rows:
        pf = row["profit_factor"] if row["profit_factor"] is not None else "n/a"
        report.append(
            f"| `{row['scenario']}` | {row['window']} | {row['trades']} | ${float(row['final_balance']):.2f} | "
            f"{float(row['return_pct']):+.2f}% | {pf} | {float(row['win_rate_pct']):.1f}% | "
            f"${float(row['max_drawdown_usd']):.2f} | ${float(row['simulated_fees_usd']):.2f} |"
        )
    report.extend(
        [
            "",
            "## Interpretation rule",
            "",
            "If the zero-friction scenario is negative in development, validation, and holdout, the base signal has no gross edge and fee tuning cannot rescue it. If it is positive but realistic scenarios are negative, the strategy may be too low-frequency/low-expectancy for the venue and requires verified contract fees before a final conclusion.",
            "",
            f"Machine-readable results: [`{Path(args.results_csv).name}`]({Path(args.results_csv).name}).",
        ]
    )
    Path(args.report).write_text("\n".join(report) + "\n", encoding="utf-8")
    for row in rows:
        print(f"{row['scenario']} | {row['window']}: return={float(row['return_pct']):+.2f}% PF={row['profit_factor']}")


if __name__ == "__main__":
    main()
