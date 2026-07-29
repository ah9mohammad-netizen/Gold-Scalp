# XAU-USDT 6-Pillar Professional Institutional Scalping Framework

## Practitioner's Verdict & Rationale

As demonstrated by this repository's exhaustive **443,451-bar historical audit (2019–2026)**, standard retail closed-candle systematic strategies—whether simple Z-Score Mean Reversion (`v5`) or session breakout systems (`London/Asian Breakouts`)—suffer from negative net expectancy when realistic perpetual/ECN trading friction (`0.04% taker fee per side + $0.40 spread + slippage`) is applied.

### Why Standard Systems Bleed in Gold (`XAU-USDT`)
1. **The Friction Trap**: A 0.08% round-trip taker fee plus $0.40 spread consumes 40%–60% of the gross profit of a 2.0R target on 5-minute scalping stops.
2. **Two-Way Liquidity Stop-Hunting**: Gold is a liquidity-seeking predator. It routinely sweeps 10–20 pips above Asian or London session highs/lows to trigger retail breakout stops, absorbs the liquidity, and reverses violently.
3. **Static Hope-Based Exits**: Holding a scalping trade for a fixed 2.0R target in a quiet ADX regime (`ADX <= 20`) ignores the fact that price often snaps back to the mean (`SMA20`), stalls, and reverses. Time decay works against static scalps.

---

## The 6-Pillar Institutional Architecture

```
                       THE 6-PILLAR PROFESSIONAL GOLD FRAMEWORK
  ┌──────────────────────────────────────────────────────────────────────────────────┐
  │  1. VENUE & EXECUTION ECONOMICS   │  • Raw ECN/Perp Spreads <= $0.25/oz            │
  │                                   │  • Maker Post-Only Limit Entries (0 Taker Fee) │
  ├───────────────────────────────────┼──────────────────────────────────────────────┤
  │  2. TIME-OF-DAY KILL ZONES        │  • Tokyo Sweep (00:00–04:00 UTC)               │
  │                                   │  • London Open (07:00–10:00 UTC)               │
  │                                   │  • NY / London Overlap (12:00–16:00 UTC)       │
  ├───────────────────────────────────┼──────────────────────────────────────────────┤
  │  3. DYNAMIC REGIME GATING         │  • 3-State Classifier (Ranging/Trending/Shock) │
  │                                   │  • Absolute Macro Event Veto (±30m)            │
  ├───────────────────────────────────┼──────────────────────────────────────────────┤
  │  4. LIQUIDITY SWEEP & RECLAIM     │  • Fade Asian/PDH/PDL Sweeps after Rejection   │
  │                                   │  • Join H1 Order-Block Pullbacks               │
  ├───────────────────────────────────┼──────────────────────────────────────────────┤
  │  5. ADAPTIVE EXITS & TIME LIMITS  │  • Mean Return Exits (|Z| <= 0.35 / SMA Cross) │
  │                                   │  • Time-Based Kill Switch (Max 6 Bars / 30m)   │
  ├───────────────────────────────────┼──────────────────────────────────────────────┤
  │  6. CAPITAL & FREQUENCY DEFENSE   │  • Max 2 Trades/Session | -3.0% Daily DD Limit │
  └───────────────────────────────────┴──────────────────────────────────────────────┘
```

---

## Pillar 1: Venue & Execution Economics

### 1.1 Taker Fee Mitigation via Maker Post-Only
In XAU-USDT perpetual trading, paying taker fees (`0.04%` per side = `0.08%` RT) creates a massive hurdle rate. The 6-Pillar bot uses **Maker Post-Only limit orders** (`EXECUTION_MODE = "MAKER_POST_ONLY"`) at the structural rejection close or order-block edge.
- **Taker Round-Trip Cost**: `0.08% × $2,850 = $2.28/oz` in fee drag.
- **Maker Round-Trip Cost**: `0.02% × $2,850 = $0.57/oz` (or 0.00% on VIP tiers).
- Saving `$1.71/oz` per round trip converts marginal paper scratches into positive-expectancy wins.

### 1.2 Hard Spread Ceiling (`$0.25/oz`)
New entries are rejected outright whenever the live spread exceeds **`MAX_ALLOWABLE_SPREAD_USD = 0.25`** ($0.25/oz equivalent to ~2.5 pips).

---

## Pillar 2: Time-of-Day Kill Zones (UTC)

Gold volume and spread economics are strictly seasonal across the 24-hour cycle. Trading is restricted to **three institutional liquidity windows**:

| Kill Zone | UTC Hours | Target Behavior & Setup Focus |
| :--- | :--- | :--- |
| **Tokyo / Sydney Sweep** | `00:00 – 04:00 UTC` | Accumulation range fade. Target liquidity sweeps of previous day highs/lows or Asian range boundaries. |
| **London Open Kill Zone** | `07:00 – 10:00 UTC` | "Silver Bullet" liquidity sweep absorption of Asian High/Low and reversal back toward session midpoint. |
| **London / NY Overlap** | `12:00 – 16:00 UTC` | Peak daily volume. Trade Order Block pullbacks in trending regimes and major liquidity sweeps. |
| **Dead Zone / Low Volatility** | `04:00–07:00`, `10:00–12:00`, `16:00–24:00 UTC` | **NO TRADING.** Spreads expand, liquidity drops, and false breakouts proliferate. |

---

## Pillar 3: Dynamic Regime Gating

