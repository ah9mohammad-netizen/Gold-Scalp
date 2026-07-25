# v5 parameter research — critical walk-forward test

## Protocol

- Data: 443,451 supplied 5-minute bars; source timestamps treated as UTC.
- Fixed execution assumption: $0.40 spread, $0.03 adverse slippage per fill, 0.04% taker fee per side.
- Development window: 2019-09 through 2022-12. Validation and 2025+ holdout were not used to select parameters.
- Rank rule: at least 8 development trades, then profit factor, then net PnL. A candidate with too few trades is not allowed to win on an infinite/undefined PF.
- Data revision: `9229cd58ff171df61180c12e16fc35cc8b716343`.

## Step 1 — regime and entry threshold candidates

| Candidate | Trades | Final | Return | PF | DD |
|---|---:|---:|---:|---:|---:|
| `Z2.4|ADX≤20|SL2.5ATR|TP2R|07-17|turn|off` | 10 | $94.20 | -5.80% | 0.45 | $7.62 |
| `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off` | 15 | $86.74 | -13.26% | 0.27 | $16.54 |
| `Z2.2|ADX≤20|SL2.5ATR|TP2R|07-17|turn|off` | 30 | $75.61 | -24.39% | 0.26 | $26.09 |
| `Z2.6|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off` | 1 | $101.73 | +1.73% | n/a | $0.00 |
| `Z2.8|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off` | 1 | $101.73 | +1.73% | n/a | $0.00 |
| `Z2.4|ADX≤14|SL2.5ATR|TP2R|07-17|turn|off` | 0 | $100.00 | +0.00% | n/a | $0.00 |
| `Z2.6|ADX≤14|SL2.5ATR|TP2R|07-17|turn|off` | 0 | $100.00 | +0.00% | n/a | $0.00 |
| `Z2.4|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off` | 4 | $96.34 | -3.66% | 0.31 | $5.30 |
| `Z2.2|ADX≤14|SL2.5ATR|TP2R|07-17|turn|off` | 3 | $94.79 | -5.21% | 0.00 | $5.21 |

## Step 2 — session candidates using the step-1 development winner

| Candidate | Trades | Final | Return | PF | DD |
|---|---:|---:|---:|---:|---:|
| `Z2.4|ADX≤20|SL2.5ATR|TP2R|12-17|turn|off` | 8 | $97.29 | -2.71% | 0.64 | $6.26 |
| `Z2.4|ADX≤20|SL2.5ATR|TP2R|13-17|turn|off` | 8 | $97.29 | -2.71% | 0.64 | $6.26 |
| `Z2.4|ADX≤20|SL2.5ATR|TP2R|07-17|turn|off` | 10 | $94.20 | -5.80% | 0.45 | $7.62 |
| `Z2.4|ADX≤20|SL2.5ATR|TP2R|08-16|turn|off` | 8 | $94.39 | -5.61% | 0.36 | $7.44 |
| `Z2.4|ADX≤20|SL2.5ATR|TP2R|07-12|turn|off` | 2 | $96.82 | -3.18% | 0.00 | $3.18 |
| `Z2.4|ADX≤20|SL2.5ATR|TP2R|12-16|turn|off` | 7 | $95.69 | -4.31% | 0.42 | $6.16 |

## Step 3 — exit and breakeven candidates using the step-2 development winner

| Candidate | Trades | Final | Return | PF | DD |
|---|---:|---:|---:|---:|---:|
| `Z2.4|ADX≤20|SL3ATR|TP1.5R|12-17|turn|BE1R` | 11 | $98.65 | -1.35% | 0.82 | $3.82 |
| `Z2.4|ADX≤20|SL2.5ATR|TP2R|12-17|turn|BE1R` | 8 | $98.76 | -1.24% | 0.80 | $4.82 |
| `Z2.4|ADX≤20|SL2.5ATR|TP2R|12-17|turn|BE1.5R` | 8 | $98.21 | -1.79% | 0.73 | $5.36 |
| `Z2.4|ADX≤20|SL2.5ATR|TP2R|12-17|turn|off` | 8 | $97.29 | -2.71% | 0.64 | $6.26 |
| `Z2.4|ADX≤20|SL3ATR|TP1.5R|12-17|turn|off` | 11 | $95.87 | -4.13% | 0.59 | $6.57 |
| `Z2.4|ADX≤20|SL3ATR|TP2R|12-17|turn|off` | 11 | $95.00 | -5.00% | 0.57 | $8.38 |
| `Z2.4|ADX≤20|SL2ATR|TP1.5R|12-17|turn|off` | 3 | $103.55 | +3.55% | n/a | $0.00 |
| `Z2.4|ADX≤20|SL3ATR|TP1R|12-17|turn|off` | 3 | $102.35 | +2.35% | n/a | $0.00 |
| `Z2.4|ADX≤20|SL2ATR|TP2R|12-17|turn|off` | 3 | $101.63 | +1.63% | 1.96 | $1.70 |
| `Z2.4|ADX≤20|SL2.5ATR|TP1R|12-17|turn|off` | 1 | $100.76 | +0.76% | n/a | $0.00 |

## Frozen comparison on unseen windows

| Candidate | Trades | Final | Return | PF | DD |
|---|---:|---:|---:|---:|---:|
| `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off` | 9 | $105.31 | +5.31% | 2.13 | $2.95 |
| `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off` | 20 | $94.28 | -5.72% | 0.70 | $6.51 |
| `Z2.4|ADX≤20|SL3ATR|TP1.5R|12-17|turn|BE1R` | 8 | $90.47 | -9.53% | 0.10 | $9.53 |
| `Z2.4|ADX≤20|SL3ATR|TP1.5R|12-17|turn|BE1R` | 5 | $98.14 | -1.86% | 0.55 | $4.13 |

## Critical interpretation

The development-selected candidate is `Z2.4|ADX≤20|SL3ATR|TP1.5R|12-17|turn|BE1R`. It must not be treated as deployable unless it has acceptable validation and holdout results with adequate trade counts. This script is intentionally designed to make overfitting visible rather than hide it.

[`V5_PARAMETER_RESEARCH.csv`](V5_PARAMETER_RESEARCH.csv) contains every evaluated candidate and window. A negative or very small-sample validation/holdout result is a rejection of the change, not an invitation to keep searching the holdout set.
