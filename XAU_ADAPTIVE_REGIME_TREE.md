# Adaptive layered regime-tree sensitivity study — XAU

## What ‘learn’ means here

The machine does not infer a single magic setting and it does not modify the Railway bot. At each January/July decision point it evaluates the fixed, bounded candidate bank using only preceding candles, selects at most one configuration for each decision-tree context, and then freezes that selection for the next six-month forward window. A branch with insufficient evidence learns **NO_TRADE**.

## Layered decision tree

```text
closed canonical UTC M5 candle + gap/execution guard
└─ L1 market regime (candidate thresholds): BULL / BEAR / RANGE / TRANSITION
   └─ L2 volatility suitability (candidate ATR-ratio min/max)
      └─ L3 location branch
         ├─ bull/bear: EMA pullback (+ optional source-local VWAP reclaim)
         ├─ bull/bear: Bollinger squeeze → breakout (+ optional VWAP confirmation)
         └─ range: Bollinger extension → reversion (+ optional VWAP distance)
            └─ L4 closed-bar trigger: MACD histogram + RSI + CCI + candle confirmation
               └─ L5 candidate risk leaf: ATR stop, R multiple, max holding time
```

## Parameter sensitivity design

- Contexts: `BULL_PULLBACK`, `BEAR_PULLBACK`, `BULL_BREAKOUT`, `BEAR_BREAKOUT`, `RANGE_REVERSION`.
- Candidate leaves: **60** = 12 balanced fractional-factorial candidates × 5 contexts.
- Every candidate carries flexible thresholds for ADX trend/range classification, EMA separation in ATR, ATR-ratio min/max, EMA-touch tolerance, RSI/CCI levels, Bollinger compression, breakout range, VWAP requirement/distance, confirmation bar, stop ATR, target R, and holding bars.
- This is deliberately not an unbounded full Cartesian optimisation. All discrete levels are represented in each context; the deterministic bank is auditable in the configuration CSV. Expanding the search after seeing results would be a new experiment and requires new unseen data.

## Selection guardrails

- Training lookback: up to 3 years ending exactly at each rebalance; first forward fold begins 2023-01-01.
- Candidate selection: ≥20 training trades, positive net PnL after current costs, full training PF ≥1.10, and no chronological third with ≥3 trades and PF <0.80.
- Rank: maximize the weaker of full-sample and worst sampled-third PF; trade count only breaks ties. At most one candidate per context is selected.
- Policy: one position account-wide; simultaneous context signals are skipped, never resolved with a hidden discretionary tie-break.
- 2023–2024 is adaptive forward validation. 2025 onward is adaptive forward holdout: later folds may use earlier outcomes, never future holdout bars.

## Data / execution assumptions

- Canonical UTC M5 bars: **451,906**, 2019-09-06T06:25:00+00:00 → 2026-01-30T21:55:00+00:00.
- Provenance: `M1_AGGREGATED` = 8,455, `M5_ORIGINAL` = 443,451.
- Input SHA-256 (file names + bytes): `9d9f28cef259308737578eca5de96d6d9610d83faf7fc597d4294c73ff07c40c`.
- Execution assumptions: $0.40 spread, $0.03 adverse slippage/fill, 0.04% taker fee/side, 1% risk target, 35% margin cap, 3/day cap, daily-loss/cooldown controls, stop-first OHLC ambiguity.
- VWAP is source-local and UTC-day anchored. It resets at M1-repair/M5-original seams because their volume scales are incompatible; it is not venue-certified VWAP or trade flow.
- Gap guard: enabled; 75 non-routine gaps block entries near the pre-gap bar and force flattening.

## Forward adaptive-policy results

