# Gold-Scalp — Gold Edge v5 (XAU-USDT)

24/7 gold engine driven by **research on your real 5m history** (443k bars).

## Strategy (v5)

**Z-Score mean reversion in strict ranges** (N30-style), not breakouts:

- Enter when \|Z\| ≥ **2.2** (SMA20) and **ADX ≤ 18**
- Turn-bar confirmation  
- SL **2.5×ATR** · TP **2.0R** · no early BE  
- Sessions **07–17 UTC** · risk **1%** · max **3**/day  

Breakout / ORB / EMA-cross families were tested and **rejected** (account-destroying on this sample).

## Docs

- [`STRATEGY_V5.md`](STRATEGY_V5.md) — research ranking + defaults  
- [`STRATEGY_V4.md`](STRATEGY_V4.md) / [`STRATEGY_V3.md`](STRATEGY_V3.md) — prior iterations  

## Stack

- Paper trading from **$100 USDT**  
- SQLite **`/data/history.db`** (Railway Volume)  
- Telegram UI (`/status` `/stats` `/get_db` …)  
- Live feed: Bybit / OKX / Binance PAXG / CCXT  

```bash
pip install -r requirements.txt
cp .env.example .env   # set TELEGRAM_* 
python -m app.main
```
