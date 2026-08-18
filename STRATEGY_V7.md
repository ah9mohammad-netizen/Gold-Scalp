# v7 adaptive-session scalper — forward-paper specification

## Status

**Forward-paper experiment only. It is not historically validated and it cannot trade live.**

v7 is a re-framing of the bot after the sparse v6 run exposed both an engineering defect and a weak evaluation design. It is intended to produce a usable, setup-tagged sample without pretending that higher activity automatically creates an edge.

## Why v6 was replaced

1. The in-memory `MAX_TRADES_PER_SESSION` key contained only the session name. After two accepted London plans, for example, the same Railway process could block every later London session until restart. The key now includes the UTC date.
2. v6 had hard-coded strategy limits that could disagree with Railway environment variables.
3. Previous-day high/low and order-block fields were not supplied by the live feed, leaving advertised setup branches inactive.
4. Open-trade management passed a synthetic `zscore=0` and `sma=current_price`, making every fee-cleared trade appear to have returned to its mean.
5. Holding bars and setup metadata were not persisted, so time exits and setup-level attribution were unreliable.
6. Selecting v6 silently switched the paper ledger to maker fees even though entry fills were modelled as market/taker fills.
7. Position size budgeted only the price stop. At XAU notionals near $1,500, fees could be larger than the intended price risk.

Those are engineering failures. Fixing them does not prove a profitable signal.

## Re-framed objective

The objective is **not “trade as often as possible.”** It is to target a practical sample of approximately 0–4 accepted trades on an active weekday while:

- keeping only one position open;
- keeping effective per-trade stop-out risk at or below 0.50%, including estimated round-trip costs;
- stopping new entries after the 2% daily loss limit;
- retaining spread, ATR shock, stale-data and direct-instrument gates; and
- separating performance by setup family, session and regime.

Some days should still produce no trade. Four is a ceiling, not a quota.

## Setup router

All decisions use a completed five-minute candle.

### 1. `LIQUIDITY_REJECTION`

- Uses completed Asian high/low and previous UTC-day high/low.
- Requires a volatility-scaled pierce, close back through the level and a rejection candle.
- RSI, DI and candle close location contribute to the score.

### 2. `TREND_PULLBACK_RECLAIM`

- Requires an EMA21/EMA50/EMA200 directional stack and trending regime.
- Price must touch/reclaim EMA21 with the candle closing in trend direction.
- DI, RSI, VWAP location and ADX contribute to the score.

### 3. `MOMENTUM_CONTINUATION`

- Shares the trend permission layer.
- Requires a completed close beyond the preceding M5 high/low rather than an EMA pullback.
- It is independently tagged because its expectancy may differ materially from pullbacks.

### 4. `RANGE_STRETCH_RECLAIM`

- Requires ranging regime, `|Z| >= 1.60`, and a completed directional reclaim bar.
- RSI, VWAP and candle close location contribute to the score.
- The lower Z threshold increases observations, but score and cost gates remain mandatory.

A setup must score at least 4. Opposing top-score candidates on the same candle are rejected as ambiguous.

## Sessions and frequency

Default v7 decision window:

```text
06:00–20:00 UTC
```

This covers liquid London and New York trading without operating around the clock. The database still enforces one open position, cooldowns and `MAX_TRADES_PER_DAY=4`.

The former v6 session counter is not used by v7. Account-level daily controls are persisted in SQLite and survive Railway restarts.

## Costs and sizing

The default paper model is deliberately conservative:

```text
PAPER_EXECUTION_MODE=TAKER
fee per side = 0.0004
adverse slippage per fill = $0.03/oz
spread = observed feed spread
```

Estimated round-trip cost per ounce:

```text
2 × price × fee_rate + observed_spread + 2 × slippage
```

Position size:

```text
risk_budget / (stop_distance + estimated_round_trip_cost_per_oz)
```

This means a nominal stop plus fees should remain inside the risk budget. The stop and target must also clear configured cost multiples. A `MAKER_POST_ONLY` fee scenario may be run only as a separately labelled experiment; the current bot does not model post-only fill probability.

## Exits

- SL and TP are evaluated from subsequent completed candles with stop-first ordering when both appear in one OHLC candle.
- A nominal breakeven stop is replaced by a **cost-lock stop** intended to cover entry fee, expected exit fee and exit slippage.
- Range/liquidity value exits use the real current SMA/Z-score and require a positive executable net-PnL estimate.
- Trend failure exits require an adverse EMA50 close.
- Range/liquidity trades time out after 8 M5 bars by default.
- Trend trades time out after 12 M5 bars by default.

## Stored audit fields

The schema migrates existing Railway volumes in place. It deliberately stores more than executed trades:

- `market_bars`: every consumed closed M5 candle, raw OHLCV/quote fields, indicators and structural levels;
- `decision_audit`: one outcome for every consumed bar—executed, strategy-rejected, fill-rejected, paused, cooldown, position cap, daily cap or loss limit—with a flexible JSON snapshot;
- `trade_marks`: each subsequent closed bar during a position, executable mark, estimated net PnL, active stop/target and indicator state;
- `signals`: accepted setup snapshots; and
- `trades`: strategy version, setup, session, regime, score, initial/current stop, ATR, fee rate, holding bars, expected cost/reward, MFE, MAE, MFE-R, MAE-R, best/worst estimated net PnL, gross PnL, both fees, net PnL and exit reason.

This avoids survivor/selection bias from studying only executed trades. It also permits later analysis of whether a different score threshold would have changed opportunity count, whether stops were structurally too tight, and whether exits surrendered useful MFE. It still cannot reconstruct tick-level order sequencing or prove that a different rule would have filled.

Telegram `/stats` reports setup outcomes, decision-status/reason counts, market-bar count and trade-mark count. `/status` reports the latest v7 acceptance or rejection reason.

## Promotion/rejection protocol

Do not retune v7 after every loss. Freeze the deployment and collect at least 50 closed trades, preferably 100. Evaluate:

1. net expectancy and profit factor after the conservative taker model;
2. setup-level and session-level concentration;
3. fee-to-gross-profit ratio;
4. maximum drawdown and longest loss sequence;
5. target, stop, value, trend-failure and time-exit distributions; and
6. nearby score/Z/session sensitivity without changing the forward sample.

A setup family with adequate observations and negative net expectancy should be disabled, not blended into the aggregate. Live trading remains blocked regardless of paper results until an independently reviewed executor and venue-specific validation exist.
