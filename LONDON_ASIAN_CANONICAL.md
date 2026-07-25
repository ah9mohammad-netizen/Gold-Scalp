# Asian range / London session timezone research

## Method

- Data: 451,906 source 5-minute bars; timestamps explicitly treated as UTC.
- Asian range: 00:00 UTC through the listed cutoff; London window is either fixed UTC or `Europe/London` local time using IANA DST rules.
- Entry: sweep beyond Asian range by $0.40, then a 5-minute close back inside the range. One structural trade per UTC day.
- Stop: farther of 1.5 ATR from entry or $0.20 beyond the sweep extreme. Target: 2.0R.
- Cost: $0.40 spread, $0.03 adverse slippage per fill, and 0.04% taker fee per side.
- Position management begins on the bar after entry. If a subsequent OHLC bar touches both stop and target, stop is selected first.
- Timing choice is made only from development data; validation and holdout are frozen.
- Gap guard: enabled.
- Data revision: `canonical-utc-m1-repaired-local`.

## DST consequence

A London 08:00 local window begins at 08:00 UTC during GMT and 07:00 UTC during British Summer Time. The legacy fixed 07:00 UTC window therefore starts one hour too early during UK winter and is only aligned with London 08:00 during BST.

## Development-only timing comparison

| Timing / structure | Trades | Final | Return | PF | DD | Example entries |
|---|---:|---:|---:|---:|---:|---|
| `Asia 00:00-07:00 UTC | Europe/London 08:00-10:30 | no-EMA` | 37 | $77.99 | -22.01% | 0.41 | $27.27 | 2019-12-04 09:05 UTC / 09:05 GMT SHORT<br>2020-02-28 08:00 UTC / 08:00 GMT LONG<br>2020-03-13 08:00 UTC / 08:00 GMT SHORT<br>2020-03-16 09:30 UTC / 09:30 GMT LONG<br>2020-03-18 08:00 UTC / 08:00 GMT LONG |
| `Asia 00:00-06:30 UTC | Europe/London 08:00-10:30 | no-EMA` | 39 | $76.01 | -23.99% | 0.39 | $29.24 | 2019-12-04 09:05 UTC / 09:05 GMT SHORT<br>2020-02-28 08:00 UTC / 08:00 GMT LONG<br>2020-03-13 08:00 UTC / 08:00 GMT SHORT<br>2020-03-16 09:30 UTC / 09:30 GMT LONG<br>2020-03-17 08:35 UTC / 08:35 GMT LONG |
| `Asia 00:00-06:30 UTC | UTC 07:00-10:30 | no-EMA` | 46 | $72.79 | -27.21% | 0.38 | $34.92 | 2019-12-04 09:05 UTC / 09:05 GMT SHORT<br>2020-02-28 07:55 UTC / 07:55 GMT LONG<br>2020-03-13 07:40 UTC / 07:40 GMT SHORT<br>2020-03-16 09:30 UTC / 09:30 GMT LONG<br>2020-03-17 08:35 UTC / 08:35 GMT LONG |
| `Asia 00:00-06:30 UTC | Europe/London 08:00-11:00 | no-EMA` | 44 | $70.76 | -29.24% | 0.34 | $34.50 | 2019-12-04 09:05 UTC / 09:05 GMT SHORT<br>2020-02-28 08:00 UTC / 08:00 GMT LONG<br>2020-03-13 08:00 UTC / 08:00 GMT SHORT<br>2020-03-16 09:30 UTC / 09:30 GMT LONG<br>2020-03-17 08:35 UTC / 08:35 GMT LONG |
| `Asia 00:00-06:00 UTC | Europe/London 08:00-10:30 | no-EMA` | 34 | $72.98 | -27.02% | 0.26 | $29.22 | 2019-12-04 09:05 UTC / 09:05 GMT SHORT<br>2020-02-28 08:05 UTC / 08:05 GMT LONG<br>2020-03-13 08:00 UTC / 08:00 GMT SHORT<br>2020-03-16 09:30 UTC / 09:30 GMT LONG<br>2020-03-17 08:25 UTC / 08:25 GMT LONG |
| `Asia 00:00-06:30 UTC | Europe/London 08:00-10:30 | EMA200` | 5 | $98.31 | -1.69% | 0.67 | $3.45 | 2019-12-04 09:05 UTC / 09:05 GMT SHORT<br>2020-04-07 07:30 UTC / 08:30 BST LONG<br>2021-01-11 08:45 UTC / 08:45 GMT SHORT<br>2021-11-19 09:25 UTC / 09:25 GMT LONG<br>2022-07-08 08:05 UTC / 09:05 BST LONG |

## Frozen validation and holdout comparison

| Timing / structure | Trades | Final | Return | PF | DD | Example entries |
|---|---:|---:|---:|---:|---:|---|
| `Asia 00:00-06:30 UTC | UTC 07:00-10:30 | no-EMA` | 12 | $93.16 | -6.84% | 0.48 | $7.33 | 2023-02-10 09:15 UTC / 09:15 GMT SHORT<br>2023-03-13 09:55 UTC / 09:55 GMT SHORT<br>2023-03-15 10:00 UTC / 10:00 GMT LONG<br>2023-03-20 09:20 UTC / 09:20 GMT SHORT<br>2024-04-15 08:50 UTC / 09:50 BST LONG |
| `Asia 00:00-07:00 UTC | Europe/London 08:00-10:30 | no-EMA` | 11 | $98.68 | -1.32% | 0.86 | $2.85 | 2023-02-10 09:15 UTC / 09:15 GMT SHORT<br>2023-03-13 09:55 UTC / 09:55 GMT SHORT<br>2023-03-15 10:00 UTC / 10:00 GMT LONG<br>2023-03-20 09:20 UTC / 09:20 GMT SHORT<br>2024-04-15 08:50 UTC / 09:50 BST LONG |
| `Asia 00:00-06:30 UTC | UTC 07:00-10:30 | no-EMA` | 84 | $43.87 | -56.13% | 0.28 | $57.61 | 2025-02-04 08:10 UTC / 08:10 GMT LONG<br>2025-02-11 09:00 UTC / 09:00 GMT LONG<br>2025-02-27 07:40 UTC / 07:40 GMT LONG<br>2025-03-10 07:55 UTC / 07:55 GMT LONG<br>2025-04-03 07:15 UTC / 08:15 BST LONG |
| `Asia 00:00-07:00 UTC | Europe/London 08:00-10:30 | no-EMA` | 67 | $46.29 | -53.71% | 0.20 | $55.20 | 2025-02-04 08:10 UTC / 08:10 GMT LONG<br>2025-02-11 09:00 UTC / 09:00 GMT LONG<br>2025-02-27 09:25 UTC / 09:25 GMT LONG<br>2025-03-10 09:10 UTC / 09:10 GMT LONG<br>2025-04-04 09:00 UTC / 10:00 BST LONG |

## Decision rule

The development-selected timing is `Asia 00:00-07:00 UTC | Europe/London 08:00-10:30 | no-EMA`. It is rejected unless both frozen windows show adequate sample size and net PF above 1 after costs. A local-time adjustment alone is not sufficient evidence of an edge.

All results are available in [`LONDON_ASIAN_CANONICAL.csv`](LONDON_ASIAN_CANONICAL.csv).
