# Asian range / London session timezone research

## Method

- Data: 443,451 source 5-minute bars; timestamps explicitly treated as UTC.
- Asian range: 00:00 UTC through the listed cutoff; London window is either fixed UTC or `Europe/London` local time using IANA DST rules.
- Entry: sweep beyond Asian range by $0.40, then a 5-minute close back inside the range. One structural trade per UTC day.
- Stop: farther of 1.5 ATR from entry or $0.20 beyond the sweep extreme. Target: 2.0R.
- Cost: $0.40 spread, $0.03 adverse slippage per fill, and 0.04% taker fee per side.
- Position management begins on the bar after entry. If a subsequent OHLC bar touches both stop and target, stop is selected first.
- Timing choice is made only from development data; validation and holdout are frozen.
- Data revision: `9229cd58ff171df61180c12e16fc35cc8b716343`.

## DST consequence

A London 08:00 local window begins at 08:00 UTC during GMT and 07:00 UTC during British Summer Time. The legacy fixed 07:00 UTC window therefore starts one hour too early during UK winter and is only aligned with London 08:00 during BST.

## Development-only timing comparison

| Timing / structure | Trades | Final | Return | PF | DD | Example entries |
|---|---:|---:|---:|---:|---:|---|
| `Asia 00:00-06:30 UTC | Europe/London 08:00-10:30 | no-EMA` | 15 | $85.36 | -14.64% | 0.25 | $16.17 | 2020-02-28 10:10 UTC / 10:10 GMT LONG<br>2020-03-09 08:05 UTC / 08:05 GMT LONG<br>2020-03-10 09:40 UTC / 09:40 GMT LONG<br>2020-03-13 08:00 UTC / 08:00 GMT SHORT<br>2020-03-17 08:10 UTC / 08:10 GMT LONG |
| `Asia 00:00-07:00 UTC | Europe/London 08:00-10:30 | no-EMA` | 15 | $85.22 | -14.78% | 0.23 | $16.15 | 2020-02-28 10:10 UTC / 10:10 GMT LONG<br>2020-03-10 09:40 UTC / 09:40 GMT LONG<br>2020-03-13 08:00 UTC / 08:00 GMT SHORT<br>2020-03-17 08:10 UTC / 08:10 GMT LONG<br>2020-03-24 08:25 UTC / 08:25 GMT LONG |
| `Asia 00:00-06:30 UTC | Europe/London 08:00-11:00 | no-EMA` | 19 | $79.81 | -20.19% | 0.19 | $21.63 | 2020-02-28 10:10 UTC / 10:10 GMT LONG<br>2020-03-09 08:05 UTC / 08:05 GMT LONG<br>2020-03-10 09:40 UTC / 09:40 GMT LONG<br>2020-03-13 08:00 UTC / 08:00 GMT SHORT<br>2020-03-17 08:10 UTC / 08:10 GMT LONG |
| `Asia 00:00-06:00 UTC | Europe/London 08:00-10:30 | no-EMA` | 16 | $80.59 | -19.41% | 0.13 | $20.70 | 2020-02-28 10:15 UTC / 10:15 GMT LONG<br>2020-03-09 09:05 UTC / 09:05 GMT LONG<br>2020-03-10 09:40 UTC / 09:40 GMT LONG<br>2020-03-13 08:00 UTC / 08:00 GMT SHORT<br>2020-03-17 08:10 UTC / 08:10 GMT LONG |
| `Asia 00:00-06:30 UTC | UTC 07:00-10:30 | no-EMA` | 22 | $70.72 | -29.28% | 0.04 | $29.53 | 2020-02-28 10:10 UTC / 10:10 GMT LONG<br>2020-03-09 07:00 UTC / 07:00 GMT LONG<br>2020-03-10 09:40 UTC / 09:40 GMT LONG<br>2020-03-13 07:20 UTC / 07:20 GMT SHORT<br>2020-03-17 08:10 UTC / 08:10 GMT LONG |
| `Asia 00:00-06:30 UTC | Europe/London 08:00-10:30 | EMA200` | 4 | $97.45 | -2.55% | 0.41 | $2.98 | 2020-03-13 08:00 UTC / 08:00 GMT SHORT<br>2020-03-24 08:25 UTC / 08:25 GMT LONG<br>2020-04-08 08:35 UTC / 09:35 BST SHORT<br>2020-08-31 08:40 UTC / 09:40 BST LONG |

## Frozen validation and holdout comparison

| Timing / structure | Trades | Final | Return | PF | DD | Example entries |
|---|---:|---:|---:|---:|---:|---|
| `Asia 00:00-06:30 UTC | UTC 07:00-10:30 | no-EMA` | 13 | $92.42 | -7.58% | 0.44 | $7.65 | 2023-03-20 08:05 UTC / 08:05 GMT SHORT<br>2024-04-10 09:35 UTC / 10:35 BST SHORT<br>2024-05-20 09:20 UTC / 10:20 BST SHORT<br>2024-07-19 09:50 UTC / 10:50 BST LONG<br>2024-08-05 08:15 UTC / 09:15 BST SHORT |
| `Asia 00:00-06:30 UTC | Europe/London 08:00-10:30 | no-EMA` | 9 | $92.52 | -7.48% | 0.28 | $7.48 | 2023-03-20 08:05 UTC / 08:05 GMT SHORT<br>2024-05-20 09:20 UTC / 10:20 BST SHORT<br>2024-08-05 08:15 UTC / 09:15 BST SHORT<br>2024-08-06 09:25 UTC / 10:25 BST LONG<br>2024-09-25 08:50 UTC / 09:50 BST LONG |
| `Asia 00:00-06:30 UTC | UTC 07:00-10:30 | no-EMA` | 77 | $39.57 | -60.43% | 0.18 | $60.43 | 2025-01-20 07:45 UTC / 07:45 GMT SHORT<br>2025-01-22 09:50 UTC / 09:50 GMT SHORT<br>2025-02-21 07:30 UTC / 07:30 GMT LONG<br>2025-03-05 08:35 UTC / 08:35 GMT SHORT<br>2025-03-10 09:55 UTC / 09:55 GMT LONG |
| `Asia 00:00-06:30 UTC | Europe/London 08:00-10:30 | no-EMA` | 66 | $48.82 | -51.18% | 0.23 | $51.18 | 2025-01-22 09:50 UTC / 09:50 GMT SHORT<br>2025-03-05 08:35 UTC / 08:35 GMT SHORT<br>2025-03-10 09:55 UTC / 09:55 GMT LONG<br>2025-03-19 08:10 UTC / 08:10 GMT SHORT<br>2025-03-31 08:00 UTC / 09:00 BST SHORT |

## Decision rule

The development-selected timing is `Asia 00:00-06:30 UTC | Europe/London 08:00-10:30 | no-EMA`. It is rejected unless both frozen windows show adequate sample size and net PF above 1 after costs. A local-time adjustment alone is not sufficient evidence of an edge.

All results are available in [`LONDON_ASIAN_TIMEZONE_RESEARCH.csv`](LONDON_ASIAN_TIMEZONE_RESEARCH.csv).
