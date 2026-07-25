# XAU daily macro-regime research

## Data and anti-look-ahead policy

- Price source: 443,451 XAU UTC five-minute bars; derived M15/H1/H4/D1 bars use completed M5 components only.
- Macro source: `oil_geopolitics.csv`, daily data from 2010-02-17 through 2026-03-12.
- Every intraday decision reads the latest macro row strictly before the decision date. Same-day DXY, VIX, and oil closes are unavailable by design.
- The explicit geopolitical-event labels are retained as descriptive data only in this phase. They are not used as a live-tradable veto because a daily event label may only be known after an unexpected event occurs.
- Costs: $0.40 spread, $0.03 adverse slippage per fill, 0.04% fee per side.
- Base strategy frozen: D1/H4/H1 EMA50 trend, M15 EMA50 pullback, M5 trigger, 2R target, 21:00 UTC force-flat. Only the daily macro gate changes.
- Policies are predeclared: DXY 5-day direction agreement; stress veto using prior VIX >25, absolute prior WTI return >3%, or a WTI 7-day volatility shock above 1.5x its 30-day baseline.
- XAU data revision: `9229cd58ff171df61180c12e16fc35cc8b716343`.

## Development-only macro comparison

| Macro policy | Trades | W/L | Macro-vetoed entries | Final | Return | PF | DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| `stress veto` | 52 | 18/34 | 513 | $79.55 | -20.45% | 0.48 | $20.81 |
| `No daily macro gate` | 117 | 38/79 | 0 | $55.33 | -44.67% | 0.45 | $44.93 |
| `DXY 5d direction` | 58 | 16/42 | 435 | $67.28 | -32.72% | 0.34 | $32.74 |
| `DXY 5d direction + stress veto` | 27 | 7/20 | 691 | $79.95 | -20.05% | 0.25 | $20.07 |

## Frozen validation and holdout

| Macro policy | Trades | W/L | Macro-vetoed entries | Final | Return | PF | DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| `No daily macro gate` | 162 | 50/112 | 0 | $36.49 | -63.51% | 0.47 | $65.16 |
| `stress veto` | 137 | 42/95 | 168 | $41.62 | -58.38% | 0.45 | $58.38 |
| `No daily macro gate` | 117 | 33/84 | 0 | $38.76 | -61.24% | 0.34 | $62.01 |
| `stress veto` | 94 | 28/66 | 97 | $46.89 | -53.11% | 0.35 | $54.06 |

## Decision rule

Development selected `stress veto` under the 20-trade minimum. It is rejected unless both later windows achieve adequate trade count and net PF above 1 after the same fixed costs. A macro gate may reject poor environments; it cannot create a viable entry edge from an invalid base strategy.

All results are in [`XAU_DAILY_MACRO_REGIME_RESEARCH.csv`](XAU_DAILY_MACRO_REGIME_RESEARCH.csv).
