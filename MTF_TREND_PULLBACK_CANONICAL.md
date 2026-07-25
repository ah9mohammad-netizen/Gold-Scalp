# MTF trend-pullback XAU research

## Model

- Source: 451,906 UTC five-minute XAU bars. M15, H1, H4 and D1 bars are derived internally from only completed M5 components.
- Trend layer: D1/H4/H1 close relative to selected EMA20/EMA50 values. Pullback: an M15 touch and close back on the trend side of its EMA. Trigger: M5 directional close beyond the preceding M5 high/low.
- Intraday lifecycle: new entries only 07:00–17:00 UTC; force-flat from 21:00 UTC / next UTC date; one trade per day.
- Execution: $0.40 spread, $0.03 adverse slippage per fill, 0.04% fee per side, SL-first ambiguity treatment.
- Stop: farther of M15 pullback extreme + $0.20 buffer or 1.5×M5 ATR. Target: 2.0R.
- Development selection is limited to 2019-09 through 2022-12. Validation and holdout remain frozen.
- Gap guard: enabled; non-routine gaps are force-flattened/entry-blocked.
- Data revision: `canonical-utc-m1-repaired-local`.

## Development-only comparison

| Variant | Trades | W/L | Time / gap exits | Final | Return | PF | DD | Example M5 entries |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `D1|H4 EMA50|H1 EMA50|M15 EMA50` | 299 | 102/197 | 43/6 | $25.15 | -74.85% | 0.50 | $75.23 | 2019-11-01 14:25 UTC LONG<br>2019-11-07 07:30 UTC SHORT<br>2019-11-08 15:15 UTC SHORT<br>2020-01-06 14:30 UTC LONG<br>2020-01-07 07:25 UTC LONG |
| `no-D1|H4 EMA50|H1 EMA50|M15 EMA20` | 468 | 143/325 | 79/7 | $8.59 | -91.41% | 0.45 | $91.56 | 2019-09-23 14:00 UTC LONG<br>2019-09-27 13:15 UTC SHORT<br>2019-10-03 14:05 UTC LONG<br>2019-10-23 13:55 UTC LONG<br>2019-10-29 11:45 UTC SHORT |
| `D1|H4 EMA50|H1 EMA50|M15 EMA20` | 365 | 111/254 | 56/7 | $12.89 | -87.11% | 0.45 | $87.46 | 2019-10-29 11:45 UTC SHORT<br>2019-10-31 13:45 UTC LONG<br>2019-11-01 14:25 UTC LONG<br>2019-11-07 07:30 UTC SHORT<br>2019-12-04 13:20 UTC LONG |
| `D1|H4 EMA20|H1 EMA20|M15 EMA20` | 318 | 97/221 | 48/2 | $16.30 | -83.70% | 0.42 | $83.98 | 2019-10-29 11:45 UTC SHORT<br>2019-10-31 13:45 UTC LONG<br>2019-11-01 14:25 UTC LONG<br>2019-11-15 09:20 UTC SHORT<br>2019-12-04 13:20 UTC LONG |

## Frozen validation and holdout

| Variant | Trades | W/L | Time / gap exits | Final | Return | PF | DD | Example M5 entries |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `D1|H4 EMA50|H1 EMA50|M15 EMA20` | 241 | 85/156 | 42/1 | $29.21 | -70.79% | 0.50 | $70.82 | 2023-01-03 09:30 UTC LONG<br>2023-01-04 13:30 UTC LONG<br>2023-01-06 15:05 UTC LONG<br>2023-01-09 13:25 UTC LONG<br>2023-01-10 14:20 UTC LONG |
| `D1|H4 EMA50|H1 EMA50|M15 EMA50` | 210 | 75/135 | 38/1 | $35.94 | -64.06% | 0.53 | $64.06 | 2023-01-04 15:30 UTC LONG<br>2023-01-10 14:20 UTC LONG<br>2023-01-12 13:50 UTC LONG<br>2023-01-17 12:00 UTC LONG<br>2023-01-19 14:00 UTC LONG |
| `D1|H4 EMA50|H1 EMA50|M15 EMA20` | 187 | 60/127 | 5/1 | $28.47 | -71.53% | 0.43 | $73.18 | 2025-01-08 13:05 UTC LONG<br>2025-01-09 07:00 UTC LONG<br>2025-01-10 07:30 UTC LONG<br>2025-01-13 08:35 UTC LONG<br>2025-01-15 13:50 UTC LONG |
| `D1|H4 EMA50|H1 EMA50|M15 EMA50` | 161 | 56/105 | 11/2 | $34.18 | -65.82% | 0.42 | $66.04 | 2025-01-08 08:40 UTC LONG<br>2025-01-09 07:00 UTC LONG<br>2025-01-10 13:15 UTC LONG<br>2025-01-13 08:35 UTC LONG<br>2025-01-15 16:40 UTC LONG |

## Decision rule

Development selected `D1|H4 EMA50|H1 EMA50|M15 EMA50` only if it met the 10-trade minimum and ranked best on development PF/return. It is rejected unless both unseen windows show sufficient trades and net PF above 1 after the same costs.

Every result is in [`MTF_TREND_PULLBACK_CANONICAL.csv`](MTF_TREND_PULLBACK_CANONICAL.csv).
