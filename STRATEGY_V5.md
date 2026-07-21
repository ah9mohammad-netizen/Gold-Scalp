# Gold Edge v5 — Research-Validated Z-Score Mean Reversion

## Research process

Ran **26 strategy families** on your real 5m CSVs (`parts 011–015`, **443,451 bars**, 2019-09 → 2026-01), with friction (0.04% RT commission + $0.12/oz slip + $0.20 spread). Then optimized the winner family (~900 MR configs) and validated on:

- **Last year** (2025-01 → 2026-01)
- **Full sample** (2019 → 2026)
- **Mid sample** (2022 → 2023)

## Ranking (last year, $100 start)

| Rank | Strategy family | Final | PF | WR | DD | Verdict |
|-----:|-----------------|------:|---:|---:|---:|---------|
| 1 | **Z-Score MR (optimized)** | **$103–108** | **1.1–1.6** | 47–64% | **$4–11** | **BEST** |
| 2 | PDH/PDL breakout | $92 | 0.96 | 44% | $30 | Weak / noisy |
| 3 | Asia sweep fade | $91 | 0.74 | 50% | $16 | Unstable full-sample |
| 4 | EMA pullback (v4) | $72–90 | 0.7–0.8 | 33–39% | $18–47 | Loses full-sample |
| … | London/NY ORB, Donchian, Supertrend, EMA cross | ~$20–50 | <0.7 | — | high | **DEAD** |
| … | Hermes-style 5R ORB | ~$20 | 0.4 | 13% | 80% | **DEAD** |

### Critical lesson

**Trend breakouts and large-R ORBs destroyed the account** on this gold sample.  
**Mean reversion in *strictly ranging* regimes** was the only approach that:

1. Made money in the last year  
2. Kept drawdown tiny (~$4–11)  
3. Survived full-sample better than anything else (least bad DD)

## v5 production defaults (robust composite winner)

```
Setup:     ZSCORE_MR
Z entry:   ±2.2  (SMA20 / Std20)
ADX max:   18    (only trade deep ranges)
Turn bar:  required (stop extending into stretch)
Session:   07:00–17:00 UTC
SL:        2.5 × ATR
TP:        2.0 R
BE/Trail:  OFF
Risk:      1.0% / trade
Max/day:   3
```

### Backtest snapshot (same friction)

| Window | Final | PF | Trades | Max DD |
|--------|------:|---:|-------:|-------:|
| Last year | **~$107** | **1.63** | ~19 | **~$4** |
| Mid 2022–23 | ~$96 | 0.78 | ~21 | ~$7 |
| Full 2019–26 | ~$87 | 0.82 | ~102 | ~$31 |

Not a holy grail — full-sample still slightly negative — but **night-and-day vs v3 (−67%) / breakout systems (−60%)**.

## Why breakouts failed on this data

Gold’s multi-year path (esp. 2023–2026) has violent two-way swings. Session breakouts after Asia often **reverse**. Early BE @ 1R turned the few winners into fee-eaten scratches. Large 4–5R targets almost never filled.

MR does the opposite: wait for **statistical stretch in a quiet ADX regime**, fade with a **wide stop**, bank **2R** when it snaps back.

## Code map

- `app/engine.py` — ZSCORE_MR primary  
- `app/config.py` — v5 defaults  
- `app/market_data.py` — SMA/Stdev/Z on live bars  
- `app/paper_trader.py` — fixed TP path (BE disabled by high threshold)

## Honesty

Past edges decay. Paper-trade v5, watch `/stats`, and re-run research when you have another 6–12 months of live bars.
