# Gold Edge v4 — Strategy Overhaul (post-backtest)

## Why v3 failed (real 5m history 2025–2026)

| Metric | v3 result |
|--------|-----------|
| $100 → | **$33** (−67%) |
| PF | **0.49** |
| WR | 26% |
| Root causes | BE @ 1R turned winners into scratches; 4R almost never hit; naked Asia breakouts + NY ORB lost |

## What v4 changes

| Area | v3 | v4 |
|------|----|----|
| Primary setup | Asia breakout | **EMA21 pullback in trend** |
| Asia break / NY ORB / Sweep | ON | **OFF by default** (toggleable) |
| Session | 07–10, 12–16 | **08–11 UTC (London core)** |
| Risk / trade | 1.5% | **1.0%** |
| Max trades/day | 3 | **2** |
| SL | 1.5×ATR | **1.8×ATR** |
| TP | 4.0R | **2.0R** |
| BE arm | 1.0R | **1.5R** |
| Trail | ON tight | **OFF** |
| Loss cooldown | 300s | **1800s** |

## Decision stack

1. **Session** — London 08–11 UTC only (default)  
2. **Vol/cost** — ATR band + SL/TP ≫ round-trip cost  
3. **Trend** — EMA stack (price > EMA21 > 50 > 200) + ADX ≥ 28  
4. **Entry** — Pullback into EMA21 zone + bounce bar + DI confirm  
5. **Exit** — SL 1.8×ATR · full TP 2.0R · BE only after 1.5R · no trail  

## Backtest on your CSV (parts 011–015)

Last year (2025-01-30 → 2026-01-30), with friction:

| Config | Final | Ret | WR | PF | Max DD |
|--------|------:|----:|---:|---:|-------:|
| **v3** | $33 | −67% | 26% | 0.49 | 75% |
| **v4 multi-setup** | $69 | −31% | 36% | 0.79 | 53% |
| **v4 London pull only** | **$95** | **−5%** | 39% | **0.94** | **22%** |

v4 is a large improvement but **still not a proven money printer** on this sample. Paper trade and keep tuning.

## Env knobs

See `.env.example`. To re-enable secondary setups:

```env
ENABLE_ASIA_BREAKOUT=true
ENABLE_NY_ORB=true
ALLOWED_SESSIONS=8-11,13-17
```
