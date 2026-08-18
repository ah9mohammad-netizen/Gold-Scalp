# `history.db` forward-research guide

## Purpose and limits

The database is designed to support rejection and improvement of a frozen paper strategy without studying only the trades that happened to execute. It cannot guarantee a profitable rewrite. It also cannot reconstruct tick ordering, queue position, post-only fill probability, funding or a historical order book from five-minute OHLC data.

## Research tables

### `market_bars`

One row per consumed closed M5 candle and source. It stores:

- source/instrument/proxy provenance and bar timestamps;
- OHLCV;
- the bid, ask and spread observed when the closed bar was consumed;
- ATR/ATR average, ADX/DI, RSI, EMA21/50/200, SMA/stdev/Z-score and VWAP; and
- Asian and complete previous-day liquidity levels.

The bid/ask observation is newer than the candle close because the application deliberately computes signals from a completed candle and uses the current quote for the paper fill. `recorded_at` identifies that observation time.

### `decision_audit`

One row per strategy/source/bar, including bars that produced no trade. Status/reason examples:

- `EXECUTED / TRADE_OPENED`;
- `REJECTED / NO_SETUP_SCORE`;
- `REJECTED / SPREAD_TOO_WIDE`;
- `BLOCKED / MAX_OPEN_TRADES`;
- `BLOCKED / ENTRY_COOLDOWN`;
- `BLOCKED / MAX_TRADES_PER_DAY`; and
- `FILL_REJECTED / MARGIN_OR_RISK_GUARD`.

`evaluation_json` retains flexible strategy details, including all detected v7 candidates and their sub-threshold scores. This allows later threshold/frequency analysis without pretending that rejected bars were accepted fills.

### `signals`

Accepted pre-fill strategy plans and indicator snapshots. This is narrower than `decision_audit` by design.

### `trades`

Executed lifecycle and attribution fields, including:

- strategy, setup, session, regime and score;
- reference/fill, initial/current stop, target, size and margin;
- fee model, entry/exit fees and expected round-trip cost;
- bars held, maximum favorable/adverse prices;
- MFE/MAE in USD per ounce and initial-R units;
- best/worst executable estimated net PnL while open; and
- final gross PnL, net PnL and exit reason.

MFE and MAE can both occur in one OHLC candle; their ordering is unknown. They are diagnostics, not proof that an intrabar trailing rule would have filled.

### `trade_marks`

One row per subsequent completed candle while a trade is open. It stores the executable close estimate, fee-aware estimated net PnL, active stop/target and current indicator state. Use this to test time-exit, cost-lock and giveback hypotheses without relying only on the final exit row.

### `account_history` and `bot_state`

Immutable realized balance changes plus operational restart/pause state.

## Useful first queries

### Decision funnel

```sql
SELECT status, reason, COUNT(*) AS bars
FROM decision_audit
GROUP BY status, reason
ORDER BY bars DESC;
```

### Setup expectancy after costs

```sql
SELECT
    setup_name,
    COUNT(*) AS trades,
    SUM(pnl_usd > 0) AS wins,
    ROUND(AVG(pnl_usd), 4) AS expectancy_usd,
    ROUND(SUM(pnl_usd), 4) AS net_pnl_usd,
    ROUND(SUM(entry_fee_usd + exit_fee_usd), 4) AS fees_usd
FROM trades
WHERE status = 'CLOSED' AND strategy_version = 'v7-adaptive-session-scalper'
GROUP BY setup_name
ORDER BY net_pnl_usd DESC;
```

### Session and regime attribution

```sql
SELECT session_name, regime, setup_name,
       COUNT(*) AS trades,
       ROUND(AVG(pnl_usd), 4) AS expectancy_usd,
       ROUND(SUM(pnl_usd), 4) AS net_pnl_usd
FROM trades
WHERE status = 'CLOSED' AND strategy_version = 'v7-adaptive-session-scalper'
GROUP BY session_name, regime, setup_name
ORDER BY trades DESC;
```

### Exit/giveback diagnosis

```sql
SELECT setup_name, exit_reason, COUNT(*) AS trades,
       ROUND(AVG(mfe_r), 3) AS avg_mfe_r,
       ROUND(AVG(mae_r), 3) AS avg_mae_r,
       ROUND(AVG(pnl_usd), 4) AS avg_net_pnl
FROM trades
WHERE status = 'CLOSED' AND strategy_version = 'v7-adaptive-session-scalper'
GROUP BY setup_name, exit_reason
ORDER BY trades DESC;
```

### Fee drag

```sql
SELECT
    ROUND(SUM(gross_pnl_usd), 4) AS gross_price_pnl,
    ROUND(SUM(entry_fee_usd + exit_fee_usd), 4) AS fees,
    ROUND(SUM(pnl_usd), 4) AS net_pnl
FROM trades
WHERE status = 'CLOSED' AND strategy_version = 'v7-adaptive-session-scalper';
```

## Evaluation discipline

1. Archive the deployment commit and Railway variables with each sample.
2. Do not mix v5/v6 and v7 rows; filter by `strategy_version`.
3. Freeze v7 for at least 50 closed trades, preferably 100.
4. Examine setup/session/regime expectancy and the decision funnel before changing thresholds.
5. Form a written hypothesis from MFE/MAE or `trade_marks`.
6. Test the change on a later, untouched forward period rather than rewriting the same sample until it looks profitable.
7. Keep taker-cost results as the baseline unless a realistic maker fill model is independently implemented.

At normal M5 frequency, `market_bars` adds roughly 100,000 rows per continuously operating year. Monitor Railway volume usage and retain exported snapshots; do not delete the only research copy merely to reset account statistics.
