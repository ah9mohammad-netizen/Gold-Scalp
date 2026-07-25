# XAU daily macro-regime research

## Data and anti-look-ahead policy

- Price source: 451,906 XAU UTC five-minute bars; derived M15/H1/H4/D1 bars use completed M5 components only.
- Macro source: `oil_geopolitics.csv`, daily data from 2010-02-17 through 2026-03-12.
- Every intraday decision reads the latest macro row strictly before the decision date. Same-day DXY, VIX, and oil closes are unavailable by design.
- The explicit geopolitical-event labels are retained as descriptive data only in this phase. They are not used as a live-tradable veto because a daily event label may only be known after an unexpected event occurs.
- Costs: $0.40 spread, $0.03 adverse slippage per fill, 0.04% fee per side.
- Base strategy frozen: D1/H4/H1 EMA50 trend, M15 EMA50 pullback, M5 trigger, 2R target, 21:00 UTC force-flat. Only the daily macro gate changes.
- Policies are predeclared: DXY 5-day direction agreement; stress veto using prior VIX >25, absolute prior WTI return >3%, or a WTI 7-day volatility shock above 1.5x its 30-day baseline.
- XAU data revision: `canonical-utc-m1-repaired-local`.

## Development-only macro comparison

| Macro policy | Trades | W/L | Macro-vetoed entries | Final | Return | PF | DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| `No daily macro gate` | 299 | 102/197 | 0 | $25.15 | -74.85% | 0.50 | $75.23 |
| `DXY 5d direction` | 182 | 59/123 | 838 | $38.88 | -61.12% | 0.46 | $61.54 |
| `stress veto` | 133 | 41/92 | 1093 | $49.63 | -50.37% | 0.41 | $51.72 |
| `DXY 5d direction + stress veto` | 85 | 23/62 | 1501 | $55.46 | -44.54% | 0.31 | $44.91 |

## Frozen validation and holdout

| Macro policy | Trades | W/L | Macro-vetoed entries | Final | Return | PF | DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| `No daily macro gate` | 210 | 75/135 | 0 | $35.94 | -64.06% | 0.53 | $64.06 |
| `No daily macro gate` | 210 | 75/135 | 0 | $35.94 | -64.06% | 0.53 | $64.06 |
| `No daily macro gate` | 161 | 56/105 | 0 | $34.18 | -65.82% | 0.42 | $66.04 |
| `No daily macro gate` | 161 | 56/105 | 0 | $34.18 | -65.82% | 0.42 | $66.04 |

## Decision rule

Development selected `No daily macro gate` under the 20-trade minimum. It is rejected unless both later windows achieve adequate trade count and net PF above 1 after the same fixed costs. A macro gate may reject poor environments; it cannot create a viable entry edge from an invalid base strategy.

All results are in [`XAU_DAILY_MACRO_REGIME_CANONICAL.csv`](XAU_DAILY_MACRO_REGIME_CANONICAL.csv).
