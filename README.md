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
- [Cost-aware main-history backtest](BACKTEST_MAIN_HISTORY_V5_COST_AWARE.md) — reproducible 443,451-bar run of the current baseline; negative net result means it remains paper-only
- [Trade forensics & walk-forward parameter research](TRADE_FORENSICS_AND_OPTIMIZATION.md) — every baseline trade is audited and attempted parameter changes are rejected on unseen data
- [Phase 2 regime-filter research](V6_REGIME_FILTER_RESEARCH.md) — slope, range, rejection, prior-range, and volume filters are tested and rejected on holdout data
- [Asian/London DST-aware research](LONDON_ASIAN_TIMEZONE_RESEARCH.md) — a separate Asian-range sweep/reclaim family compares fixed UTC against `Europe/London` local time and is rejected on holdout data
- [MTF trend-pullback research](MTF_TREND_PULLBACK_RESEARCH.md) — D1/H4/H1 → M15 → M5 trend alignment/pullback tests are rejected on unseen data
- [XAU strategy comparison](XAU_STRATEGY_COMPARISON.md) — common decision view across every tested XAU-only family; PAXG excluded
- [Macro-event veto research](XAU_EVENT_VETO_RESEARCH.md) — user-supplied ForexFactory calendar converted from Tehran display time to UTC; event avoidance alone does not rescue the MTF base strategy
- [Daily macro-regime research](XAU_DAILY_MACRO_REGIME_RESEARCH.md) — DXY, VIX, oil and stress gates reduce exposure but cannot repair the failed MTF base strategy
- [Impulse–pullback–reclaim discovery](XAU_IMPULSE_RECLAIM_DISCOVERY.md) — outcome labels reject the structural continuation premise before PnL optimisation
- [XAU data-quality audit](XAU_DATA_QUALITY_AUDIT.md) — two critical multi-day holes mean all current strategy conclusions are provisional until repaired or gap-guarded
- [Compressed-archive reconciliation](XAU_COMPRESSED_ARCHIVE_RECONCILIATION.md) — the 2004–2026 archive is valid but exactly preserves the recent missing windows
- [XAUUSDc M3 assessment](XAUUSDC_M3_DATA_QUALITY_AUDIT.md) — M3 data cannot reconstruct M5 and contains stale/repeated-bar contamination
- [Native M1/M5 reconciliation](XAU_M1_M5_RECONCILIATION.md) — native M1 validates an EET/EEST M5 server clock and supplies provenance-labelled repair bars
- [Canonical UTC research rerun](XAU_CANONICAL_RESEARCH_RERUN.md) — all strategy families re-tested after timezone correction, M1 repair, and gap guard
- [Execution-cost sensitivity](XAU_COST_SENSITIVITY.md) — fees materially affect v5, but low-cost scenarios still fail robust all-period validation
- [Regime + indicator architecture study](XAU_REGIME_INDICATOR_STACK.md) — pre-registered MACD/RSI/CCI/Bollinger/VWAP regime families, independently rejected under canonical cost-aware walk-forward testing; no composite is manufactured from failed families
- [Adaptive layered regime-tree sensitivity study](XAU_ADAPTIVE_REGIME_TREE.md) — a bounded, past-only sensitivity bank learns a configuration per bull/bear/range branch or explicitly chooses no-trade; all 35 forward branch decisions selected no-trade under current canonical cost assumptions
- [Current v5 strategy notes](STRATEGY_V5.md) — earlier repository historical-study baseline and its limitations
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
