# XAU macro-event veto research

## Scope and data provenance

- Price source: 443,451 XAU UTC five-minute bars; M15/H1/H4/D1 derived only from completed M5 bars.
- Calendar source: user-supplied ForexFactory-style export from the main branch, parsed as `Asia/Tehran` display time and converted to UTC with IANA timezone rules.
- Calendar coverage used: 2023-08-10T12:30:00+00:00 through 2026-08-07T12:30:00+00:00.
- Core USD event bundles: 155 unique timestamps / 330 event rows.
- This phase uses a news veto only. Actual/forecast values are intentionally not used for directional prediction.
- Costs: $0.40 spread, $0.03 adverse slippage per fill, 0.04% fee per side.
- Base strategy fixed: D1/H4/H1 EMA50 trend state, M15 EMA50 pullback, M5 directional trigger, 2R target, force-flat 21:00 UTC. Only the veto policy changes.
- XAU data revision: `9229cd58ff171df61180c12e16fc35cc8b716343`.

## Core event taxonomy

- `average hourly earnings`: 36 CSV rows
- `cpi`: 103 CSV rows
- `fed interest rate decision`: 24 CSV rows
- `fomc economic projections`: 12 CSV rows
- `fomc press conference`: 24 CSV rows
- `fomc statement`: 24 CSV rows
- `nonfarm payrolls`: 36 CSV rows
- `ppi`: 36 CSV rows
- `unemployment rate`: 35 CSV rows

## Development-only veto comparison

| Veto policy | Trades | W/L | Vetoed entries | Final | Return | PF | DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| `Extended USD veto 30m before / 30m after` | 59 | 18/41 | 26 | $69.94 | -30.06% | 0.44 | $31.17 |
| `No event veto` | 60 | 18/42 | 0 | $68.98 | -31.02% | 0.44 | $32.11 |
| `Core USD veto 30m before / 30m after` | 60 | 18/42 | 10 | $68.98 | -31.02% | 0.44 | $32.11 |
| `Core USD veto 60m before / 60m after` | 60 | 18/42 | 16 | $68.98 | -31.02% | 0.44 | $32.11 |

## Frozen validation and holdout

| Veto policy | Trades | W/L | Vetoed entries | Final | Return | PF | DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| `No event veto` | 60 | 14/46 | 0 | $57.45 | -42.55% | 0.28 | $42.95 |
| `Extended USD veto 30m before / 30m after` | 59 | 14/45 | 7 | $58.56 | -41.44% | 0.29 | $41.84 |
| `No event veto` | 117 | 33/84 | 0 | $38.76 | -61.24% | 0.34 | $62.01 |
| `Extended USD veto 30m before / 30m after` | 116 | 34/82 | 4 | $40.76 | -59.24% | 0.36 | $60.07 |

## Decision rule

The development-selected policy is `Extended USD veto 30m before / 30m after`. It is rejected unless it produces adequate trade count and net PF above 1 in both later windows. A veto may reduce exposure; it does not create permission to trade a weak base setup.

All results are in [`XAU_EVENT_VETO_RESEARCH.csv`](XAU_EVENT_VETO_RESEARCH.csv).
