# XAU impulse-pullback-reclaim discovery study

## Purpose

This study labels the gross structural behavior before another PnL strategy is built. A candidate is valuable only if it reaches material R multiples before its structural stop often enough to overcome the fixed cost model.

## Anti-look-ahead controls

- Source: 451,906 UTC M5 XAU bars. Higher timeframes are derived from complete M5 bars only.
- D1/H4/H1/M15 state changes become visible only at their parent close time.
- M5 entry can occur only after a later M5 close than the M15 reclaim close.
- Daily macro gate reads only the prior daily row; same-day DXY/VIX/oil closes and ex-post geopolitical labels are not allowed.
- Gap guard: 75 non-routine gaps; candidates are blocked near them and outcomes force-stop at the last known pre-gap bar.
- Outcome: $0.40 fixed spread, $0.03 adverse slippage, stop-first intrabar ordering, 8-hour/21:00 UTC horizon.

## Structure definitions

- H1 impulse: true range exceeds the definition ATR multiple, closes in the top/bottom 25% of its range, and closes beyond the prior 20 H1 bars' high/low.
- M15 pullback: retraces the definition percentage of the impulse without invalidating its origin.
- M15 reclaim: closes through the pullback swing and on the correct side of M15 EMA20.
- M5 trigger: a later directional M5 close through the preceding M5 high/low.
- XAU data revision: `canonical-utc-m1-repaired-local`.

## Outcome labels

| Definition | Subset | Candidates | +0.5R first | +1R first | +1.5R first | +2R first | Stop first | Median MFE R | Median MAE R |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `Standard: H1≥1.25ATR | PB 25%-60% | ≤240m` | All candidates | 157 | 48.4% | 32.5% | 24.2% | 19.7% | 38.9% | 0.49 | -0.76 |
| `Standard: H1≥1.25ATR | PB 25%-60% | ≤240m` | All candidates | 139 | 45.3% | 28.8% | 20.1% | 12.2% | 44.6% | 0.45 | -0.79 |
| `Standard: H1≥1.25ATR | PB 25%-60% | ≤240m` | All candidates | 125 | 56.0% | 41.6% | 28.8% | 23.2% | 49.6% | 0.75 | -0.97 |
| `Standard: H1≥1.25ATR | PB 25%-60% | ≤240m` | Prior-day stress allowed | 157 | 48.4% | 32.5% | 24.2% | 19.7% | 38.9% | 0.49 | -0.76 |
| `Standard: H1≥1.25ATR | PB 25%-60% | ≤240m` | Prior-day stress allowed | 139 | 45.3% | 28.8% | 20.1% | 12.2% | 44.6% | 0.45 | -0.79 |
| `Standard: H1≥1.25ATR | PB 25%-60% | ≤240m` | Prior-day stress allowed | 125 | 56.0% | 41.6% | 28.8% | 23.2% | 49.6% | 0.75 | -0.97 |
| `Conservative: H1≥1.5ATR | PB 25%-50% | ≤180m` | All candidates | 96 | 47.9% | 32.3% | 20.8% | 15.6% | 36.5% | 0.47 | -0.75 |
| `Conservative: H1≥1.5ATR | PB 25%-50% | ≤180m` | All candidates | 96 | 49.0% | 28.1% | 17.7% | 10.4% | 46.9% | 0.48 | -0.86 |
| `Conservative: H1≥1.5ATR | PB 25%-50% | ≤180m` | All candidates | 66 | 59.1% | 45.5% | 30.3% | 27.3% | 39.4% | 0.84 | -0.76 |
| `Conservative: H1≥1.5ATR | PB 25%-50% | ≤180m` | Prior-day stress allowed | 96 | 47.9% | 32.3% | 20.8% | 15.6% | 36.5% | 0.47 | -0.75 |
| `Conservative: H1≥1.5ATR | PB 25%-50% | ≤180m` | Prior-day stress allowed | 96 | 49.0% | 28.1% | 17.7% | 10.4% | 46.9% | 0.48 | -0.86 |
| `Conservative: H1≥1.5ATR | PB 25%-50% | ≤180m` | Prior-day stress allowed | 66 | 59.1% | 45.5% | 30.3% | 27.3% | 39.4% | 0.84 | -0.76 |

## Discovery gate

A definition is rejected before PnL optimisation unless it produces at least 30 development candidates, materially more +1R-before-stop outcomes than stop-first outcomes, and a meaningful number of +1.5R/+2R outcomes across both validation and holdout. This is a behavior test, not a search for one attractive backtest period.

All output rows are in [`XAU_IMPULSE_RECLAIM_CANONICAL.csv`](XAU_IMPULSE_RECLAIM_CANONICAL.csv).