| Fold | Test window | Contexts traded | Signals | Trades | Start | End | Return | PF | Max DD | Conflicts skipped |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2023-01 to 2023-06 | 2023-01-01 → 2023-06-30 | 0 | 0 | 0 | $100.00 | $100.00 | +0.00% | n/a | $0.00 | 0 |
| 2023-07 to 2023-12 | 2023-07-01 → 2023-12-31 | 0 | 0 | 0 | $100.00 | $100.00 | +0.00% | n/a | $0.00 | 0 |
| 2024-01 to 2024-06 | 2024-01-01 → 2024-06-30 | 0 | 0 | 0 | $100.00 | $100.00 | +0.00% | n/a | $0.00 | 0 |
| 2024-07 to 2024-12 | 2024-07-01 → 2024-12-31 | 0 | 0 | 0 | $100.00 | $100.00 | +0.00% | n/a | $0.00 | 0 |
| 2025-01 to 2025-06 | 2025-01-01 → 2025-06-30 | 0 | 0 | 0 | $100.00 | $100.00 | +0.00% | n/a | $0.00 | 0 |
| 2025-07 to 2025-12 | 2025-07-01 → 2025-12-31 | 0 | 0 | 0 | $100.00 | $100.00 | +0.00% | n/a | $0.00 | 0 |
| 2026-01 to 2026-01 | 2026-01-01 → 2026-01-30 | 0 | 0 | 0 | $100.00 | $100.00 | +0.00% | n/a | $0.00 | 0 |

## Period summaries

| Period | Folds | Trades | Start | End | Return | PF | Fees | Max fold DD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Adaptive validation (2023-2024) | 4 | 0 | $100.00 | $100.00 | +0.00% | n/a | $0.00 | $0.00 |
| Adaptive holdout (2025 onward) | 3 | 0 | $100.00 | $100.00 | +0.00% | n/a | $0.00 | $0.00 |
| All adaptive forward folds | 7 | 0 | $100.00 | $100.00 | +0.00% | n/a | $0.00 | $0.00 |

## Sensitivity eligibility overview

| Context | Candidate-fold evaluations | Largest training N | Positive-net evaluations | Best full PF (N) | Selected in any fold? |
|---|---:|---:|---:|---:|---|
| `BULL_PULLBACK` | 84 | 79 | 11 | 1.64 (3) | no |
| `BEAR_PULLBACK` | 84 | 39 | 4 | 0.95 (3) | no |
| `BULL_BREAKOUT` | 84 | 61 | 0 | 0.62 (26) | no |
| `BEAR_BREAKOUT` | 84 | 76 | 0 | 0.44 (54) | no |
| `RANGE_REVERSION` | 84 | 0 | 0 | n/a | no |

A high PF with a very small training N is intentionally not promoted: every selected leaf also needs the full count, net-PnL, and chronological-stability gates above.

## Learned branch activity

- Selected branch instances: **0 / 35**. NO_TRADE instances: **35 / 35**.
- Selections by context: none.
- Exact past-only candidate metrics and selected flags are in the sensitivity CSV; fold/context configurations and NO_TRADE reasons are in the selection CSV.

## Interpretation boundary

This study can reject a flexible architecture or identify a candidate for additional scrutiny. It cannot establish a deployable ‘profit maker’: historical bid/ask, fill sequencing, funding, actual Apex multiplier/minimum order rules, mark/index behaviour, and real venue fees remain unavailable. No result enables live trading. A positive adaptive validation/holdout result would still need a new forward-paper period with the configuration frozen before it can be considered further.

Artifacts: [`XAU_ADAPTIVE_REGIME_TREE_CONFIGS.csv`](XAU_ADAPTIVE_REGIME_TREE_CONFIGS.csv) · [`XAU_ADAPTIVE_REGIME_TREE_SENSITIVITY.csv`](XAU_ADAPTIVE_REGIME_TREE_SENSITIVITY.csv) · [`XAU_ADAPTIVE_REGIME_TREE_SELECTIONS.csv`](XAU_ADAPTIVE_REGIME_TREE_SELECTIONS.csv) · [`XAU_ADAPTIVE_REGIME_TREE_TRADES.csv`](XAU_ADAPTIVE_REGIME_TREE_TRADES.csv).
