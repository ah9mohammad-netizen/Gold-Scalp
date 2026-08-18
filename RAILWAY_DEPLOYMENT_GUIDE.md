# Railway 24/7 deployment and Telegram operations

**Mode:** paper trading only

**Instrument:** direct `XAU-USDT` perpetual feed (Bybit preferred, OKX fallback)

**Starting account:** 100 USDT

**Persistent file:** Railway Volume mounted at `/data` → `/data/history.db`

> The service has no live ApeX execution adapter. It intentionally aborts if `PAPER_TRADING=false`; do not add exchange credentials expecting it to trade live.

---

## 1. Railway Volume (required)

1. In the Railway service, open **Volumes** → **Create Volume**.
2. Set **mount path** to `/data`.
3. Deploy the service. The worker writes `/data/history.db` plus temporary SQLite WAL files as needed.

The database uses SQLite WAL for safe concurrent reads/writes. `/get_db` creates a consistent standalone backup before sending it to Telegram, so recent WAL records are included.

## 2. Railway variables

Copy the values below into **Railway → Service → Variables**. Never commit a real Telegram token or future API key.

```env
ENV=production
PAPER_TRADING=true
PAPER_BALANCE=100.00
STRATEGY_VERSION=v7-adaptive-session-scalper

SYMBOL=XAU-USDT
EXCHANGE_ID=bybit
TIMEFRAME=5m
POLL_INTERVAL_SECONDS=5
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
V7_RANGE_ADX_MAX=23
V7_TREND_ADX_MIN=18
V7_ATR_SHOCK_MULTIPLE=2.20
V7_RANGE_TP_RR=1.35
V7_TREND_TP_RR=1.60
V7_LIQUIDITY_TP_RR=1.50
V7_BE_TRIGGER_RR=1.00
V7_RANGE_MAX_HOLDING_BARS=8
V7_TREND_MAX_HOLDING_BARS=12
V7_MIN_STOP_COST_MULTIPLE=1.25
V7_MIN_TARGET_COST_MULTIPLE=1.50

# Conservative baseline. MAKER_POST_ONLY requires a separately reviewed fill model.
PAPER_EXECUTION_MODE=TAKER
PAPER_TAKER_FEE_RATE=0.0004
PAPER_MAKER_FEE_RATE=0.0001
PAPER_SLIPPAGE_USD=0.03

DB_PATH=/data/history.db
DATABASE_URL=sqlite:////data/history.db
TELEGRAM_BOT_TOKEN=123456:replace_me
TELEGRAM_CHAT_ID=replace_me
```

### Important variable notes

- `ALLOW_PROXY_FEEDS=false` means the bot will remain flat rather than silently use PAXG as XAU-USDT. Turn it on only for an explicitly labelled proxy experiment.
- `ONLY_CLOSED_CANDLES=true` avoids acting on an updating 5-minute candle. The service polls frequently, but a candle is consumed once.
- `MAX_LEVERAGE` is only a margin constraint; position size is based on the stop/risk budget. It is **not** a profit target.
- v7 sizes from **stop distance plus estimated round-trip costs** and caps effective risk at 0.50% while it is unvalidated.
- `PAPER_EXECUTION_MODE=TAKER` is intentional. Selecting a strategy version does not prove a post-only maker order would fill.
- Never tune paper fees/slippage to zero. The ledger stores gross PnL, simulated fees, and net PnL separately.

## 3. Telegram setup

1. Create a bot using `@BotFather` and set `TELEGRAM_BOT_TOKEN`.
2. Start a private chat with the bot and send `/start`.
3. Obtain the chat ID from `https://api.telegram.org/bot<TOKEN>/getUpdates` and set `TELEGRAM_CHAT_ID`.
4. Redeploy/restart the Railway service.

When `TELEGRAM_CHAT_ID` is set, commands from other chats are ignored. Do not put the token in chat, source control, or a public issue.

## 4. Deploy and verify

`railway.json` starts the service as:

```bash
python -m app.main
```

The worker has an on-failure restart policy. After deployment, inspect Railway logs for:

```text
XAU-USDT Layered Scalper + Telegram UI starting
mode=PAPER | balance=$100.00
```

Then use Telegram:

1. `/status` — confirm strategy `v7-adaptive-session-scalper`, fee model `TAKER`, direct feed source, last **closed** bar, and database path.
2. `/balance` — confirm 100-USDT realized balance, 0.50% risk cap, and zero open margin.
3. `/get_db` — confirm a `history.db` document arrives.
4. `/pause`, restart the service, then `/status` — confirm the pause persisted.
5. `/resume` only after the above checks pass.

If no direct XAU feed is available, the bot logs the failure and opens no synthetic or proxy trade. This is expected safe behavior.

## 5. Telegram command reference

| Command | Action |
|---|---|
| `/status` | Feed, latest closed candle, indicators, entry state, marked equity, DB path |
| `/balance` | Realized balance, fee-aware open PnL, equity, used/free margin |
| `/get_db` | Sends a consistent SQLite `history.db` snapshot for analysis |
| `/signals` | Latest executed setup records and their indicators |
| `/trades` | Open paper position plus recent closed positions |
| `/stats` | Net PnL, fee total, profit factor, exits and equity |
| `/pause` / `/resume` | Persistently disable / permit **new** paper entries; open positions remain managed |
| `/close_all` | Emergency paper flatten at the latest executable quote assumption |
| `/force_long` / `/force_short` | Opens a clearly labelled paper-only test at the last live price; not a strategy signal |

## 6. Database contents

| Table | Purpose |
|---|---|
| `signals` | closed-bar source/time, setup version, indicators, reference/fill price, SL/TP, risk and layer notes |
| `trades` | filled entry/exit, margin, gross PnL, entry/exit fees, **net** PnL and exit reason |
| `account_history` | initial 100-USDT deposit and every realized balance change |
| `bot_state` | persistent pause flag and last processed candle for restart idempotency |

Open it with DB Browser for SQLite, DBeaver, or Python/pandas. Analyse **net** PnL; a gross-PnL chart that ignores spread, fee, and slippage is not a go-live metric.

## 7. Local smoke test

```bash
pip install -r requirements.txt
cp .env.example .env
# set DB_PATH=./history.db and optional TELEGRAM_* values in .env
python -m unittest discover -s tests -v
python -m app.main
```

`python-dotenv` loads `.env` locally without overriding Railway variables. Press `Ctrl+C` for a clean shutdown.

## 8. Later ApeX work

Do not simply flip an environment flag. A live adapter needs a separate security and execution review: contract discovery, multiplier/tick/step validation, isolated-margin policy, signed order IDs, fill/order WebSocket reconciliation, idempotency, stop/TP placement confirmation, funding, liquidation metrics, API rate limits, and an emergency kill switch. Keep this database and Telegram UI; replace only the audited execution adapter after a sufficiently long paper/forward test.
