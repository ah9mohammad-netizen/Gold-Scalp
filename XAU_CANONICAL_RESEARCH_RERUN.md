# Canonical UTC XAU research rerun

## Six-step result

| Step | Result |
|---|---|
| 1. Canonical UTC M5 | Built locally by interpreting raw M5 source labels as `Europe/Helsinki` broker-server time and converting to UTC with IANA DST rules. |
| 2. M1 repair | Inserted 8,455 exact M5 bars aggregated from five contiguous native M1 UTC bars; original M5 bars were never overwritten. |
| 3. Provenance | Canonical rows are labelled `M5_ORIGINAL` or `M1_AGGREGATED`. |
| 4. Residual gaps | Daily maintenance/weekends remain. The January repair still contains a 3h40m and a 10m M1 interruption; no interpolation was used. |
| 5. Universal gap guard | Implemented for the research engines: entries are blocked in the 60 minutes before a non-routine gap and open positions force-flat at the last pre-gap executable close. |
| 6. Research rerun | v5, parameter/filter studies, London/Asian study, MTF, calendar veto, daily macro gates, and impulse/reclaim discovery were re-run on the canonical local dataset. |

## Why canonical time was necessary

The raw M5 labels are not UTC. They align with the native M1 source only when interpreted as EET/EEST (`Europe/Helsinki`):

```text
Complete M5 overlap:                  169,471 bars
M5 return correlation after mapping:  0.997169
Median absolute return difference:    0.187 bps
Median absolute close difference:     $0.125
95th-pct close difference:            $0.342
```

The raw M5 `Date` values had previously been treated as UTC. That made all previous session and event placements provisional. This rerun is the reference result for the supplied history.

## Fixed research assumptions

```text
Start balance:             100 USDT
Risk per trade:            1%
Spread:                    $0.40
Slippage:                  $0.03 per fill
Taker fee:                 0.04% per side
Maximum open positions:    1
Ambiguous OHLC policy:     stop first
```

These costs are assumptions, not verified Apex contract fees. They must be replaced by actual execution fees before any live decision.

## Canonical strategy results

| Research family | Canonical development | Canonical validation | Canonical holdout | Verdict |
|---|---|---|---|---|
| v5 Z-score baseline | 17 trades, −12.07%, PF 0.35 | 11 trades, −0.32%, PF 0.96 | 24 trades, −7.92%, PF 0.65 | Reject |
| v5 development-selected parameter set | +1.58%, PF 1.26, 10 trades | 0 trades | −2.19%, PF 0.00, 3 trades | Reject: sample collapse / overfit |
| v5 best simple range filter | −7.66%, PF 0.46 | −2.53%, PF 0.55 | −8.40%, PF 0.58 | Reject |
| Asian range/London local sweep | −22.01%, PF 0.41 | −1.32%, PF 0.86 | −53.71%, PF 0.20 | Reject |
| MTF EMA trend pullback | −74.85%, PF 0.50 | −64.06%, PF 0.53 | −65.82%, PF 0.42 | Reject |
| Calendar event veto on MTF | −23.57%, PF 0.63 | −36.20%, PF 0.39 | −65.65%, PF 0.41 | Reject: risk reduction only |
| Daily DXY/VIX/oil gate on MTF | no gate selected; PF <1 | −64.06%, PF 0.53 | −65.82%, PF 0.42 | Reject |
| Impulse–pullback–reclaim discovery | +1R before stop 32.5%; stop first 38.9% | +1R 28.8%; stop 44.6% | +1R 41.6%; stop 49.6% | Reject before PnL optimisation |

## Interpretation

Correcting timestamp handling and repairing the large M5 holes changed trade counts and session placement. It did **not** create a robust edge in any tested family.

The v5 validation period moved close to break-even after canonicalization, but the 2025+ holdout remains negative. The apparent development winner uses only 10 trades and then produces no validation trades, a textbook example of why it cannot be deployed.

The evidence supports this narrower conclusion:

```text
The tested simple XAU strategies do not demonstrate a robust net edge
under the current fixed-cost model and canonical UTC data.
```

It does **not** prove that no XAU strategy can work.

## Execution-cost sensitivity

A fixed-signal v5 diagnostic held the decision spread/gate at $0.40 and varied only execution spread, fee, and slippage. It does **not** promote v5; it identifies whether fees are the entire explanation.

| Friction scenario | Development | Validation | Holdout | Interpretation |
|---|---|---|---|---|
| Zero execution friction | −7.58%, PF 0.50 | +2.60%, PF 1.35 | +7.67%, PF 1.46 | No robust all-window gross edge; development remains negative. |
| Low friction ($0.10 spread, 0.01%/side, $0.01 slip) | −8.79%, PF 0.45 | +1.59%, PF 1.20 | +1.93%, PF 1.10 | Later periods can clear low assumed cost, but development still fails. |
| Moderate friction ($0.20, 0.02%/side, $0.02) | −10.04%, PF 0.41 | +1.24%, PF 1.16 | −3.71%, PF 0.82 | Not robust. |
| Current model ($0.40, 0.04%/side, $0.03) | −12.07%, PF 0.35 | −0.32%, PF 0.96 | −7.92%, PF 0.65 | Reject. |

This confirms two things at once:

```text
The current cost assumption is material.
But lower cost does not turn v5 into a robust all-period framework.
```

Actual Apex contract fees, price multiplier, and order-price behavior are still required before any final execution decision.

## Remaining evidence-quality tasks

1. Validate the actual fee, contract multiplier, and order-price model on the intended execution venue.
2. Keep canonical UTC conversion for every source; never assume chart timestamps are UTC without overlap validation.
3. Maintain the gap guard in all future research.
4. Preserve the M1 repair provenance and never overwrite original source bars.
5. Keep cost sensitivity as a diagnostic, not an optimization target; a strategy must be positive under realistic fees across development, validation, and holdout.

## Linked detailed reports

- [`V5_CANONICAL_GAP_GUARD.md`](V5_CANONICAL_GAP_GUARD.md)
- [`V5_PARAMETER_CANONICAL.md`](V5_PARAMETER_CANONICAL.md)
- [`V6_REGIME_FILTER_CANONICAL.md`](V6_REGIME_FILTER_CANONICAL.md)
- [`LONDON_ASIAN_CANONICAL.md`](LONDON_ASIAN_CANONICAL.md)
- [`MTF_TREND_PULLBACK_CANONICAL.md`](MTF_TREND_PULLBACK_CANONICAL.md)
- [`XAU_EVENT_VETO_CANONICAL.md`](XAU_EVENT_VETO_CANONICAL.md)
- [`XAU_DAILY_MACRO_REGIME_CANONICAL.md`](XAU_DAILY_MACRO_REGIME_CANONICAL.md)
- [`XAU_IMPULSE_RECLAIM_CANONICAL.md`](XAU_IMPULSE_RECLAIM_CANONICAL.md)
- [`XAU_COST_SENSITIVITY.md`](XAU_COST_SENSITIVITY.md)
