# XAU regime + MACD/RSI/CCI/BB/VWAP architecture study

## Research question

Can a regime-first architecture transferred *methodologically* from public BTC/ETH indicator research survive a cost-aware XAU walk-forward test? This is not a parameter transfer and not a promise of a profitable bot.

## Locked protocol before reading validation/holdout results

- Families are evaluated separately: trend pullback, squeeze breakout, and range reversion.
- Feature roles: EMA/ADX/DI = regime; ATR ratio = volatility gate; MACD/RSI/CCI = momentum/recovery; Bollinger Bands = compression/extension; VWAP = value location.
- Conventional indicator definitions are fixed: EMA 50/200; MACD 12/26/9; RSI 14; CCI 20; Bollinger 20/2; Wilder ATR/ADX 14. They were not tuned against XAU outcomes in this study.
- Entry occurs only after a completed M5 candle. The first eligible stop/target bar is the following M5 candle. If both touch in one OHLC bar, the stop is chosen first.
- All models share the exact same risk/execution lifecycle: 07:00–20:00 UTC decisions; flat after the 20:55–21:00 UTC candle; 1% account risk target, 35% margin cap, 3 trades/day cap, configured cooldown/daily-loss guard, 1.5×ATR stop subject to the existing $2.00/cost floor, fixed 2R target, and a 4h trend/breakout or 2h range maximum holding time.
- Costs are engineering assumptions only: $0.40 execution spread, $0.03 adverse slippage per fill, 0.04% fee per side.
- Development selection is limited to 2019-09–2022. A family is eligible only with ≥30 closed development trades, net profit after current costs, and PF ≥1.10. At most one eligible variant per family is selected. Validation and holdout cannot alter this selection.
- A composite takes only the frozen selected families, risks one normal position at a time, and skips an ambiguous simultaneous multi-signal rather than using a post-hoc tie-break.

## Data and provenance

- Canonical UTC M5 bars: **451,906** from 2019-09-06T06:25:00+00:00 through 2026-01-30T21:55:00+00:00.
- Source provenance: `M1_AGGREGATED` = 8,455, `M5_ORIGINAL` = 443,451.
- Input SHA-256 (file names + bytes): `9d9f28cef259308737578eca5de96d6d9610d83faf7fc597d4294c73ff07c40c`.
- Original M5 server labels were normalized with `Europe/Helsinki` IANA rules; complete native M1 aggregates repair only missing M5 intervals. This study refuses raw timezone-unlabelled CSVs.
- VWAP is a **source-local UTC-day VWAP**. Original M5 volumes and M1-aggregated volumes have incompatible magnitudes, so VWAP resets at a provenance seam and never mixes volume scales. It is a location proxy, not venue-certified traded volume/VWAP.
- Historical bid/ask, trade-side flow, order-book depth, funding, and actual Apex contract specifications were unavailable and therefore not inferred from this file.
- Gap guard: enabled; 75 non-routine gaps block pre-gap entries and force a last-observable-close exit.

## Development-only independent families

| Model | Window | Signals | Trades | Final | Return | PF | Win rate | Max DD | Fees |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `Trend pullback — core` | Development (2019-09 to 2022-12) | 488 | 426 | $8.61 | -91.39% | 0.42 | 29.8% | $92.54 | $58.10 |
| `Trend pullback — MACD + CCI` | Development (2019-09 to 2022-12) | 128 | 125 | $50.58 | -49.42% | 0.41 | 31.2% | $51.47 | $30.82 |
| `Trend pullback — value-confirmed` | Development (2019-09 to 2022-12) | 55 | 55 | $75.87 | -24.13% | 0.45 | 34.5% | $27.91 | $16.14 |
| `Squeeze breakout — core` | Development (2019-09 to 2022-12) | 137 | 131 | $42.65 | -57.35% | 0.31 | 25.2% | $59.80 | $29.36 |
| `Squeeze breakout — value-confirmed` | Development (2019-09 to 2022-12) | 137 | 131 | $42.65 | -57.35% | 0.31 | 25.2% | $59.80 | $29.36 |
| `Range reversion — core` | Development (2019-09 to 2022-12) | 7 | 7 | $92.47 | -7.53% | 0.17 | 14.3% | $9.03 | $2.42 |
| `Range reversion — value-confirmed` | Development (2019-09 to 2022-12) | 6 | 6 | $93.98 | -6.02% | 0.20 | 16.7% | $7.54 | $2.08 |

## Frozen validation diagnostics (all independent models)

