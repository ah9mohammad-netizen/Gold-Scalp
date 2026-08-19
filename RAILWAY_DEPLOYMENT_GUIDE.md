# Railway deployment — v7 paper worker

## Required volume

Create one Railway Volume mounted at `/data`. The worker stores `/data/history.db`; `/get_db` creates a consistent export including SQLite WAL writes.

Do not put `history.db` in Git. Download periodic `/get_db` snapshots before wiping a volume.

## Raw Editor variables

Replace the two Telegram placeholders before pasting:

```env
ENV=production
PAPER_TRADING=true
PAPER_BALANCE=100.00
STRATEGY_VERSION=v7-adaptive-session-scalper
SYMBOL=XAU-USDT
EXCHANGE_ID=bybit
TIMEFRAME=5m
POLL_INTERVAL_SECONDS=60
ONLY_CLOSED_CANDLES=true
MAX_DATA_STALENESS_SECONDS=900
ALLOW_PROXY_FEEDS=false
MAX_LEVERAGE=50
RISK_PER_TRADE_PCT=0.50
V7_RISK_CAP_PCT=0.50
MAX_SPREAD_USD=0.40
MAX_OPEN_TRADES=1
MAX_DAILY_LOSS_PCT=2.0
MAX_TRADES_PER_DAY=4
ENTRY_COOLDOWN_SECONDS=600
LOSS_COOLDOWN_SECONDS=1200
MARGIN_CAP_PCT=25.0
V7_ALLOWED_SESSIONS=6-20
V7_MIN_SIGNAL_SCORE=4
V7_RANGE_Z_ENTRY=1.60
V7_RANGE_ADX_MAX=23.0
V7_TREND_ADX_MIN=18.0
V7_ATR_SHOCK_MULTIPLE=2.20
V7_RANGE_TP_RR=1.35
V7_TREND_TP_RR=1.60
V7_LIQUIDITY_TP_RR=1.50
V7_BE_TRIGGER_RR=1.00
V7_RANGE_MAX_HOLDING_BARS=8
V7_TREND_MAX_HOLDING_BARS=12
V7_MIN_STOP_COST_MULTIPLE=1.25
V7_MIN_TARGET_COST_MULTIPLE=1.50
EMA_TREND_PERIOD=200
EMA_FAST_PERIOD=50
EMA_PULLBACK_PERIOD=21
ZSCORE_PERIOD=20
ATR_PERIOD=14
ATR_AVG_LOOKBACK=50
RSI_PERIOD=14
ADX_PERIOD=14
MIN_ATR_USD=0.80
ASIAN_START_HOUR_UTC=0
ASIAN_END_HOUR_UTC=7
PAPER_EXECUTION_MODE=TAKER
PAPER_TAKER_FEE_RATE=0.0004
PAPER_MAKER_FEE_RATE=0.0001
PAPER_SLIPPAGE_USD=0.03
DB_PATH=/data/history.db
DATABASE_URL=sqlite:////data/history.db
TELEGRAM_BOT_TOKEN=PASTE_YOUR_EXISTING_BOT_TOKEN_HERE
TELEGRAM_CHAT_ID=PASTE_YOUR_EXISTING_CHAT_ID_HERE
```

Remove obsolete v5/v6 variables from Railway. The application now refuses non-v7 strategy versions.

## Cost controls

- `POLL_INTERVAL_SECONDS=60` is enough for completed M5 candles and cuts request activity substantially versus five-second polling.
- Bybit history is downloaded once at process start; later polls merge only the newest rows.
- The runtime uses only the Python standard library, avoiding large dependency installs on every build.
- `PAPER_EXECUTION_MODE=TAKER` remains the conservative baseline.
- `MAX_LEVERAGE` is a margin constraint, not a profit target.

## Deploy and verify

`railway.json` starts:

```bash
python -m app.main
```

After deployment:

1. `/status` — confirm v7, TAKER, direct feed, recent closed candle and `/data/history.db`.
2. `/balance` — confirm paper balance and 0.50% effective risk cap.
3. `/stats` — confirm market bars and decision audits are accumulating.
4. `/get_db` — confirm a downloadable database snapshot.
5. Test `/pause`, restart, `/status`, then `/resume` to verify persistent state.

The process intentionally aborts when `PAPER_TRADING=false`; no live executor is installed.
