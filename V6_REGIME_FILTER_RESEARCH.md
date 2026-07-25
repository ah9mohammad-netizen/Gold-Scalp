# Phase 2 — v6 regime-filter research

## Protocol

- Data: 443,451 main-branch 5-minute bars, treated as UTC because the source has no timezone field.
- Friction: $0.40 fixed spread, $0.03 adverse slippage per fill, 0.04% taker fee per side.
- Baseline entry/exit parameters are held fixed. Only one additional market-state gate changes per candidate unless the candidate label explicitly lists a combination.
- Candidate selection is development-only (2019-09 through 2022-12), with a minimum of eight development trades. Validation and holdout are frozen.
- Data revision: `9229cd58ff171df61180c12e16fc35cc8b716343`.

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
| `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off|bar≤1.25ATR` | 14 | $88.85 | -11.15% | 0.31 | $14.46 |
| `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off` | 15 | $86.74 | -13.26% | 0.27 | $16.54 |
| `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off|slope≤1` | 15 | $86.74 | -13.26% | 0.27 | $16.54 |
| `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off|bar≤1.5ATR` | 15 | $86.74 | -13.26% | 0.27 | $16.54 |
| `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off|bar≤2ATR` | 15 | $86.74 | -13.26% | 0.27 | $16.54 |
| `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off|inside20` | 15 | $86.74 | -13.26% | 0.27 | $16.54 |
| `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off|vol≤2x` | 11 | $89.98 | -10.02% | 0.25 | $11.82 |
| `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off|slope≤0.5` | 12 | $87.63 | -12.37% | 0.21 | $15.66 |
| `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off|slope≤0.5+bar≤1.5ATR` | 12 | $87.63 | -12.37% | 0.21 | $15.66 |
| `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off|slope≤0.5+bar≤1.5ATR+inside20` | 12 | $87.63 | -12.37% | 0.21 | $15.66 |
| `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off|slope≤0.25` | 8 | $89.74 | -10.26% | 0.15 | $12.05 |
| `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off|CLV≥0.6` | 5 | $95.94 | -4.06% | 0.29 | $4.36 |
| `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off|CLV≥0.7` | 3 | $95.65 | -4.35% | 0.00 | $4.35 |
| `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off|slope≤0.5+bar≤1.5ATR+CLV≥0.6` | 3 | $95.62 | -4.38% | 0.00 | $4.38 |
| `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off|vol≤1.5x` | 7 | $95.51 | -4.49% | 0.44 | $6.28 |

## Frozen unseen comparison

| Candidate | Trades | Final | Net return | PF | Max DD |
|---|---:|---:|---:|---:|---:|
| `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off` | 9 | $105.31 | +5.31% | 2.13 | $2.95 |
| `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off|bar≤1.25ATR` | 4 | $103.43 | +3.43% | 3.41 | $1.42 |
| `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off` | 20 | $94.28 | -5.72% | 0.70 | $6.51 |
| `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off|bar≤1.25ATR` | 17 | $92.66 | -7.34% | 0.59 | $7.34 |

## Decision rule

The development-selected filter is `Z2.2|ADX≤18|SL2.5ATR|TP2R|07-17|turn|off|bar≤1.25ATR`. It is rejected unless both unseen windows show adequate trade count and net PF above 1 after the same cost assumptions. A favourable single period is not enough.

All rows, including filters that did not rank highly, are in [`V6_REGIME_FILTER_RESEARCH.csv`](V6_REGIME_FILTER_RESEARCH.csv).
