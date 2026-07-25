# XAU 5-minute v5 cost-aware backtest

## Scope

- Source: supplied main-branch CSV parts (xau_canonical_repaired.csv).
- Data revision: `canonical-utc-m1-repaired-local`.
- Timestamp assumption: source `Date` field is treated as UTC; the CSV does not provide a timezone.
- Entry model: closed-candle signal, then adverse bid/ask fill plus slippage.
- Friction model: fixed $0.40 bid/ask spread, $0.03 adverse slippage **per fill**, and 0.04% taker fee **per side**.
- Exit model: first subsequent bar only; if stop and target both touch, stop is selected first.
- This is a research backtest of OHLC data, not a claim that the execution contract would have filled identically.

## Results

| Window | Bars | Closed trades | Final realized balance | Net return | PF | Net win rate | Max realized DD | Simulated fees |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Full sample | 451,906 | 52 | $80.71 | -19.29% | 0.5804 | 36.5% | $22.85 | $14.81 |
| Mid sample (2022-2023) | 141,387 | 2 | $100.23 | +0.23% | 1.153 | 50.0% | $1.50 | $0.51 |
| Recent / pseudo-OOS (2025-01 onward) | 76,677 | 24 | $92.08 | -7.92% | 0.6525 | 41.7% | $9.93 | $8.56 |

## Interpretation

The full sample closed 52 trades and ended at $80.71. This should be treated as a rejection/validation signal, not as a marketing result. The out-of-sample/recent window is more relevant than an optimized full-sample result.

Important limitations: the CSV has no bid/ask or funding data, timestamps lack a stated timezone, and the source series may not match the future execution venue's contract/index. Do not enable live trading based on this report. Forward paper performance and venue-specific fee/fill validation are still required.

## Machine-readable output

The companion JSON and trade-audit CSV contain every closed trade with entry/exit, gross PnL, fees, net PnL, Z-score, ADX, excursions, and balance after close.
