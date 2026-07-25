# MTF trend-pullback XAU research

## Model

- Source: 443,451 UTC five-minute XAU bars. M15, H1, H4 and D1 bars are derived internally from only completed M5 components.
- Trend layer: D1/H4/H1 close relative to selected EMA20/EMA50 values. Pullback: an M15 touch and close back on the trend side of its EMA. Trigger: M5 directional close beyond the preceding M5 high/low.
- Intraday lifecycle: new entries only 07:00–17:00 UTC; force-flat from 21:00 UTC / next UTC date; one trade per day.
- Execution: $0.40 spread, $0.03 adverse slippage per fill, 0.04% fee per side, SL-first ambiguity treatment.
- Stop: farther of M15 pullback extreme + $0.20 buffer or 1.5×M5 ATR. Target: 2.0R.
- Development selection is limited to 2019-09 through 2022-12. Validation and holdout remain frozen.
- Data revision: `9229cd58ff171df61180c12e16fc35cc8b716343`.

## Development-only comparison

| Variant | Trades | W/L | Time exits | Final | Return | PF | DD | Example M5 entries |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `D1|H4 EMA50|H1 EMA50|M15 EMA50` | 117 | 38/79 | 20 | $55.33 | -44.67% | 0.45 | $44.93 | 2020-08-19 12:25 UTC LONG<br>2020-08-31 08:45 UTC LONG<br>2020-09-10 12:55 UTC LONG<br>2020-09-11 15:45 UTC LONG<br>2020-09-15 16:45 UTC LONG |
| `no-D1|H4 EMA50|H1 EMA50|M15 EMA20` | 390 | 122/268 | 57 | $11.97 | -88.03% | 0.44 | $88.13 | 2019-09-27 16:15 UTC SHORT<br>2019-10-03 09:15 UTC LONG<br>2019-10-11 12:45 UTC SHORT<br>2019-10-23 16:55 UTC LONG<br>2019-10-29 13:45 UTC SHORT |
| `D1|H4 EMA50|H1 EMA50|M15 EMA20` | 160 | 48/112 | 30 | $40.95 | -59.05% | 0.43 | $61.63 | 2020-08-18 07:05 UTC LONG<br>2020-08-19 12:25 UTC LONG<br>2020-08-28 13:40 UTC LONG<br>2020-08-31 08:45 UTC LONG<br>2020-09-01 09:45 UTC LONG |
| `D1|H4 EMA20|H1 EMA20|M15 EMA20` | 149 | 43/106 | 25 | $40.01 | -59.99% | 0.39 | $62.50 | 2020-08-18 07:05 UTC LONG<br>2020-08-19 12:25 UTC LONG<br>2020-08-27 10:45 UTC LONG<br>2020-08-28 11:00 UTC LONG<br>2020-08-31 08:45 UTC LONG |

## Frozen validation and holdout

| Variant | Trades | W/L | Time exits | Final | Return | PF | DD | Example M5 entries |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `D1|H4 EMA50|H1 EMA50|M15 EMA20` | 202 | 64/138 | 30 | $28.86 | -71.14% | 0.42 | $71.14 | 2023-01-03 11:30 UTC LONG<br>2023-01-04 15:30 UTC LONG<br>2023-01-09 15:25 UTC LONG<br>2023-01-10 16:20 UTC LONG<br>2023-01-12 15:50 UTC LONG |
| `D1|H4 EMA50|H1 EMA50|M15 EMA50` | 162 | 50/112 | 23 | $36.49 | -63.51% | 0.47 | $65.16 | 2023-01-10 16:20 UTC LONG<br>2023-01-12 15:50 UTC LONG<br>2023-01-17 14:00 UTC LONG<br>2023-01-19 16:00 UTC LONG<br>2023-02-06 11:15 UTC SHORT |
| `D1|H4 EMA50|H1 EMA50|M15 EMA20` | 152 | 45/107 | 6 | $28.74 | -71.26% | 0.35 | $72.72 | 2025-01-07 13:30 UTC LONG<br>2025-01-08 08:15 UTC LONG<br>2025-01-09 10:35 UTC LONG<br>2025-01-10 09:30 UTC LONG<br>2025-01-13 10:35 UTC LONG |
| `D1|H4 EMA50|H1 EMA50|M15 EMA50` | 117 | 33/84 | 5 | $38.76 | -61.24% | 0.34 | $62.01 | 2025-01-03 08:10 UTC LONG<br>2025-01-08 08:15 UTC LONG<br>2025-01-10 15:15 UTC LONG<br>2025-01-13 10:35 UTC LONG<br>2025-01-16 09:15 UTC LONG |

## Decision rule

Development selected `D1|H4 EMA50|H1 EMA50|M15 EMA50` only if it met the 10-trade minimum and ranked best on development PF/return. It is rejected unless both unseen windows show sufficient trades and net PF above 1 after the same costs.

Every result is in [`MTF_TREND_PULLBACK_RESEARCH.csv`](MTF_TREND_PULLBACK_RESEARCH.csv).