### 3.1 3-State Regime Classifier
Each 5-minute bar is classified before setup evaluation:
1. **`RANGING`** (`ADX <= 20` and normal ATR): Enables `LIQUIDITY_SWEEP_RECLAIM` and `ZSCORE_SWEEP_RECLAIM` setups.
2. **`TRENDING`** (`ADX >= 22` with EMA stack alignment): Enables `ORDER_BLOCK_PULLBACK` continuation setups.
3. **`SHOCK_VOLATILE` / VETO** (`ATR14 > 1.8 × SMA(ATR14, 50)` or High-Impact News): **Absolute Veto** on all entries.

### 3.2 Scheduled Macro Event Buffer
All automated entries are vetoed **±30 minutes around scheduled high-impact US macro releases** (CPI, NFP, FOMC, GDP) to avoid abnormal slippage and spread widening.

---

## Pillar 4: ICT/SMC Liquidity Sweep Reclaim & Order Blocks

Instead of entering breakouts when price crosses a session high/low, the 6-Pillar framework trades the **stop-hunt absorption**:

### 4.1 `LIQUIDITY_SWEEP_RECLAIM` (Primary Setup)
1. **Level Identification**: Track `Asian High`, `Asian Low`, `Previous Day High (PDH)`, and `Previous Day Low (PDL)`.
2. **Stop-Hunt Pierce**: Candle high must pierce a key resistance level by at least **`$0.80/oz`** (`SWEEP_PIERCE_USD`) to trigger buy stops.
3. **Absorption Rejection**: The 5m candle **must close back inside structure** (`close < level` for SHORT, `close > level` for LONG).
4. **Stop Loss & Sizing**: SL is placed `Sweep Extreme ± $0.50` (`SWEEP_BUFFER_SL_USD`), minimum $1.50/oz.

### 4.2 `ORDER_BLOCK_PULLBACK` (Secondary Setup in Trending Regimes)
During confirmed `TRENDING` regimes (`ADX >= 22`), identify the last opposing candle before an impulsive Fair Value Gap (FVG) and enter on the first pullback rejection at the Order Block edge.

---

## Pillar 5: Adaptive Exits & Time-Based Kill Switch

### 5.1 Mean-Return Exit (`MEAN_RETURN_EXIT`)
In ranging regimes, price action reverts to the mean (`SMA20` / session VWAP) before stalling.
- Whenever an open `LIQUIDITY_SWEEP_RECLAIM` or `ZSCORE` trade sees the Z-score return inside **`|Z| <= 0.35`** or cross the 20-period SMA, the bot **exits immediately at market**, securing profit without waiting for a static 2.0R target.

### 5.2 Time-Based Kill Switch (`TIME_KILL_SWITCH`)
- If an open scalp has not hit its target or mean-return threshold within **`6 bars (30 minutes)`**, the position is closed immediately at market (`max_holding_bars = 6`).
- **Rationale**: In gold scalping, if an absorption trade does not work quickly, time decay works against the trade.

### 5.3 Dynamic Breakeven & ATR Trailing
- Once a trade reaches **`+1.2R`** (`BE_TRIGGER_RR = 1.2`), Stop Loss is immediately moved to `entry_price` to lock out losses from sudden wicks.

---

## Pillar 6: Capital Defense & Frequency Discipline

1. **Session Frequency Cap**: Maximum **`2 trades per killzone session`** (`MAX_TRADES_PER_SESSION = 2`), maximum 6 trades per day.
2. **Daily Drawdown Circuit Breaker**: If daily realized loss reaches **`-3.0%` of equity** (`MAX_DAILY_LOSS_PCT = 3.0`), trading is suspended for the remainder of the UTC day.
3. **Equity-Tiered Risk Sizing**: Position sizing is dynamically sized to risk exactly **`1.0%` of equity** per trade, clamped by `MARGIN_CAP_PCT = 30.0%`.

---

## Codebase Map & Implementation

| Component | File Path | Description |
| :--- | :--- | :--- |
| **Core 6-Pillar Engine** | [`app/six_pillar_engine.py`](app/six_pillar_engine.py) | Implements the 6-Pillar decision engine, regime classifier, sweep reclaim logic, and Pillar 5 adaptive exits. |
| **Engine Unit Tests** | [`tests/test_six_pillar_engine.py`](tests/test_six_pillar_engine.py) | 100% test coverage verifying spread gates, kill zones, regime vetoes, sweep reclaims, mean exits, and frequency limits. |
| **Production Python Bot** | [`bots/python_xauusdt_6pillar_scalper.py`](bots/python_xauusdt_6pillar_scalper.py) | Standalone async runner implementing simulated maker execution, candle cycles, and fee-aware PnL accounting. |
| **Layered Scalper Wrapper** | [`bots/python_xauusdt_layered_scalper.py`](bots/python_xauusdt_layered_scalper.py) | Upgraded entry point with backward-compatible aliases for the 6-Pillar architecture. |
| **TradingView Script** | [`bots/pinescript_6pillar_scalper.pine`](bots/pinescript_6pillar_scalper.pine) | Pinescript v5 implementation of the 6-Pillar framework with killzone highlighting and mean-return exits. |
| **MetaTrader 5 EA** | [`bots/mql5_xauusd_6pillar_scalper.mq5`](bots/mql5_xauusd_6pillar_scalper.mq5) | MQL5 Expert Advisor implementing kill zones, spread filters, and Pillar 5 adaptive exits. |

---

## Quick Start Command

To run the 6-Pillar institutional scalping demonstration:

```bash
python -m bots.python_xauusdt_6pillar_scalper
```

To run the complete repository test suite (including the 6-Pillar unit tests):

```bash
python -m unittest discover -s tests -v
```
