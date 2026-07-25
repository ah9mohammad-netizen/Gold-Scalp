#!/usr/bin/env python3
"""Phase 2: test non-overlapping regime filters for the v5 mean-reversion idea.

This is not an unconstrained optimiser. The filters are pre-specified from the
trade audit's failure mode (fading continuation), selected only on 2019-2022,
and then frozen for 2023-2024 validation and 2025+ holdout testing.

Filters tested:
  * directionally opposing 10-bar SMA20 slope;
  * abnormally large signal-bar range versus ATR;
  * close-location rejection strength;
  * close back inside the prior 20-bar range;
  * unusually high relative tick-volume exclusion.
"""
from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.optimize_v5_parameters import (
    Parameters,
    Result,
    build_features,
    load_csv_parts,
    rank_development,
    simulate,
)


Window = Tuple[str, datetime, datetime | None]


def render_table(results: Sequence[Result]) -> List[str]:
    lines = [
        "| Candidate | Trades | Final | Net return | PF | Max DD |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for result in results:
        pf = f"{result.pf:.2f}" if result.pf is not None else "n/a"
        lines.append(
            f"| `{result.params.label()}` | {result.trades} | ${result.final_balance:.2f} | "
            f"{result.return_pct:+.2f}% | {pf} | ${result.max_dd:.2f} |"
        )
    return lines


def write_csv(path: Path, results: Sequence[Result]) -> None:
    rows = [result.row() for result in results]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", nargs="+", help="CSV part paths or shell globs")
    parser.add_argument("--spread", type=float, default=0.40)
    parser.add_argument("--report", default="V6_REGIME_FILTER_RESEARCH.md")
    parser.add_argument("--results-csv", default="V6_REGIME_FILTER_RESEARCH.csv")
    parser.add_argument("--data-revision", default="")
    args = parser.parse_args()
    if args.spread < 0:
        parser.error("--spread must be non-negative")

    bars = load_csv_parts(args.csv)
    features = build_features(bars)
    windows: List[Window] = [
        (
            "Development (2019-09 to 2022-12)",
            datetime(2019, 9, 6, tzinfo=timezone.utc),
            datetime(2023, 1, 1, tzinfo=timezone.utc),
        ),
        (
            "Validation (2023-2024)",
            datetime(2023, 1, 1, tzinfo=timezone.utc),
            datetime(2025, 1, 1, tzinfo=timezone.utc),
        ),
        ("Holdout (2025 onward)", datetime(2025, 1, 1, tzinfo=timezone.utc), None),
    ]
    baseline = Parameters()

    # Every candidate keeps v5 entry/exit/risk settings. Only the added state
    # gate changes, making attribution of any effect possible.
    candidates = [
        baseline,
        Parameters(opposing_sma_slope_max_atr=0.25),
        Parameters(opposing_sma_slope_max_atr=0.50),
        Parameters(opposing_sma_slope_max_atr=1.00),
        Parameters(max_signal_bar_range_atr=1.25),
        Parameters(max_signal_bar_range_atr=1.50),
        Parameters(max_signal_bar_range_atr=2.00),
        Parameters(rejection_close_min=0.60),
        Parameters(rejection_close_min=0.70),
        Parameters(require_close_inside_prior20=True),
        Parameters(max_relative_volume=1.50),
        Parameters(max_relative_volume=2.00),
        Parameters(opposing_sma_slope_max_atr=0.50, max_signal_bar_range_atr=1.50),
        Parameters(
            opposing_sma_slope_max_atr=0.50,
            max_signal_bar_range_atr=1.50,
            rejection_close_min=0.60,
        ),
        Parameters(
            opposing_sma_slope_max_atr=0.50,
            max_signal_bar_range_atr=1.50,
            require_close_inside_prior20=True,
        ),
    ]

    _, development_start, development_end = windows[0]
    development = [
        simulate(features, candidate, development_start, development_end, args.spread, "Development")
        for candidate in candidates
    ]
    ranked = rank_development(development)
    selected = ranked[0].params

    all_results: List[Result] = development[:]
    unseen: List[Result] = []
    for label, start, end in windows[1:]:
        for params, name in ((baseline, "Baseline"), (selected, "Development-selected regime filter")):
            result = simulate(features, params, start, end, args.spread, f"{name} — {label}")
            unseen.append(result)
            all_results.append(result)
    write_csv(Path(args.results_csv), all_results)

    report = [
        "# Phase 2 — v6 regime-filter research",
        "",
        "## Protocol",
        "",
        f"- Data: {len(bars):,} main-branch 5-minute bars, treated as UTC because the source has no timezone field.",
        f"- Friction: ${args.spread:.2f} fixed spread, $0.03 adverse slippage per fill, 0.04% taker fee per side.",
        "- Baseline entry/exit parameters are held fixed. Only one additional market-state gate changes per candidate unless the candidate label explicitly lists a combination.",
        "- Candidate selection is development-only (2019-09 through 2022-12), with a minimum of eight development trades. Validation and holdout are frozen.",
    ]
    if args.data_revision:
        report.append(f"- Data revision: `{args.data_revision}`.")
    report.extend(
        [
            "",
            "## Why these filters were tested",
            "",
            "The baseline audit found that 14 of 26 stopped trades never reversed by even 0.25R. The failure hypothesis is therefore continuation/news impulse, not merely a poor target. Each filter attempts to reject one version of that state using information available at the signal close:",
            "",
            "| Filter | Long rejection condition | Short rejection condition |",
            "|---|---|---|",
            "| Opposing SMA slope | SMA20 fell too far over the prior 10 bars relative to ATR | SMA20 rose too far over the prior 10 bars relative to ATR |",
            "| Signal-bar range | Current bar is too large relative to ATR | Same |",
            "| Close-location value | Bullish turn closes weakly in its own range | Bearish turn closes weakly in its own range |",
            "| Prior-20 close-inside | Close remains below the previous 20-bar low | Close remains above the previous 20-bar high |",
            "| Relative volume | Signal bar has unusually high tick volume versus prior 20 bars | Same |",
            "",
            "## Development-only results",
            "",
        ]
    )
    report.extend(render_table(ranked))
    report.extend(
        [
            "",
            "## Frozen unseen comparison",
            "",
        ]
    )
    report.extend(render_table(unseen))
    report.extend(
        [
            "",
            "## Decision rule",
            "",
            f"The development-selected filter is `{selected.label()}`. It is rejected unless both unseen windows show adequate trade count and net PF above 1 after the same cost assumptions. A favourable single period is not enough.",
            "",
            f"All rows, including filters that did not rank highly, are in [`{Path(args.results_csv).name}`]({Path(args.results_csv).name}).",
        ]
    )
    Path(args.report).write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"Development-selected filter: {selected.label()}")
    for result in unseen:
        print(
            f"{result.window}: trades={result.trades} final=${result.final_balance:.2f} "
            f"return={result.return_pct:+.2f}% PF={result.pf}"
        )


if __name__ == "__main__":
    main()
