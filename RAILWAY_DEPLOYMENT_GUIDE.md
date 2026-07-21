# 🚂 Railway 24/7 Deployment & Telegram UI Guide (`XAU-USDT` Paper Trading Engine)

*Author: Senior Quantitative Gold Trader (`Gold-Scalp` Repository)*  
*Target Asset: `XAU-USDT` (Crypto Perpetual Futures)*  
*Initial Paper Balance: `$100.00 USDT` (`50x` Max Leverage)*

---

## 🏛️ System Architecture Overview

We have engineered and integrated a complete, asynchronous, 24/7 quantitative trading system right inside `/home/user/Gold-Scalp`. The system runs **Paper Trading (`paper_trading = True`)** on `XAU-USDT` starting with exactly **`$100.00 USDT`**, storing every signal, trade, and balance change inside a persistent database (`SQLite` locally or `PostgreSQL` on Railway), and communicating bidirectionally with you via a **Telegram Bot UI**.

```
+-----------------------------------------------------------------------------------+
|                        RAILWAY 24/7 CLOUD WORKER (`python -m app.main`)           |
+-----------------------------------------------------------------------------------+
                                   │
         ┌─────────────────────────┼─────────────────────────┐
         ▼                         ▼                         ▼
+---------------------+   +---------------------+   +---------------------+
| Layered Decision    |   | Paper Trading Engine|   | Database Engine     |
| Engine (app/engine) |   | (app/paper_trader)  |   | (app/database.py)   |
+---------------------+   +---------------------+   +---------------------+
| • Checks 4 Tiers    |   | • Manages $100 Bal  |   | • Table: signals    |
| • Exact $100 Sizing |   | • Tick SL/TP1/TP2   |   | • Table: trades     |
|   (Risk / SL Dist)  |   | • Trailing Breakeven|   | • Table: history    |
+---------------------+   +---------------------+   +---------------------+
         ▲                                                   │
         │ (Evaluates & Executes)                            │ (Persists State)
         └─────────────────────────┬─────────────────────────┘
                                   ▼
+-----------------------------------------------------------------------------------+
|                  TELEGRAM BOT UI & PUSH ALERTS (`app/telegram_ui.py`)             |
+-----------------------------------------------------------------------------------+
| • Outgoing Push Alerts: Instant Trade Opened, SL/TP Hit, Trailing Stop updates    |
| • Incoming Commands: /status | /balance | /signals | /trades | /stats | /close_all|
+-----------------------------------------------------------------------------------+
```

---

## ⚙️ How Position Sizing & Margin Work for `$100.00 USDT` Starting Capital

When trading `XAU-USDT` perpetual futures with a **`$100.00` account balance** at **`50x` leverage**, naive fixed lot sizes ($1.00\text{ oz}$ or $0.50\text{ oz}$) will immediately wipe out your account on a minor $\$3.00$ spike.

Our `LayeredDecisionEngine` computes exact position sizes dynamically based on your **Account Equity Risk Percentage (`1.5% = $1.50 per trade`)** and the **Distance to Stop Loss (`ATR_14 * 1.5`)**:

$$\text{Contract Size (troy oz)} = \frac{\text{Dollar Risk Limit (`$1.50`)}}{| \text{Entry Price} - \text{Stop Loss Price} |}$$

$$\text{Required Margin (USDT)} = \frac{\text{Entry Price} \times \text{Contract Size (`oz`)}}{\text{Max Leverage (`50x`)}}$$

### Example Calculation from Our Live Sandbox Verification:
* **Current Account Balance:** `$100.00 USDT`
* **Entry Price:** `$2,847.50 / oz`
* **Dynamic Stop Loss:** `$2,843.90` ($\text{Distance} = \$3.60$)
* **Exact Position Size (`size_oz`):** $\frac{\$1.50}{\$3.60} = \mathbf{0.4167\text{ oz}}$
* **Notional Position Value:** $\$2,847.50 \times 0.4167 = \$1,186.55$
* **Required Margin at `50x`:** $\frac{\$1,186.55}{50} = \mathbf{\$23.73\text{ USDT}}$ ($\approx 23.7\%$ of your capital)
* **If TP1 Hit (`+2.0R` R:R):** You gain **`+$3.00 USDT`**, lifting your balance from **`$100.00` to `$103.00 USDT`** (`+3.0%` account growth in a single scalp!).

---

## 📂 Complete Application Directory Structure (`Gold-Scalp`)

