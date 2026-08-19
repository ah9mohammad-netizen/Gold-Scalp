# Gold-Scalp — lean XAU-USDT paper research worker

A Railway-oriented, **paper-only** XAU-USDT worker using the frozen v7 adaptive-session strategy.

- Direct Bybit XAU-USDT feed with direct OKX fallback
- Closed five-minute candles evaluated exactly once
- Liquidity rejection, trend pullback, momentum and range-reclaim setup tags
- Cost-inclusive position sizing with a 0.50% effective risk cap
- Conservative spread, slippage and fee accounting
- Persistent SQLite decision/bar/trade-path research telemetry
- Telegram status, controls, alerts and consistent `/get_db` snapshots
- Live execution intentionally blocked
- Python standard-library runtime: no CCXT, SQLAlchemy, aiohttp, aiogram or pydantic install
- Historical CSVs, superseded strategies, alternate-platform bots and offline research scripts removed from the deployment branch

> This is research tooling, not financial advice or a profit guarantee.

## Current documentation

- [v7 strategy specification](STRATEGY_V7.md)
- [`history.db` research guide and SQL](HISTORY_DB_RESEARCH_GUIDE.md)
- [Railway deployment guide](RAILWAY_DEPLOYMENT_GUIDE.md)

## Railway entry point

```bash
python -m app.main
```

Mount a Railway Volume at `/data` and set `DB_PATH=/data/history.db`. The feed bootstraps indicator history once, then downloads only recent rows every 60 seconds instead of repeatedly downloading hundreds of candles.

## Local checks

The runtime has no third-party package requirement:

```bash
python -m unittest discover -s tests -v
```

Set variables in your shell, then run:

```bash
DB_PATH=./history.db python -m app.main
```

## Telegram commands

`/status` · `/balance` · `/signals` · `/trades` · `/stats` · `/get_db` · `/pause` · `/resume` · `/close_all`

`/force_long` and `/force_short` are paper-only plumbing tests, not trade recommendations.
