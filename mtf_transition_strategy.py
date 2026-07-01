"""
Multi-Timeframe Transition Strategy Prototype
────────────────────────────────────────────
4H = macro structure / permission
1H = setup detection
15m = execution confirmation

This uses lessons from ANN V1/V2:
  - strongest recurring edge: short-side capitulation/distribution/expansion continuation
  - avoid trading every pair/setup just because validation looked good
  - use 4H to block lower-timeframe signals against macro context
  - use 15m trigger to avoid entering directly on 1H signal close

Research only, not live bot.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
from pathlib import Path
import math
import numpy as np
import pandas as pd

from market_structure_strategy import prepare as prepare_1h, ema, atr, adx, rsi, df_to_md
from ann_transition_framework import setup_candidates_at

DATA=Path('data'); OUT=Path('results'); OUT.mkdir(exist_ok=True)
INIT=700.0; FEE=0.0005; SLIP=0.0010


def load(sym, tf):
    p=DATA/f'{sym}_{tf}.csv'
    if not p.exists(): return pd.DataFrame()
    df=pd.read_csv(p,index_col=0,parse_dates=True)
    df.index=pd.to_datetime(df.index,utc=True)
    return df.sort_index()


def prepare_4h(sym):
    d=load(sym,'4h')
    if d.empty: return d
    c,h,l=d.close,d.high,d.low
    d['ema50']=ema(c,50); d['ema200']=ema(c,200); d['ema400']=ema(c,400)
    d['atr14']=atr(h,l,c,14); d['atr_pct']=d.atr14/c
    d['adx14']=adx(h,l,c,14); d['rsi14']=rsi(c,14)
    d['ema200_slope']=d.ema200.pct_change(12); d['ema400_slope']=d.ema400.pct_change(24)
    d['ret24h']=c.pct_change(6); d['ret72h']=c.pct_change(18)
    d['hi60']=h.rolling(60).max(); d['lo60']=l.rolling(60).min()
    d['range_pos']=((c-d.lo60)/(d.hi60-d.lo60).replace(0,np.nan)).clip(0,1)
    d['macro_state']='NEUTRAL'
    bull=(c>d.ema200)&(d.ema50>d.ema200)&(d.ema200_slope>0)&(d.adx14>18)
    bear=(c<d.ema200)&(d.ema50<d.ema200)&(d.ema200_slope<0)&(d.adx14>18)
    compression=(d.adx14<18)&(d.atr_pct<d.atr_pct.rolling(120).quantile(.35))
    distribution=(c>d.ema200)&(d.range_pos>.65)&(d.rsi14<d.rsi14.shift(6))&(d.ret24h<0)
    capitulation=(c<d.ema200)&((c<d.lo60.shift(1))|(d.ret24h<-2*d.atr_pct))&(d.adx14>18)
    recovery=(c<d.ema200)&(c>d.ema50)&(d.rsi14>45)&(d.ret24h>0)
    d.loc[compression,'macro_state']='COMPRESSION'
    d.loc[bull,'macro_state']='EXPANSION_UP'
    d.loc[bear,'macro_state']='EXPANSION_DOWN'
    d.loc[distribution,'macro_state']='DISTRIBUTION'
    d.loc[capitulation,'macro_state']='CAPITULATION'
    d.loc[recovery,'macro_state']='RECOVERY'
    d['allow_short']=d.macro_state.isin(['EXPANSION_DOWN','DISTRIBUTION','CAPITULATION']) | ((c<d.ema200)&(d.ema200_slope<0))
    d['allow_long']=d.macro_state.isin(['EXPANSION_UP','RECOVERY']) | ((c>d.ema200)&(d.ema200_slope>0))
    return d.dropna().copy()


def prepare_15m(sym):
    d=load(sym,'15m')
    if d.empty: return d
    c,h,l,v=d.close,d.high,d.low,d.volume
    d['ema20']=ema(c,20); d['ema50']=ema(c,50); d['ema200']=ema(c,200)
    d['atr14']=atr(h,l,c,14); d['rsi14']=rsi(c,14)
    d['lo32']=l.rolling(32).min(); d['hi32']=h.rolling(32).max()
    d['lo96']=l.rolling(96).min(); d['hi96']=h.rolling(96).max()
    d['vol_z']=(v-v.rolling(96).mean())/v.rolling(96).std().replace(0,np.nan)
    body=(d.close-d.open).abs()/d.close
    d['bear_reject']=(d.close<d.open)&((d.high-d[['open','close']].max(axis=1))/(d.high-d.low).replace(0,np.nan)>.25)
    d['bull_reject']=(d.close>d.open)&((d[['open','close']].min(axis=1)-d.low)/(d.high-d.low).replace(0,np.nan)>.25)
    d['body_pct']=body
    return d.dropna().copy()


def macro_at(m4, t):
    loc=m4.index.searchsorted(t, side='right')-1
    if loc<0: return None
    return m4.iloc[loc]


def trigger_15m(d15, t, side, setup):
    # Search from after the 1H signal close up to 4 candles later.
    start=d15.index.searchsorted(t, side='right')
    end=min(len(d15)-2, start+4)
    for k in range(start,end+1):
        r=d15.iloc[k]
        if side=='SHORT':
            breakdown = r.close < d15.lo32.iloc[k-1]
            reject = (r.high>=min(r.ema20,r.ema50)) and (r.close<r.ema20) and (r.close<r.open)
            momentum = (r.close<r.ema50) and (r.rsi14<52)
            if momentum and (breakdown or reject or (setup in ['capitulation_continuation','distribution_break'] and r.close<r.open)):
                return k, '15m_short_confirm'
        else:
            breakout = r.close > d15.hi32.iloc[k-1]
            reject = (r.low<=max(r.ema20,r.ema50)) and (r.close>r.ema20) and (r.close>r.open)
            momentum = (r.close>r.ema50) and (r.rsi14>48)
            if momentum and (breakout or reject or (setup in ['recovery_continuation','capitulation_recovery'] and r.close>r.open)):
                return k, '15m_long_confirm'
    return None, None


SHORT_SETUPS={'capitulation_continuation','distribution_break','expansion_pullback_short','compression_down_break'}
LONG_SETUPS={'recovery_continuation','capitulation_recovery','compression_up_break'}
# Do not use expansion_pullback_long by default; V1/V2 showed it was toxic in this market.

@dataclass
class Trade:
    pair:str; split:str; side:str; setup:str; macro_state:str
    signal_time:pd.Timestamp; entry_time:pd.Timestamp; exit_time:pd.Timestamp
    entry:float; exit:float; sl:float; tp:float; reason:str; bars:int; net_pct:float; equity:float


def run(sym, split_name, h1, m4, d15):
    equity=INIT; trades=[]; last_exit_time=pd.Timestamp.min.tz_localize('UTC')
    # Restrict 1H signals to 15m available window.
    h1=h1[(h1.index>=d15.index[0])&(h1.index<=d15.index[-1])].copy()
    for i in range(100, len(h1)-2):
        t=h1.index[i]
        if t<=last_exit_time: continue
        mac=macro_at(m4,t)
        if mac is None: continue
        candidates=setup_candidates_at(h1,i)
        if not candidates: continue
        for side,setup in candidates:
            if side=='SHORT' and setup not in SHORT_SETUPS: continue
            if side=='LONG' and setup not in LONG_SETUPS: continue
            if side=='SHORT' and not bool(mac.allow_short): continue
            if side=='LONG' and not bool(mac.allow_long): continue
            # Extra learned restrictions: longs only on stronger recovery names/context.
            if side=='LONG' and setup in ['recovery_continuation','capitulation_recovery']:
                if mac.macro_state not in ['RECOVERY','EXPANSION_UP'] and sym not in ['ENA','HYPE']:
                    continue
            trig_i, trig_reason=trigger_15m(d15,t,side,setup)
            if trig_i is None: continue
            if d15.index[trig_i]<=last_exit_time: continue
            entry_i=trig_i+1
            if entry_i>=len(d15): continue
            raw=float(d15.open.iloc[entry_i])
            entry=raw*(1+SLIP) if side=='LONG' else raw*(1-SLIP)
            r=d15.iloc[trig_i]; a=float(h1.atr14.iloc[i])
            if not math.isfinite(a) or a<=0: continue
            if side=='LONG':
                sl=min(float(d15.lo96.iloc[trig_i]), entry-0.9*a)
                sl=max(sl, entry-2.2*a)
                risk=entry-sl; tp=entry+1.8*risk
            else:
                sl=max(float(d15.hi96.iloc[trig_i]), entry+0.9*a)
                sl=min(sl, entry+2.2*a)
                risk=sl-entry; tp=entry-1.8*risk
            if risk<=0 or risk/entry<0.0025 or risk/entry>0.10: continue
            max_j=min(len(d15)-1, entry_i+96*4) # max 96h
            exit_raw=float(d15.close.iloc[max_j]); exit_i=max_j; reason='TIME'
            for j in range(entry_i,max_j+1):
                rr=d15.iloc[j]
                # exit if 4H macro flips hard opposite
                macj=macro_at(m4,d15.index[j])
                if side=='LONG':
                    if rr.low<=sl: exit_raw=sl; exit_i=j; reason='SL'; break
                    if rr.high>=tp: exit_raw=tp; exit_i=j; reason='TP'; break
                    if macj is not None and macj.macro_state in ['DISTRIBUTION','CAPITULATION','EXPANSION_DOWN'] and rr.close<rr.ema50:
                        exit_raw=float(rr.close); exit_i=j; reason='MACRO_FLIP'; break
                else:
                    if rr.high>=sl: exit_raw=sl; exit_i=j; reason='SL'; break
                    if rr.low<=tp: exit_raw=tp; exit_i=j; reason='TP'; break
                    if macj is not None and macj.macro_state in ['RECOVERY','EXPANSION_UP'] and rr.close>rr.ema50:
                        exit_raw=float(rr.close); exit_i=j; reason='MACRO_FLIP'; break
            ex=exit_raw*(1-SLIP) if side=='LONG' else exit_raw*(1+SLIP)
            gross=ex/entry-1 if side=='LONG' else entry/ex-1
            net=gross-2*FEE; equity*=1+net
            trades.append(Trade(sym,split_name,side,setup,str(mac.macro_state),t,d15.index[entry_i],d15.index[exit_i],round(entry,8),round(ex,8),round(sl,8),round(tp,8),reason,int(exit_i-entry_i+1),100*net,equity))
            last_exit_time=d15.index[exit_i]
            break
    return trades, summarize(sym,split_name,trades)


def summarize(sym,split,trades):
    if not trades:
        return dict(pair=sym,split=split,trades=0,win_rate=0,return_pct=0,final=INIT,profit_factor=0,expectancy=0,max_dd=0,sharpe=0,avg_bars=0)
    r=np.array([t.net_pct/100 for t in trades]); wins=r[r>0]; losses=r[r<=0]
    eq=np.array([INIT]+[t.equity for t in trades]); peak=np.maximum.accumulate(eq); dd=(eq/peak-1)*100
    return dict(pair=sym,split=split,trades=len(trades),win_rate=round(100*len(wins)/len(trades),1),return_pct=round(100*(eq[-1]/INIT-1),1),final=round(eq[-1],2),profit_factor=round(wins.sum()/abs(losses.sum()),2) if len(losses) and abs(losses.sum())>0 else np.inf,expectancy=round(100*r.mean(),3),max_dd=round(abs(dd.min()),1),sharpe=round(r.mean()/r.std(ddof=1)*math.sqrt(len(r)),2) if len(r)>1 and r.std(ddof=1)>0 else 0,avg_bars=round(np.mean([t.bars for t in trades]),1))


def split_by_15m(h1,d15):
    # Split by recent 15m history; apply same dates to h1.
    n=len(d15); t1=d15.index[int(n*.5)]; t2=d15.index[int(n*.75)]
    return {
        'train_recent': h1[h1.index<t1],
        'val_recent': h1[(h1.index>=t1)&(h1.index<t2)],
        'test_recent': h1[h1.index>=t2]
    }


def main():
    syms=['BTC','ETH','SOL','BNB','HYPE','ENA','AVAX']
    stats=[]; alltr=[]; profiles=[]
    for sym in syms:
        h1=prepare_1h(sym); m4=prepare_4h(sym); d15=prepare_15m(sym)
        if h1.empty or m4.empty or d15.empty:
            print('missing',sym); continue
        print(sym, '15m', d15.index[0], d15.index[-1], len(d15))
        profiles.append({'pair':sym,'15m_start':d15.index[0],'15m_end':d15.index[-1],'15m_rows':len(d15),'4h_macro_short_pct':round(100*m4.allow_short.mean(),1),'4h_macro_long_pct':round(100*m4.allow_long.mean(),1)})
        parts=split_by_15m(h1,d15)
        for split,hpart in parts.items():
            tr,st=run(sym,split,hpart,m4,d15)
            stats.append(st); alltr += tr
    sdf=pd.DataFrame(stats); tdf=pd.DataFrame([asdict(t) for t in alltr]); pdf=pd.DataFrame(profiles)
    sdf.to_csv(OUT/'mtf_transition_stats.csv',index=False)
    tdf.to_csv(OUT/'mtf_transition_trades.csv',index=False)
    pdf.to_csv(OUT/'mtf_transition_profile.csv',index=False)
    cols=['pair','split','trades','win_rate','return_pct','max_dd','profit_factor','expectancy','sharpe','avg_bars','final']
    rep=['# Multi-Timeframe Transition Strategy Prototype','','4H macro permission + 1H structure setup + 15m execution confirmation.','','## Data/profile','',df_to_md(pdf),'','## Results','',df_to_md(sdf[cols].sort_values(['split','return_pct'],ascending=[True,False]))]
    if len(tdf):
        setup=tdf.groupby(['split','pair','setup','side','macro_state']).agg(trades=('net_pct','size'),wr=('net_pct',lambda x:round(100*(x>0).mean(),1)),ret_sum=('net_pct',lambda x:round(x.sum(),1)),avg=('net_pct',lambda x:round(x.mean(),2))).reset_index().sort_values(['split','ret_sum'],ascending=[True,False])
        setup.to_csv(OUT/'mtf_transition_setup_breakdown.csv',index=False)
        rep += ['','## Setup breakdown','',df_to_md(setup.head(120))]
    (OUT/'mtf_transition_report.md').write_text('\n'.join(rep),encoding='utf-8')
    print(sdf[cols].to_string(index=False))
    print('Saved results/mtf_transition_report.md')

if __name__=='__main__': main()