```
Gold-Scalp/
├── app/
│   ├── __init__.py         # Package initialization
│   ├── config.py           # Config variables (PAPER_BALANCE=100.00, SYMBOL=XAU-USDT, etc.)
│   ├── database.py         # SQLAlchemy & SQLite/Postgres ORM engine (signals, trades, history)
│   ├── engine.py           # 4-Layer Decision Engine & dynamic $100 position sizing
│   ├── paper_trader.py     # Paper execution loop: monitors ticks, triggers TP/SL hits, updates DB
│   ├── telegram_ui.py      # Async Telegram bot UI with interactive commands & push alerts
│   └── main.py             # Main async entrypoint running 24/7
├── Procfile                # Railway worker config (`worker: python -m app.main`)
├── railway.json            # Railway deployment metadata
├── requirements.txt        # Production dependencies (aiogram, sqlalchemy, ccxt, aiohttp)
├── .env.example            # Environment variables template
├── GOLD_DAY_TRADING_AUTOMATION_AND_STRATEGIES.md # Comprehensive quantitative research
└── RAILWAY_DEPLOYMENT_GUIDE.md # This deployment guide
```

---

## 🗄️ Database Schema & Storage

Every transaction, signal, and balance change is permanently saved:

1. **`signals` Table:** Records `timestamp`, `symbol`, `direction`, `entry_price`, `sl_price`, `tp1_price`, `tp2_price`, `layer1_regime`, `layer2_structure`, `layer3_momentum`, and `status` (`NEW`, `EXECUTED`, `SKIPPED`).
2. **`trades` Table:** Records `signal_id`, `symbol`, `direction`, `entry_price`, `sl_price`, `tp1_price`, `tp2_price`, `size_oz`, `leverage`, `required_margin_usd`, `opened_at`, `closed_at`, `exit_price`, `pnl_usd`, `pnl_pct`, `exit_reason` (`TP1_HIT`, `TP2_HIT`, `SL_HIT`, `MANUAL_CLOSE`), and `status` (`OPEN`, `CLOSED`).
3. **`account_history` Table:** Records exact balance progression (`balance_before`, `balance_after`, `change_usd`, `change_reason`, and `trade_id`). Starts automatically at `balance_after = 100.00 USDT`.

---

## 🤖 Telegram Bot UI Commands (`app/telegram_ui.py`)

Once deployed on Railway with your `TELEGRAM_BOT_TOKEN`, open your Telegram Bot and type any of these interactive commands:

| Command | Action & Return Preview |
| :--- | :--- |
| **`/status`** | Displays 24/7 bot status, execution mode (`PAPER TRADING ($100 Capital)`), last price, and active trade count. |
| **`/balance`** | Shows your real-time paper balance (`$100.00 -> $103.00`), total PnL `$ and %`, and exact dollar risk per trade. |
| **`/signals`** | Lists the last 5 signals generated by the `LayeredDecisionEngine` along with structural reasoning and status. |
| **`/trades`** | Displays all currently active open positions (Entry, SL, TP1, Margin) and recent closed trades with exact PnL. |
| **`/stats`** | Returns comprehensive win rate (`%`), total return (`%`), profit factor, best win, and worst loss. |
| **`/close_all`** | **Emergency Override:** Immediately closes all active open paper positions at current market price and updates DB. |
| **`/pause` / `/resume`** | Toggles whether the bot opens new trades while continuing to monitor existing positions for SL/TP hits. |
| **`/force_long` / `/force_short`** | Dispatches a synthetic structural breakout tick to test live Telegram alert & paper order flow directly. |

---

## 🚀 Step-by-Step Railway Deployment Guide (Take 3 Minutes)

To deploy this exact repository (`Gold-Scalp`) to **Railway (`railway.app`)** to run 24/7 right now:

### Step 1: Connect GitHub Repository to Railway
1. Log in to [Railway.app](https://railway.app/) and click **+ New Project**.
2. Select **Deploy from GitHub repo** and choose `ah9mohammad-netizen/Gold-Scalp` (branch `arena/019f837d-gold-scalp` or `main`).

### Step 2: Set Environment Variables
In your Railway project dashboard, go to **Variables** and add:
```env
ENV=production
PAPER_TRADING=true
PAPER_BALANCE=100.00
SYMBOL=XAU-USDT
EXCHANGE_ID=bybit
MAX_LEVERAGE=50
RISK_PER_TRADE_PCT=1.5
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
TELEGRAM_CHAT_ID=your_telegram_chat_id_here
```
*(Optional)* If you want persistent cloud PostgreSQL instead of SQLite, click **+ New** $\rightarrow$ **Database** $\rightarrow$ **PostgreSQL** in Railway. Railway will automatically inject `DATABASE_URL=postgresql://...` into your bot worker!

### Step 3: Deploy & Monitor
1. Railway will automatically read `railway.json` and `Procfile` and launch `python -m app.main`.
2. Within 15 seconds, your Telegram Bot will buzz with the startup alert:  
   `🟢 XAU-USDT Strategy & Paper Trading Bot Online 24/7 | Starting Balance: $100.00 USDT`!
