# Gold-Scalp — XAU-USDT paper research bot

A Railway-friendly **paper-trading** worker for researching a closed-candle XAU-USDT day-trading strategy with a Telegram control surface.

- Starts with a persistent **100 USDT** paper account
- Uses direct XAU-USDT feeds (Bybit first; OKX fallback); it does **not** silently substitute PAXG
- Evaluates each **closed 5-minute candle once** to avoid intrabar look-ahead/repeated polling signals
- Uses a range-only Z-score mean-reversion baseline: Z ±2.2, ADX ≤18, turn bar, ATR SL, fixed 2R target
- Simulates bid/ask execution, slippage, and taker fees; stores gross and **net** results
- Persists signals, trades, account history, and state in `/data/history.db`
- Offers Telegram alerts, pause/resume, trade/status commands, and `/get_db` SQLite export
- **Cannot trade live.** The app refuses `PAPER_TRADING=false` until an independently reviewed ApeX executor exists.

> This software is research tooling, not financial advice. It does not promise profit. High leverage magnifies operational, gap, spread, funding, and liquidation risks.

## Research and strategy

- [Gold automation research and strategy decision memo](GOLD_AUTOMATION_RESEARCH_2026.md) — strategy families, venue facts, rejected approaches, research gates, and sources
- [Current v5 strategy notes](STRATEGY_V5.md) — repository historical-study baseline and its limitations
- [Railway & Telegram deployment guide](RAILWAY_DEPLOYMENT_GUIDE.md) — exact Volume, variables, commands, and verification steps

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env
# Set DB_PATH=./history.db locally; add TELEGRAM_* only if wanted.
python -m unittest discover -s tests -v
python -m app.main
```

For Railway, mount a Volume at `/data` and set `DB_PATH=/data/history.db`. Follow the deployment guide for the complete variable list and the Telegram authorization check.

## Core Telegram commands

`/status` · `/balance` · `/signals` · `/trades` · `/stats` · `/get_db` · `/pause` · `/resume` · `/close_all`

`/force_long` and `/force_short` are paper-only plumbing tests at the last live price, not recommendations or production strategy signals.
