# v5 parameter research — critical walk-forward test

## Protocol

- Data: 451,906 supplied 5-minute bars; source timestamps treated as UTC.
- Fixed execution assumption: $0.40 spread, $0.03 adverse slippage per fill, 0.04% taker fee per side.
- Development window: 2019-09 through 2022-12. Validation and 2025+ holdout were not used to select parameters.
- Rank rule: at least 8 development trades, then profit factor, then net PnL. A candidate with too few trades is not allowed to win on an infinite/undefined PF.
- Data revision: `canonical-utc-m1-repaired-local`.

## Step 1 — regime and entry threshold candidates

| Candidate | Trades | Final | Return | PF | DD |
|---|---:|---:|---:|---:|---:|
| `Z2.4|ADX≤20|SL2.5ATR|TP2R|07-17|turn|off` | 14 | $94.90 | -5.10% | 0.59 | $6.72 |
| `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off` | 17 | $87.93 | -12.07% | 0.35 | $16.88 |
| `Z2.2|ADX≤20|SL2.5ATR|TP2R|07-17|turn|off` | 38 | $75.25 | -24.75% | 0.34 | $26.03 |
| `Z2.8|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off` | 1 | $101.73 | +1.73% | n/a | $0.00 |
| `Z2.6|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off` | 2 | $100.48 | +0.48% | 1.39 | $1.24 |
| `Z2.6|ADX≤14|SL2.5ATR|TP2R|07-17|turn|off` | 0 | $100.00 | +0.00% | n/a | $0.00 |
| `Z2.4|ADX≤14|SL2.5ATR|TP2R|07-17|turn|off` | 1 | $98.64 | -1.36% | 0.00 | $1.36 |
| `Z2.4|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off` | 5 | $95.61 | -4.39% | 0.27 | $6.02 |
| `Z2.2|ADX≤14|SL2.5ATR|TP2R|07-17|turn|off` | 4 | $93.71 | -6.29% | 0.00 | $6.29 |

## Step 2 — session candidates using the step-1 development winner

| Candidate | Trades | Final | Return | PF | DD |
|---|---:|---:|---:|---:|---:|
| `Z2.4|ADX≤20|SL2.5ATR|TP2R|13-17|turn|off` | 10 | $101.02 | +1.02% | 1.15 | $2.72 |
| `Z2.4|ADX≤20|SL2.5ATR|TP2R|12-16|turn|off` | 12 | $97.55 | -2.45% | 0.76 | $4.53 |
| `Z2.4|ADX≤20|SL2.5ATR|TP2R|12-17|turn|off` | 13 | $96.22 | -3.78% | 0.67 | $5.84 |
| `Z2.4|ADX≤20|SL2.5ATR|TP2R|08-16|turn|off` | 13 | $96.22 | -3.78% | 0.67 | $5.42 |
| `Z2.4|ADX≤20|SL2.5ATR|TP2R|07-17|turn|off` | 14 | $94.90 | -5.10% | 0.59 | $6.72 |
| `Z2.4|ADX≤20|SL2.5ATR|TP2R|07-12|turn|off` | 1 | $98.63 | -1.37% | 0.00 | $1.37 |

## Step 3 — exit and breakeven candidates using the step-2 development winner

| Candidate | Trades | Final | Return | PF | DD |
|---|---:|---:|---:|---:|---:|
| `Z2.4|ADX≤20|SL2.5ATR|TP2R|13-17|turn|BE1R` | 10 | $101.58 | +1.58% | 1.26 | $2.17 |
| `Z2.4|ADX≤20|SL2.5ATR|TP2R|13-17|turn|off` | 10 | $101.02 | +1.02% | 1.15 | $2.72 |
| `Z2.4|ADX≤20|SL2.5ATR|TP2R|13-17|turn|BE1.5R` | 10 | $101.02 | +1.02% | 1.15 | $2.72 |
| `Z2.4|ADX≤20|SL2.5ATR|TP1.5R|13-17|turn|off` | 8 | $99.56 | -0.44% | 0.92 | $2.79 |
| `Z2.4|ADX≤20|SL3ATR|TP1.5R|13-17|turn|BE1R` | 13 | $99.03 | -0.97% | 0.88 | $4.43 |
| `Z2.4|ADX≤20|SL3ATR|TP1.5R|13-17|turn|off` | 13 | $97.43 | -2.57% | 0.73 | $5.03 |
| `Z2.4|ADX≤20|SL3ATR|TP2R|13-17|turn|off` | 13 | $96.73 | -3.27% | 0.70 | $4.96 |
| `Z2.4|ADX≤20|SL2ATR|TP1.5R|13-17|turn|off` | 5 | $100.87 | +0.87% | 1.33 | $1.39 |
| `Z2.4|ADX≤20|SL3ATR|TP1R|13-17|turn|off` | 5 | $99.75 | -0.25% | 0.90 | $1.32 |
| `Z2.4|ADX≤20|SL2.5ATR|TP1R|13-17|turn|off` | 2 | $99.53 | -0.47% | 0.62 | $1.24 |

## Frozen comparison on unseen windows

| Candidate | Trades | Final | Return | PF | DD |
|---|---:|---:|---:|---:|---:|
| `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off` | 11 | $99.68 | -0.32% | 0.96 | $5.47 |
| `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off` | 24 | $92.08 | -7.92% | 0.65 | $9.93 |
| `Z2.4|ADX≤20|SL2.5ATR|TP2R|13-17|turn|BE1R` | 0 | $100.00 | +0.00% | n/a | $0.00 |
| `Z2.4|ADX≤20|SL2.5ATR|TP2R|13-17|turn|BE1R` | 3 | $97.81 | -2.19% | 0.00 | $2.19 |

## Critical interpretation

The development-selected candidate is `Z2.4|ADX≤20|SL2.5ATR|TP2R|13-17|turn|BE1R`. It must not be treated as deployable unless it has acceptable validation and holdout results with adequate trade counts. This script is intentionally designed to make overfitting visible rather than hide it.

[`V5_PARAMETER_RESEARCH.csv`](V5_PARAMETER_RESEARCH.csv) contains every evaluated candidate and window. A negative or very small-sample validation/holdout result is a rejection of the change, not an invitation to keep searching the holdout set.
