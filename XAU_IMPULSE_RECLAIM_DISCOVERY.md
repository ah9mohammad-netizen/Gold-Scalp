# XAU impulse-pullback-reclaim discovery study

## Purpose

This study labels the gross structural behavior before another PnL strategy is built. A candidate is valuable only if it reaches material R multiples before its structural stop often enough to overcome the fixed cost model.

## Anti-look-ahead controls

- Source: 443,451 UTC M5 XAU bars. Higher timeframes are derived from complete M5 bars only.
- D1/H4/H1/M15 state changes become visible only at their parent close time.
- M5 entry can occur only after a later M5 close than the M15 reclaim close.
- Daily macro gate reads only the prior daily row; same-day DXY/VIX/oil closes and ex-post geopolitical labels are not allowed.
- Outcome: $0.40 fixed spread, $0.03 adverse slippage, stop-first intrabar ordering, 8-hour/21:00 UTC horizon.

## Structure definitions

- H1 impulse: true range exceeds the definition ATR multiple, closes in the top/bottom 25% of its range, and closes beyond the prior 20 H1 bars' high/low.
- M15 pullback: retraces the definition percentage of the impulse without invalidating its origin.
- M15 reclaim: closes through the pullback swing and on the correct side of M15 EMA20.
- M5 trigger: a later directional M5 close through the preceding M5 high/low.
- XAU data revision: `9229cd58ff171df61180c12e16fc35cc8b716343`.

## Outcome labels

| Definition | Subset | Candidates | +0.5R first | +1R first | +1.5R first | +2R first | Stop first | Median MFE R | Median MAE R |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `Standard: H1≥1.25ATR | PB 25%-60% | ≤240m` | All candidates | 93 | 38.7% | 18.3% | 11.8% | 10.8% | 38.7% | 0.28 | -0.75 |
| `Standard: H1≥1.25ATR | PB 25%-60% | ≤240m` | All candidates | 141 | 41.1% | 22.7% | 16.3% | 11.3% | 38.3% | 0.37 | -0.66 |
| `Standard: H1≥1.25ATR | PB 25%-60% | ≤240m` | All candidates | 95 | 47.4% | 31.6% | 22.1% | 17.9% | 47.4% | 0.45 | -0.94 |
| `Standard: H1≥1.25ATR | PB 25%-60% | ≤240m` | Prior-day stress allowed | 93 | 38.7% | 18.3% | 11.8% | 10.8% | 38.7% | 0.28 | -0.75 |
| `Standard: H1≥1.25ATR | PB 25%-60% | ≤240m` | Prior-day stress allowed | 141 | 41.1% | 22.7% | 16.3% | 11.3% | 38.3% | 0.37 | -0.66 |
| `Standard: H1≥1.25ATR | PB 25%-60% | ≤240m` | Prior-day stress allowed | 95 | 47.4% | 31.6% | 22.1% | 17.9% | 47.4% | 0.45 | -0.94 |
| `Conservative: H1≥1.5ATR | PB 25%-50% | ≤180m` | All candidates | 58 | 37.9% | 13.8% | 8.6% | 6.9% | 34.5% | 0.26 | -0.75 |
| `Conservative: H1≥1.5ATR | PB 25%-50% | ≤180m` | All candidates | 98 | 42.9% | 19.4% | 12.2% | 9.2% | 35.7% | 0.42 | -0.66 |
| `Conservative: H1≥1.5ATR | PB 25%-50% | ≤180m` | All candidates | 53 | 54.7% | 34.0% | 22.6% | 20.8% | 35.8% | 0.57 | -0.77 |
| `Conservative: H1≥1.5ATR | PB 25%-50% | ≤180m` | Prior-day stress allowed | 58 | 37.9% | 13.8% | 8.6% | 6.9% | 34.5% | 0.26 | -0.75 |
| `Conservative: H1≥1.5ATR | PB 25%-50% | ≤180m` | Prior-day stress allowed | 98 | 42.9% | 19.4% | 12.2% | 9.2% | 35.7% | 0.42 | -0.66 |
| `Conservative: H1≥1.5ATR | PB 25%-50% | ≤180m` | Prior-day stress allowed | 53 | 54.7% | 34.0% | 22.6% | 20.8% | 35.8% | 0.57 | -0.77 |

## Discovery gate

A definition is rejected before PnL optimisation unless it produces at least 30 development candidates, materially more +1R-before-stop outcomes than stop-first outcomes, and a meaningful number of +1.5R/+2R outcomes across both validation and holdout. This is a behavior test, not a search for one attractive backtest period.

All output rows are in [`XAU_IMPULSE_RECLAIM_DISCOVERY.csv`](XAU_IMPULSE_RECLAIM_DISCOVERY.csv).
