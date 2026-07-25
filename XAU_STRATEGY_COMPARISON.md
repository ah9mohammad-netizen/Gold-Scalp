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

## Phase 4A — calendar-only event veto

The user-supplied ForexFactory-style calendar covers August 2023 onward. Its historical export displayed `Asia/Tehran` timestamps, verified against known CPI/FOMC release times, so the research parser converted that source display time through the IANA timezone database to UTC. The bot itself remains UTC. The MTF trend strategy was held fixed while only a 30/30 or 60/60 minute no-entry window around predeclared USD event bundles changed.

| Calendar-covered window | No veto | Development-selected extended USD 30/30 veto | Decision |
|---|---|---|---|
| Development: 2023-08 to 2024-06 | −31.02%, PF 0.44 | −30.06%, PF 0.44 | Negligible improvement; reject. |
| Validation: 2024-07 to 2024-12 | −42.55%, PF 0.28 | −41.44%, PF 0.29 | Negligible improvement; reject. |
| Holdout: 2025-01 to 2026-01 | −61.24%, PF 0.34 | −59.24%, PF 0.36 | Slightly less bad, still decisively negative. |

The core CPI/NFP/PPI/FOMC veto did not alter closed-trade results because the MTF trigger rarely coincided with those narrow windows; the broader calendar removed some triggers but did not repair the underlying setup. This proves that event avoidance is a **risk-control layer**, not a source of directional edge by itself.

See [`XAU_EVENT_VETO_RESEARCH.md`](XAU_EVENT_VETO_RESEARCH.md) and [`XAU_EVENT_VETO_RESEARCH.csv`](XAU_EVENT_VETO_RESEARCH.csv).

---

## Phase 4B — daily DXY/VIX/oil macro gates

The new daily oil/geopolitics dataset on `main` contributes DXY, VIX, WTI/Brent returns and volatility. To avoid daily-data look-ahead, every intraday XAU decision uses the **latest prior daily row only**; same-day closes and ex-post geopolitical labels are not used as tradeable input.

| Window | No macro gate | Development-selected stress veto | Decision |
|---|---|---|---|
| Development: 2019-09 to 2022-12 | −44.67%, PF 0.45 | −20.45%, PF 0.48 | Less bad but still negative. |
| Validation: 2023–2024 | −63.51%, PF 0.47 | −58.38%, PF 0.45 | Less exposure, no edge. |
| Holdout: 2025-01 to 2026-01 | −61.24%, PF 0.34 | −53.11%, PF 0.35 | Less loss, still decisively negative. |

The stress veto rejected conditions where the prior VIX exceeded 25, the prior daily WTI move exceeded 3%, or WTI 7-day volatility exceeded 1.5× its 30-day baseline. It reduced trades and drawdown but did not lift PF above 1. The DXY-direction gate performed worse, so it is also rejected.

See [`XAU_DAILY_MACRO_REGIME_RESEARCH.md`](XAU_DAILY_MACRO_REGIME_RESEARCH.md) and [`XAU_DAILY_MACRO_REGIME_RESEARCH.csv`](XAU_DAILY_MACRO_REGIME_RESEARCH.csv).

---

## Phase 5A — impulse–pullback–reclaim behavior discovery

Before constructing another PnL system, two strict structural definitions were outcome-labelled. A candidate had to pass D1/H4 EMA50 trend permission, print an H1 ATR expansion through the prior 20-hour extreme, make a 25–60% controlled M15 pullback, reclaim the pullback swing on M15/EMA20, and then produce a later M5 directional trigger.

| Definition / window | Candidates | +1R before stop | +1.5R before stop | +2R before stop | Stop first | Decision |
|---|---:|---:|---:|---:|---:|---|
| Standard, development | 93 | 18.3% | 11.8% | 10.8% | 38.7% | Reject |
| Standard, validation | 141 | 22.7% | 16.3% | 11.3% | 38.3% | Reject |
| Standard, holdout | 95 | 31.6% | 22.1% | 17.9% | 47.4% | Reject |
| Conservative, development | 58 | 13.8% | 8.6% | 6.9% | 34.5% | Reject |
| Conservative, validation | 98 | 19.4% | 12.2% | 9.2% | 35.7% | Reject |
| Conservative, holdout | 53 | 34.0% | 22.6% | 20.8% | 35.8% | Reject |

The discovery gate required materially more +1R-before-stop outcomes than stop-first outcomes in all windows. Both definitions failed, so no PnL optimisation is justified. The prior-day stress gate did not remove any of these strict candidates, which means it did not provide additional discrimination for this structure.

See [`XAU_IMPULSE_RECLAIM_DISCOVERY.md`](XAU_IMPULSE_RECLAIM_DISCOVERY.md) and [`XAU_IMPULSE_RECLAIM_DISCOVERY.csv`](XAU_IMPULSE_RECLAIM_DISCOVERY.csv).

---

## What remains worth testing

We should not retune EMA periods, stop multipliers, target R values, or event-window sizes against these holdout results. The next candidate needs **new information**, not another variation of price-only rules.

### Next research family: daily macro regime plus stricter continuation structure

Use the existing M5 data plus daily macro regime series:

```text
Daily regime:
    10Y real yield, 10Y/2Y yield direction, broad USD index, VIX, oil

Event veto:
    retain the fixed calendar no-entry layer as risk control

Trend setup:
    permit the strategy only when macro state and higher-timeframe direction agree

M15/M5 entry:
    replace the one-bar M5 break with a stricter continuation/reclaim structure
```

This does not imply that macro factors predict every intraday move. They are first used to classify or avoid hostile environments.

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
