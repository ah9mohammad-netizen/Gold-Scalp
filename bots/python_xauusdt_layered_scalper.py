#!/usr/bin/env python3
"""
🪙 XAU-USDT Layered & 6-Pillar Quantitative Scalping Bot
---------------------------------------------------------
Target: XAU-USDT Perpetual Futures (e.g., Bybit, OKX, Binance via CCXT)
Architecture: Upgraded to the Institutional 6-Pillar Scalping Framework:

  Pillar 1: Venue & Execution Economics (Raw ECN spread <= $0.25/oz, Maker Post-Only)
  Pillar 2: Time-of-Day Kill Zones (00-04 Tokyo Sweep, 07-10 London Open, 12-16 NY Overlap)
  Pillar 3: Dynamic Regime Gating (3-State HMM / Volatility Shock & News Veto)
  Pillar 4: ICT/SMC Liquidity Sweep Reclaim & Order Block Pullback (No Breakout Traps)
  Pillar 5: Adaptive Exits & Time-Based Kill Switch (Mean return Z<=0.35, max 6 bars / 30m hold)
  Pillar 6: Capital Defense & Frequency Discipline (Max 2 trades/session, -3.0% daily DD cap)

Author: Professional Institutional Gold Scalper
Repository: Gold-Scalp
"""

import asyncio
import logging
from app.six_pillar_engine import SixPillarConfig, SixPillarDecisionEngine, six_pillar_engine
from bots.python_xauusdt_6pillar_scalper import (
    ActiveScalpPosition,
    SimulatedMarketCandle,
    XAUUSDT6PillarScalpingBot,
)

# Maintain backward compatibility with legacy imports
BotConfig = SixPillarConfig
LayeredDecisionEngine = SixPillarDecisionEngine
XAUUSDTScalpingBot = XAUUSDT6PillarScalpingBot

logger = logging.getLogger("XAU_Layered_Scalper")

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger.info("Starting XAU-USDT Layered Scalper (Upgraded to 6-Pillar Institutional Architecture)")
    bot = XAUUSDTScalpingBot(dry_run=True)
    asyncio.run(bot.start(cycles=3, delay_sec=0.2))