| Model | Window | Signals | Trades | Final | Return | PF | Win rate | Max DD | Fees |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `Trend pullback — core` | Validation (2023-2024) | 260 | 223 | $23.24 | -76.76% | 0.33 | 30.0% | $77.31 | $45.68 |
| `Trend pullback — MACD + CCI` | Validation (2023-2024) | 70 | 65 | $61.76 | -38.24% | 0.26 | 26.2% | $39.14 | $21.38 |
| `Trend pullback — value-confirmed` | Validation (2023-2024) | 35 | 33 | $78.01 | -21.99% | 0.26 | 21.2% | $24.09 | $12.22 |
| `Squeeze breakout — core` | Validation (2023-2024) | 74 | 69 | $51.41 | -48.59% | 0.21 | 20.3% | $48.59 | $22.65 |
| `Squeeze breakout — value-confirmed` | Validation (2023-2024) | 73 | 68 | $52.42 | -47.58% | 0.21 | 20.6% | $47.58 | $22.48 |
| `Range reversion — core` | Validation (2023-2024) | 15 | 15 | $89.96 | -10.04% | 0.27 | 33.3% | $11.09 | $6.02 |
| `Range reversion — value-confirmed` | Validation (2023-2024) | 11 | 11 | $95.01 | -4.99% | 0.43 | 45.5% | $7.02 | $4.35 |

## Frozen holdout diagnostics (all independent models)

| Model | Window | Signals | Trades | Final | Return | PF | Win rate | Max DD | Fees |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `Trend pullback — core` | Holdout (2025 onward) | 135 | 123 | $30.69 | -69.31% | 0.26 | 27.6% | $69.44 | $38.08 |
| `Trend pullback — MACD + CCI` | Holdout (2025 onward) | 39 | 39 | $62.51 | -37.49% | 0.19 | 20.5% | $38.10 | $17.36 |
| `Trend pullback — value-confirmed` | Holdout (2025 onward) | 19 | 19 | $75.53 | -24.47% | 0.14 | 21.1% | $26.29 | $8.96 |
| `Squeeze breakout — core` | Holdout (2025 onward) | 58 | 56 | $56.74 | -43.26% | 0.28 | 26.8% | $43.42 | $24.54 |
| `Squeeze breakout — value-confirmed` | Holdout (2025 onward) | 57 | 55 | $57.80 | -42.20% | 0.29 | 27.3% | $42.37 | $24.06 |
| `Range reversion — core` | Holdout (2025 onward) | 5 | 5 | $91.39 | -8.61% | 0.00 | 0.0% | $8.61 | $2.56 |
| `Range reversion — value-confirmed` | Holdout (2025 onward) | 5 | 5 | $91.39 | -8.61% | 0.00 | 0.0% | $8.61 | $2.56 |

## Development selection and composite

No family met the pre-stated development eligibility rule. **No composite was created.** Combining rejected or under-sampled signals would manufacture complexity, not evidence.

## Blind spots retained deliberately

- **Trend pullback:** EMAs and ADX are lagging; a recovery through a value reference can be the first leg of a trend failure. A stop on OHLC data does not know intrabar path beyond the conservative stop-first rule.
- **Squeeze breakout:** Bollinger compression is not a causal forecast. News shocks and false breakouts can pass momentum filters, while a 5-minute candle hides fill sequencing and transient spread widening.
- **Range reversion:** It is explicitly vulnerable to volatility expansion and persistent directional moves. The earlier canonical Z-score range baseline already failed, so this family is a falsification test rather than a presumed improvement.
- **VWAP:** The available volume is source-specific rather than venue-verified. Source-local reset avoids mixing scales but does not convert it into actual execution-venue volume.
- **Portfolio/execution:** All results depend on unverified spread, fee, multiplier, size, liquidation, index/mark, and funding assumptions. A positive OHLC backtest would still require independent forward paper validation; a negative one is a rejection signal.

## Promotion rule

Nothing in this report changes the Railway bot or enables live trading. A candidate may move only to a separately reviewed forward-paper phase if the frozen composite (or a single family when no composite is justified) has adequate trade counts, PF above 1 after verified costs in both unseen windows, acceptable drawdown, and no material provenance/gap failure. Otherwise it remains rejected.

Machine-readable metrics: [`XAU_REGIME_INDICATOR_STACK.csv`](XAU_REGIME_INDICATOR_STACK.csv). Trade-level audit: [`XAU_REGIME_INDICATOR_STACK_TRADES.csv`](XAU_REGIME_INDICATOR_STACK_TRADES.csv).
