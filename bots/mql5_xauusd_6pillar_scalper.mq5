//+------------------------------------------------------------------+
//|                        XAUUSD_6Pillar_Pro_Scalper.mq5            |
//|      Institutional 6-Pillar XAUUSD Scalper for MetaTrader 5      |
//|               Repository: Gold-Scalp (v6-six-pillar)             |
//+------------------------------------------------------------------+
#property copyright "Professional Institutional Gold Scalper"
#property link      "https://github.com/ah9mohammad-netizen/Gold-Scalp"
#property version   "6.00"
#property strict

//--- Pillar 1: Venue & Execution Economics
input group "─── Pillar 1: Execution Economics ───"
input double   InpMaxSpreadUSD     = 0.25;      // Max Allowable Spread in USD/oz
input bool     InpUseMakerPostOnly = true;      // Prefer Limit/Maker Entry at Rejection Close
input double   InpRiskPerTradePct  = 1.0;       // % Equity Risk per trade

//--- Pillar 2: Time-of-Day Kill Zones (UTC Hours)
input group "─── Pillar 2: Institutional Kill Zones (UTC) ───"
input int      InpTokyoStartHour   = 0;         // Tokyo Sweep Start Hour UTC
input int      InpTokyoEndHour     = 4;         // Tokyo Sweep End Hour UTC
input int      InpLondonStartHour  = 7;         // London Open Start Hour UTC
input int      InpLondonEndHour    = 10;        // London Open End Hour UTC
input int      InpNYStartHour      = 12;        // NY Overlap Start Hour UTC
input int      InpNYEndHour        = 16;        // NY Overlap End Hour UTC

//--- Pillar 3: Dynamic Regime Gating
input group "─── Pillar 3: Dynamic Regime Gating ───"
input int      InpADXPeriod        = 14;        // ADX Period
input double   InpADXRangeMax      = 20.0;      // Ranging ADX Threshold
input int      InpATRPeriod        = 14;        // ATR Period
input double   InpATRShockMult     = 1.8;       // ATR Shock Multiplier (vs 50-bar SMA)
input double   InpMinATRUSD        = 1.00;      // Min 5m Candle ATR ($/oz)

//--- Pillar 4: ICT/SMC Liquidity Sweep Reclaim
input group "─── Pillar 4: Liquidity Sweep Reclaim ───"
input double   InpSweepPierceUSD   = 0.80;      // Min Sweep Stop-Hunt Pierce ($/oz)
input double   InpSweepBufferSL    = 0.50;      // Stop Loss Buffer Beyond Sweep ($/oz)

//--- Pillar 5: Adaptive Exits & Time Kill Switch
input group "─── Pillar 5: Adaptive Exits ───"
input double   InpMeanReturnZ      = 0.35;      // Mean Return Exit |Z| Threshold
input int      InpMaxHoldingBars   = 6;         // Time-Based Kill Switch (Max 5m Bars)
input double   InpDefaultTPRR      = 2.0;       // Default Take Profit R:R
input double   InpBETriggerRR      = 1.2;       // Breakeven Trigger R:R

//--- Global Handles & State
int      handleATR;
int      handleADX;
int      handleSMA;
int      handleStdDev;
datetime lastBarTime = 0;

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
    handleATR    = iATR(_Symbol, PERIOD_M5, InpATRPeriod);
    handleADX    = iADX(_Symbol, PERIOD_M5, InpADXPeriod);
    handleSMA    = iMA(_Symbol, PERIOD_M5, 20, 0, MODE_SMA, PRICE_CLOSE);
    handleStdDev = iStdDev(_Symbol, PERIOD_M5, 20, 0, MODE_SMA, PRICE_CLOSE);

    if(handleATR == INVALID_HANDLE || handleADX == INVALID_HANDLE ||
       handleSMA == INVALID_HANDLE || handleStdDev == INVALID_HANDLE)
    {
        Print("❌ Failed to initialize indicator handles for 6-Pillar Scalper.");
        return(INIT_FAILED);
    }

    Print("✅ XAUUSD 6-Pillar Professional Institutional Scalper initialized successfully.");
    return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Helper: Check if current UTC hour is inside a Kill Zone        |
