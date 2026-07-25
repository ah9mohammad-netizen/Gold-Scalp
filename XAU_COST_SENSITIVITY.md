# XAU v5 execution-cost sensitivity

## Method

- Canonical UTC M5 source: 451,906 bars with M1 repairs and universal gap guard.
- Signal-decision spread is frozen at $0.40 in every scenario, so the decision/cost gate and signal set do not change.
- Only simulated fill spread, fee per side, and adverse slippage change.
- Zero-friction is a gross-edge diagnostic only; it is not an execution assumption or deployable result.
- Data revision: `canonical-utc-m1-repaired-local`.

## Results

| Scenario | Window | Trades | Final | Return | PF | Win rate | Max DD | Fees |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `Zero execution friction` | Development (2019-09 to 2022-12) | 17 | $92.42 | -7.58% | 0.4994 | 23.5% | $13.17 | $0.00 |
| `Zero execution friction` | Validation (2023-2024) | 11 | $102.60 | +2.60% | 1.3473 | 45.5% | $4.30 | $0.00 |
| `Zero execution friction` | Holdout (2025 onward) | 24 | $107.67 | +7.67% | 1.4645 | 50.0% | $3.44 | $0.00 |
| `Low friction` | Development (2019-09 to 2022-12) | 17 | $91.21 | -8.79% | 0.453 | 23.5% | $14.18 | $1.07 |
| `Low friction` | Validation (2023-2024) | 11 | $101.59 | +1.59% | 1.1988 | 45.5% | $4.86 | $0.89 |
| `Low friction` | Holdout (2025 onward) | 24 | $101.93 | +1.93% | 1.1031 | 45.8% | $3.48 | $2.26 |
| `Moderate friction` | Development (2019-09 to 2022-12) | 17 | $89.96 | -10.04% | 0.4108 | 23.5% | $15.23 | $2.13 |
| `Moderate friction` | Validation (2023-2024) | 11 | $101.24 | +1.24% | 1.1573 | 45.5% | $4.78 | $1.77 |
| `Moderate friction` | Holdout (2025 onward) | 24 | $96.29 | -3.71% | 0.8214 | 41.7% | $7.46 | $4.37 |
| `Current model` | Development (2019-09 to 2022-12) | 17 | $87.93 | -12.07% | 0.3487 | 23.5% | $16.88 | $4.21 |
| `Current model` | Validation (2023-2024) | 11 | $99.68 | -0.32% | 0.9619 | 45.5% | $5.47 | $3.52 |
| `Current model` | Holdout (2025 onward) | 24 | $92.08 | -7.92% | 0.6525 | 41.7% | $9.93 | $8.56 |

## Interpretation rule

If the zero-friction scenario is negative in development, validation, and holdout, the base signal has no gross edge and fee tuning cannot rescue it. If it is positive but realistic scenarios are negative, the strategy may be too low-frequency/low-expectancy for the venue and requires verified contract fees before a final conclusion.

Machine-readable results: [`XAU_COST_SENSITIVITY.csv`](XAU_COST_SENSITIVITY.csv).
