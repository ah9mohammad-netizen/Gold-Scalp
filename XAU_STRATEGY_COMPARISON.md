# XAU strategy comparison — fixed-cost research tournament

**Scope:** XAU only. PAXG and cross-venue approaches are deliberately excluded from this comparison.

**Price data:** supplied UTC 5-minute XAU history, 443,451 bars, 2019-09 through 2026-01.

**Common friction model:** $0.40 spread, $0.03 adverse slippage per fill, 0.04% taker fee per side, one position maximum, and stop-first treatment when a later OHLC bar touches both stop and target.

> **Decision:** none of the tested strategy families has passed the research gate. The comparison is valuable because it tells us what to stop tuning: simple M5 fading, simple OHLC regime filters, Asian/London sweep fades, and simple EMA-alignment pullbacks.

---

## Tournament scorecard

| Family / frozen candidate | Development (2019-09–2022) | Validation (2023–2024) | Holdout (2025+) | Decision |
|---|---|---|---|---|
| Z-score range fade — v5 baseline | 15 trades, −13.26%, PF 0.27 | 9 trades, +5.31%, PF 2.13 | 20 trades, **−5.72%, PF 0.70** | Reject; validation result is too small and did not persist. |
| Z-score + best simple regime filter | 14 trades, −11.15%, PF 0.31 | 4 trades, +3.43%, PF 3.41 | 17 trades, **−7.34%, PF 0.59** | Reject; the bar-range filter worsened the holdout. |
| Asian range sweep/reclaim — DST-aware London local | 15 trades, −14.64%, PF 0.25 | 9 trades, −7.48%, PF 0.28 | 66 trades, **−51.18%, PF 0.23** | Reject; correct local-time handling is not an edge. |
| MTF trend pullback — strict D1/H4/H1/M15 hierarchy | 160 trades, −59.05%, PF 0.43 | 202 trades, −71.14%, PF 0.42 | 152 trades, **−71.26%, PF 0.35** | Reject; high trade frequency compounds a weak entry edge. |
| MTF trend pullback — development-selected slow M15 EMA50 | 117 trades, −44.67%, PF 0.45 | 162 trades, −63.51%, PF 0.47 | 117 trades, **−61.24%, PF 0.34** | Reject; best development variant still fails every window. |

## What is directly comparable

All candidates use the same source price history, initial 100-USDT book, fixed cost assumptions, position cap, risk sizing approach, and no-look-ahead entry/exit sequencing.

The families do not have identical holding periods:

- v5 and the prior sweep studies may remain open beyond the entry session if no exit triggers;
- the MTF trend-pullback study explicitly force-flats at 21:00 UTC or on the next UTC date, because it is designed as an intraday strategy.

Therefore, the precise return magnitudes are not a claim of a perfectly normalized contest. The decisive result is stronger: all tested strategies have net PF below 1 on their holdout period.

---

## MTF trend-pullback diagnosis

The MTF hypothesis was intentionally different from the Z-score fade:

```text
D1/H4/H1: trend alignment
M15:       EMA pullback that closes back on the trend side
M5:        directional close beyond the preceding M5 high/low
Risk:       M15 structure or 1.5×M5 ATR stop, 2R target
```

It failed despite higher-timeframe alignment. The likely explanations are:

1. **EMA-side alignment is not a sufficient trend definition.** Price can be above stacked EMAs and still be in a late trend, rotation, or pullback continuation against the M5 trigger.
2. **The M5 trigger is too cheap.** A one-bar close beyond the prior M5 high/low is frequent and does not establish meaningful order-flow or structural continuation.
3. **The stop/target geometry is poor for this entry.** The M15 pullback extreme may be wide, while a fixed 2R target may be unrealistic before the 21:00 UTC flat rule.
4. **Trade frequency exposes cost.** The development-selected variant generated 117 development trades and paid about $24 in simulated fees before validation. More activity is not more edge.
5. **The model lacks an event veto and macro regime.** It may trade directly into CPI, NFP, FOMC, and yield-driven reversals.

The MTF report and full candidate output are here:

- [`MTF_TREND_PULLBACK_RESEARCH.md`](MTF_TREND_PULLBACK_RESEARCH.md)
- [`MTF_TREND_PULLBACK_RESEARCH.csv`](MTF_TREND_PULLBACK_RESEARCH.csv)

---

## What remains worth testing

We should not retune EMA periods, stop multipliers, or target R values on these holdout results. The next candidate needs **new information**, not another variation of price-only rules.

### Next research family: macro-vetoed, event-aware trend continuation

Use the existing M5 data plus freely available daily macro regime series and official event times:

```text
Daily regime:
    10Y real yield, 10Y/2Y yield direction, broad USD index, VIX, oil

Event veto:
    no entries around CPI, Employment Situation/NFP, FOMC, PCE, PPI

Trend setup:
    use higher-timeframe direction only after macro/event state allows it

M15/M5 entry:
    require a stricter continuation/reclaim pattern than a one-bar M5 break
```

This does not imply that macro factors predict every intraday move. They are first used to avoid entering in known hostile environments.

---

## Promotion rule

No family moves from research into the paper bot unless it shows all of the following:

```text
Development PF > 1 after fixed costs
Validation PF > 1 after fixed costs
Holdout PF > 1 after fixed costs
Adequate trade count in every window
Stable nearby parameter behavior
No dependence on a single session/year
Forward paper confirmation before live consideration
```