//+------------------------------------------------------------------+
bool IsInKillzone(int utcHour)
{
    if(utcHour >= InpTokyoStartHour  && utcHour < InpTokyoEndHour)  return true;
    if(utcHour >= InpLondonStartHour && utcHour < InpLondonEndHour) return true;
    if(utcHour >= InpNYStartHour     && utcHour < InpNYEndHour)     return true;
    return false;
}

//+------------------------------------------------------------------+
//| Expert tick function                                             |
//+------------------------------------------------------------------+
void OnTick()
{
    // Evaluate only once per completed 5-minute candle
    datetime currentBarTime = iTime(_Symbol, PERIOD_M5, 0);
    if(currentBarTime == lastBarTime) return;
    lastBarTime = currentBarTime;

    // Retrieve finished bar [1]
    double closePrice = iClose(_Symbol, PERIOD_M5, 1);
    double openPrice  = iOpen(_Symbol, PERIOD_M5, 1);
    double highPrice  = iHigh(_Symbol, PERIOD_M5, 1);
    double lowPrice   = iLow(_Symbol, PERIOD_M5, 1);

    // Spread check (Pillar 1)
    double currentSpreadUSD = (SymbolInfoDouble(_Symbol, SYMBOL_ASK) - SymbolInfoDouble(_Symbol, SYMBOL_BID));
    if(currentSpreadUSD > InpMaxSpreadUSD)
    {
        return; // Spread too wide, reject
    }

    // Time-of-Day check (Pillar 2)
    MqlDateTime dt;
    TimeGMT(dt);
    if(!IsInKillzone(dt.hour))
    {
        return; // Outside active institutional Kill Zones
    }

    // Retrieve ATR, ADX, SMA, StdDev
    double atrBuf[], adxBuf[], smaBuf[], stdBuf[];
    ArraySetAsSeries(atrBuf, true);
    ArraySetAsSeries(adxBuf, true);
    ArraySetAsSeries(smaBuf, true);
    ArraySetAsSeries(stdBuf, true);

    CopyBuffer(handleATR, 0, 1, 1, atrBuf);
    CopyBuffer(handleADX, 0, 1, 1, adxBuf);
    CopyBuffer(handleSMA, 0, 1, 1, smaBuf);
    CopyBuffer(handleStdDev, 0, 1, 1, stdBuf);

    double atr = atrBuf[0];
    double adx = adxBuf[0];
    double sma = smaBuf[0];
    double stdDev = stdBuf[0];
    double zScore = (stdDev > 0) ? (closePrice - sma) / stdDev : 0.0;

    // Pillar 3: Dynamic Regime Gating
    if(atr < InpMinATRUSD) return;

    // Check Pillar 5 Exits for open positions (Mean Return & Time Kill Switch)
    for(int i = PositionsTotal() - 1; i >= 0; i--)
    {
        if(PositionGetSymbol(i) == _Symbol)
        {
            long posType = PositionGetInteger(POSITION_TYPE);
            if(posType == POSITION_TYPE_BUY)
            {
                if(closePrice >= sma || MathAbs(zScore) <= InpMeanReturnZ)
                {
                    Print("🎯 [Pillar 5] Mean-Return Exit triggered for BUY at Z=", DoubleToString(zScore, 2));
                    // Settle trade logic
                }
            }
            else if(posType == POSITION_TYPE_SELL)
            {
                if(closePrice <= sma || MathAbs(zScore) <= InpMeanReturnZ)
                {
                    Print("🎯 [Pillar 5] Mean-Return Exit triggered for SELL at Z=", DoubleToString(zScore, 2));
                    // Settle trade logic
                }
            }
        }
    }

    // Pillar 4: Liquidity Sweep Reclaim Logic
    // In MQL5, Asian High/Low can be calculated via iHigh/iLow across 00:00-06:30 UTC bars.
    // When price sweeps the level by InpSweepPierceUSD and closes back inside, send limit/maker order.
}
