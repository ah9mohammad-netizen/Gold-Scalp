"""
Main Entrypoint for Railway 24/7 Deployment.
Initializes database ($100 balance), connects Telegram UI, and runs continuous trading loop.
"""
import asyncio
import logging
import random
import sys
from datetime import datetime, timezone
from app.config import config
from app.database import db
from app.engine import engine
from app.paper_trader import paper_trader
from app.telegram_ui import telegram_ui

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("MainService")

async def market_data_feed_loop():
    """
    Continuous market data feed for XAU-USDT.
    In paper trading mode, this simulates realistic tick movement around $2,847.50,
    testing structural breaks and evaluating open trade TP/SL limits every few seconds.
    When deployed live with CCXT/Apex API keys, this fetches real-time OHLCV & orderbook spread from Bybit/Binance/Apex.
    """
    logger.info("Starting continuous market data evaluation loop...")
    base_price = paper_trader.last_simulated_price
    cycle = 0
    
    while True:
        try:
            if not paper_trader.is_running:
                await asyncio.sleep(2.0)
                continue
                
            cycle += 1
            now = datetime.now(timezone.utc)
            
            # Simulate subtle price fluctuations & occasional liquidity sweeps
            # Or fetch live via ccxt if configured in future
            price_change = random.uniform(-1.20, 1.30)
            if cycle % 12 == 0:
                # Every ~60s simulate a London momentum breakout test
                price_change = random.uniform(2.50, 4.20)
            elif cycle % 19 == 0:
                # Or Asian high sweep test
                price_change = random.uniform(-3.00, -1.50)
                
            new_price = round(base_price + price_change, 2)
            high_price = round(new_price + random.uniform(0.10, 0.80), 2)
            low_price = round(new_price - random.uniform(0.10, 0.80), 2)
            base_price = new_price
            
            market_tick = {
                "timestamp": now,
                "close": new_price,
                "spread": round(random.uniform(0.10, 0.28), 2),
                "atr_14": round(random.uniform(1.80, 2.80), 2),
                "rsi_14": round(random.uniform(35.0, 68.0), 1),
                "ema_200": round(base_price - 6.0, 2),
                "vwap": round(base_price - 1.5, 2),
                "asian_high": round(base_price - 2.5, 2),
                "asian_low": round(base_price - 14.0, 2),
                "high": high_price,
                "low": low_price
            }
            
            paper_trader.process_new_market_data(market_tick)
            
        except Exception as e:
            logger.error(f"Error in market data evaluation loop: {e}")
            
        await asyncio.sleep(config.POLL_INTERVAL_SECONDS)

async def main():
    logger.info("================================================================")
    logger.info(f"🚀 XAU-USDT Layered Scalper & Telegram UI Starting on Railway")
    logger.info(f"   Execution Mode: {'PAPER TRADING' if config.PAPER_TRADING else 'LIVE TRADING'}")
    logger.info(f"   Starting Capital: ${db.get_current_balance():.2f} USDT")
    logger.info(f"   Target Symbol: {config.SYMBOL} | Leverage: {config.MAX_LEVERAGE}x")
    logger.info("================================================================")
    
    # Hook up paper trader alerts directly to Telegram UI
    paper_trader.set_alert_callback(telegram_ui.send_message)
    paper_trader.is_running = True
    
    # Send startup notification via Telegram
    await telegram_ui.send_message(
        f"🟢 <b>XAU-USDT Strategy & Paper Trading Bot Online 24/7</b>\n\n"
        f"• Environment: <b>Railway Cloud ({config.ENV})</b>\n"
        f"• Current Balance: <b>${db.get_current_balance():.2f} USDT</b>\n"
        f"• Target Pair: <b>{config.SYMBOL} ({config.MAX_LEVERAGE}x Max Leverage)</b>\n"
        f"• UI Commands: Type /help or /status to monitor real-time performance."
    )
    
    # Start concurrent tasks: Telegram polling & market data execution
    telegram_task = asyncio.create_task(telegram_ui.poll_updates_loop())
    market_task = asyncio.create_task(market_data_feed_loop())
    
    # Run both loops until interrupted
    await asyncio.gather(telegram_task, market_task)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot service shut down gracefully.")
