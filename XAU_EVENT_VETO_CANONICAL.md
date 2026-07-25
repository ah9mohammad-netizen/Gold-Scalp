# XAU macro-event veto research

## Scope and data provenance

- Price source: 451,906 XAU UTC five-minute bars; M15/H1/H4/D1 derived only from completed M5 bars.
- Calendar source: user-supplied ForexFactory-style export from the main branch; source display timezone `Asia/Tehran` normalized to UTC with IANA timezone rules. This conversion applies to the source file only; the Railway bot clock remains UTC.
- Calendar coverage used: 2023-08-10T12:30:00+00:00 through 2026-08-07T12:30:00+00:00.
- Core USD event bundles: 155 unique timestamps / 330 event rows.
- This phase uses a news veto only. Actual/forecast values are intentionally not used for directional prediction.
- Costs: $0.40 spread, $0.03 adverse slippage per fill, 0.04% fee per side.
- Base strategy fixed: D1/H4/H1 EMA50 trend state, M15 EMA50 pullback, M5 directional trigger, 2R target, force-flat 21:00 UTC. Only the veto policy changes.
- XAU data revision: `canonical-utc-m1-repaired-local`.

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
| `Core USD veto 60m before / 60m after` | 81 | 35/46 | 23 | $76.43 | -23.57% | 0.63 | $27.27 |
| `Core USD veto 30m before / 30m after` | 85 | 36/49 | 13 | $73.34 | -26.66% | 0.60 | $30.26 |
| `Extended USD veto 30m before / 30m after` | 80 | 33/47 | 33 | $71.80 | -28.20% | 0.55 | $31.76 |
| `No event veto` | 86 | 35/51 | 0 | $69.76 | -30.24% | 0.55 | $33.64 |

## Frozen validation and holdout

| Veto policy | Trades | W/L | Vetoed entries | Final | Return | PF | DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| `No event veto` | 67 | 21/46 | 0 | $61.51 | -38.49% | 0.38 | $42.77 |
| `Core USD veto 60m before / 60m after` | 65 | 21/44 | 15 | $63.80 | -36.20% | 0.39 | $39.63 |
| `No event veto` | 161 | 56/105 | 0 | $34.18 | -65.82% | 0.42 | $66.04 |
| `Core USD veto 60m before / 60m after` | 158 | 54/104 | 14 | $34.35 | -65.65% | 0.41 | $65.87 |

## Decision rule

The development-selected policy is `Core USD veto 60m before / 60m after`. It is rejected unless it produces adequate trade count and net PF above 1 in both later windows. A veto may reduce exposure; it does not create permission to trade a weak base setup.

All results are in [`XAU_EVENT_VETO_CANONICAL.csv`](XAU_EVENT_VETO_CANONICAL.csv).
