# XAU 5-minute v5 cost-aware backtest

## Scope

- Source: supplied main-branch CSV parts (XAU_5m_data-part-011.csv, XAU_5m_data-part-012.csv, XAU_5m_data-part-013.csv, XAU_5m_data-part-014.csv, XAU_5m_data-part-015.csv).
- Data revision: `9229cd58ff171df61180c12e16fc35cc8b716343`.
- Timestamp assumption: source `Date` field is treated as UTC; the CSV does not provide a timezone.
- Entry model: closed-candle signal, then adverse bid/ask fill plus slippage.
- Friction model: fixed $0.40 bid/ask spread, $0.03 adverse slippage **per fill**, and 0.04% taker fee **per side**.
- Exit model: first subsequent bar only; if stop and target both touch, stop is selected first.
- This is a research backtest of OHLC data, not a claim that the execution contract would have filled identically.

## Results

| Window | Bars | Closed trades | Final realized balance | Net return | PF | Net win rate | Max realized DD | Simulated fees |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Full sample | 443,451 | 44 | $86.12 | -13.88% | 0.6516 | 40.9% | $16.54 | $13.85 |
| Mid sample (2022-2023) | 141,375 | 1 | $101.73 | +1.73% | n/a | 100.0% | $0.00 | $0.26 |
| Recent / pseudo-OOS (2025-01 onward) | 68,235 | 20 | $94.28 | -5.72% | 0.7038 | 45.0% | $6.51 | $7.57 |

## Interpretation

The full sample closed 44 trades and ended at $86.12. This should be treated as a rejection/validation signal, not as a marketing result. The out-of-sample/recent window is more relevant than an optimized full-sample result.

Important limitations: the CSV has no bid/ask or funding data, timestamps lack a stated timezone, and the source series may not match the future execution venue's contract/index. Do not enable live trading based on this report. Forward paper performance and venue-specific fee/fill validation are still required.

## Machine-readable output

The companion JSON file contains every closed trade with entry/exit, gross PnL, fees, net PnL, Z-score, ADX, and balance after close.
