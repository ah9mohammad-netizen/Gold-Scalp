# Phase 2 — v6 regime-filter research

## Protocol

- Data: 451,906 main-branch 5-minute bars, treated as UTC because the source has no timezone field.
- Friction: $0.40 fixed spread, $0.03 adverse slippage per fill, 0.04% taker fee per side.
- Baseline entry/exit parameters are held fixed. Only one additional market-state gate changes per candidate unless the candidate label explicitly lists a combination.
- Candidate selection is development-only (2019-09 through 2022-12), with a minimum of eight development trades. Validation and holdout are frozen.
- Data revision: `canonical-utc-m1-repaired-local`.

## Why these filters were tested

The baseline audit found that 14 of 26 stopped trades never reversed by even 0.25R. The failure hypothesis is therefore continuation/news impulse, not merely a poor target. Each filter attempts to reject one version of that state using information available at the signal close:

| Filter | Long rejection condition | Short rejection condition |
|---|---|---|
| Opposing SMA slope | SMA20 fell too far over the prior 10 bars relative to ATR | SMA20 rose too far over the prior 10 bars relative to ATR |
| Signal-bar range | Current bar is too large relative to ATR | Same |
| Close-location value | Bullish turn closes weakly in its own range | Bearish turn closes weakly in its own range |
| Prior-20 close-inside | Close remains below the previous 20-bar low | Close remains above the previous 20-bar high |
| Relative volume | Signal bar has unusually high tick volume versus prior 20 bars | Same |

## Development-only results

| Candidate | Trades | Final | Net return | PF | Max DD |
|---|---:|---:|---:|---:|---:|
| `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off|bar≤1.25ATR` | 14 | $92.34 | -7.66% | 0.46 | $12.88 |
| `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off|vol≤1.5x` | 11 | $93.41 | -6.59% | 0.44 | $10.03 |
| `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off|bar≤1.5ATR` | 15 | $90.14 | -9.86% | 0.40 | $15.00 |
| `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off|vol≤2x` | 13 | $90.88 | -9.12% | 0.36 | $12.51 |
| `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off` | 17 | $87.93 | -12.07% | 0.35 | $16.88 |
| `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off|slope≤1` | 17 | $87.93 | -12.07% | 0.35 | $16.88 |
| `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off|bar≤2ATR` | 17 | $87.93 | -12.07% | 0.35 | $16.88 |
| `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off|inside20` | 17 | $87.93 | -12.07% | 0.35 | $16.88 |
| `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off|slope≤0.5+bar≤1.5ATR` | 9 | $91.97 | -8.03% | 0.30 | $11.40 |
| `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off|slope≤0.5+bar≤1.5ATR+inside20` | 9 | $91.97 | -8.03% | 0.30 | $11.40 |
| `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off|slope≤0.5` | 11 | $89.71 | -10.29% | 0.24 | $13.62 |
| `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off|slope≤0.5+bar≤1.5ATR+CLV≥0.6` | 2 | $96.95 | -3.05% | 0.00 | $3.05 |
| `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off|CLV≥0.6` | 7 | $93.58 | -6.42% | 0.20 | $6.42 |
| `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off|slope≤0.25` | 6 | $93.03 | -6.97% | 0.20 | $8.77 |
| `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off|CLV≥0.7` | 6 | $92.03 | -7.97% | 0.00 | $7.97 |

## Frozen unseen comparison

| Candidate | Trades | Final | Net return | PF | Max DD |
|---|---:|---:|---:|---:|---:|
| `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off` | 11 | $99.68 | -0.32% | 0.96 | $5.47 |
| `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off|bar≤1.25ATR` | 6 | $97.47 | -2.53% | 0.55 | $2.83 |
| `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off` | 24 | $92.08 | -7.92% | 0.65 | $9.93 |
| `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off|bar≤1.25ATR` | 20 | $91.60 | -8.40% | 0.58 | $10.07 |

## Decision rule

The development-selected filter is `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off|bar≤1.25ATR`. It is rejected unless both unseen windows show adequate trade count and net PF above 1 after the same cost assumptions. A favourable single period is not enough.

All rows, including filters that did not rank highly, are in [`V6_REGIME_FILTER_CANONICAL.csv`](V6_REGIME_FILTER_CANONICAL.csv).
