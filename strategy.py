import json
from pathlib import Path
import numpy as np
import pandas as pd
import joblib

# Import research feature functions from parent repo.
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from market_structure_strategy import ema, atr, adx, rsi, classify
from ann_transition_framework import setup_candidates_at, add_meta_features
from mtf_transition_strategy import prepare_4h as _prepare_4h_base, prepare_15m as _prepare_15m_base, macro_at, trigger_15m
from ann_mtf_transition_v3 import (
    SHORT_SETUPS, LONG_SETUPS, get_4h_features, get_1h_features, get_15m_features, geometry, NUM_COLS, CAT_COLS, FEATURE_COLS
)

class StrategyBrain:
    def __init__(self, model_path, meta_path):
        base=Path(__file__).resolve().parent
        mp=Path(model_path); mt=Path(meta_path)
        if not mp.is_absolute(): mp=base/mp
        if not mt.is_absolute(): mt=base/mt
        self.model=joblib.load(mp)
        self.meta=json.loads(mt.read_text())
        self.columns=self.meta['feature_columns']
        self.threshold=float(self.meta['threshold'])
        self.allowed_setups=self.meta['allowed_setups']

    def prepare_1h_live(self, df):
        d=df.copy(); c,h,l,v=d.close,d.high,d.low,d.volume
        d['ema20']=ema(c,20); d['ema50']=ema(c,50); d['ema200']=ema(c,200); d['ema800']=ema(c,800)
        d['atr14']=atr(h,l,c,14); d['atr_pct']=d.atr14/c
        d['adx14']=adx(h,l,c,14); d['adx_slope']=d.adx14-d.adx14.shift(12)
        d['rsi14']=rsi(c,14); d['rsi_slope']=d.rsi14-d.rsi14.shift(12)
        mid=c.rolling(20).mean(); std=c.rolling(20).std()
        d['bb_width']=(4*std/mid).replace([np.inf,-np.inf],np.nan)
        d['bb_pct']=d.bb_width.rolling(240).apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1],raw=False)
        d['atr_pct_rank']=d.atr_pct.rolling(240).apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1],raw=False)
        d['hi48']=h.rolling(48).max(); d['lo48']=l.rolling(48).min(); d['hi96']=h.rolling(96).max(); d['lo96']=l.rolling(96).min()
        d['range_pos96']=((c-d.lo96)/(d.hi96-d.lo96).replace(0,np.nan)).clip(0,1)
        d['ret24']=c.pct_change(24); d['ret72']=c.pct_change(72); d['ret168']=c.pct_change(168)
        d['ema50_slope']=d.ema50.pct_change(24); d['ema200_slope']=d.ema200.pct_change(48); d['ema800_slope']=d.ema800.pct_change(72)
        d['vol_z']=(v-v.rolling(72).mean())/v.rolling(72).std().replace(0,np.nan)
        d['body_pct']=(d.close-d.open).abs()/d.close
        d['red_big']=(d.close<d.open)&(d.body_pct>0.8*d.atr_pct)
        d['green_big']=(d.close>d.open)&(d.body_pct>0.8*d.atr_pct)
        d['trend_bias']=np.select([(c>d.ema200)&(d.ema200_slope>0),(c<d.ema200)&(d.ema200_slope<0)],[1,-1],default=0)
        d=classify(d)
        d=add_meta_features(d)
        return d.dropna().copy()

    def prepare_4h_live(self, df):
        # Similar to mtf_transition_strategy.prepare_4h but on supplied df.
        d=df.copy(); c,h,l=d.close,d.high,d.low
        d['ema50']=ema(c,50); d['ema200']=ema(c,200); d['ema400']=ema(c,400)
        d['atr14']=atr(h,l,c,14); d['atr_pct']=d.atr14/c; d['adx14']=adx(h,l,c,14); d['rsi14']=rsi(c,14)
        d['ema200_slope']=d.ema200.pct_change(12); d['ema400_slope']=d.ema400.pct_change(24)
        d['ret24h']=c.pct_change(6); d['ret72h']=c.pct_change(18); d['hi60']=h.rolling(60).max(); d['lo60']=l.rolling(60).min()
        d['range_pos']=((c-d.lo60)/(d.hi60-d.lo60).replace(0,np.nan)).clip(0,1)
        d['macro_state']='NEUTRAL'
        bull=(c>d.ema200)&(d.ema50>d.ema200)&(d.ema200_slope>0)&(d.adx14>18)
        bear=(c<d.ema200)&(d.ema50<d.ema200)&(d.ema200_slope<0)&(d.adx14>18)
        compression=(d.adx14<18)&(d.atr_pct<d.atr_pct.rolling(120).quantile(.35))
        distribution=(c>d.ema200)&(d.range_pos>.65)&(d.rsi14<d.rsi14.shift(6))&(d.ret24h<0)
        capitulation=(c<d.ema200)&((c<d.lo60.shift(1))|(d.ret24h<-2*d.atr_pct))&(d.adx14>18)
        recovery=(c<d.ema200)&(c>d.ema50)&(d.rsi14>45)&(d.ret24h>0)
        d.loc[compression,'macro_state']='COMPRESSION'; d.loc[bull,'macro_state']='EXPANSION_UP'; d.loc[bear,'macro_state']='EXPANSION_DOWN'; d.loc[distribution,'macro_state']='DISTRIBUTION'; d.loc[capitulation,'macro_state']='CAPITULATION'; d.loc[recovery,'macro_state']='RECOVERY'
        d['allow_short']=d.macro_state.isin(['EXPANSION_DOWN','DISTRIBUTION','CAPITULATION']) | ((c<d.ema200)&(d.ema200_slope<0))
        d['allow_long']=d.macro_state.isin(['EXPANSION_UP','RECOVERY']) | ((c>d.ema200)&(d.ema200_slope>0))
        return d.dropna().copy()

    def prepare_15m_live(self, df):
        d=df.copy(); c,h,l,v=d.close,d.high,d.low,d.volume
        d['ema20']=ema(c,20); d['ema50']=ema(c,50); d['ema200']=ema(c,200)
        d['atr14']=atr(h,l,c,14); d['rsi14']=rsi(c,14)
        d['lo32']=l.rolling(32).min(); d['hi32']=h.rolling(32).max(); d['lo96']=l.rolling(96).min(); d['hi96']=h.rolling(96).max()
        d['vol_z']=(v-v.rolling(96).mean())/v.rolling(96).std().replace(0,np.nan)
        rng=(d.high-d.low).replace(0,np.nan)
        d['bear_reject']=(d.close<d.open)&((d.high-d[['open','close']].max(axis=1))/rng>.25)
        d['bull_reject']=(d.close>d.open)&((d[['open','close']].min(axis=1)-d.low)/rng>.25)
        d['body_pct']=(d.close-d.open).abs()/d.close
        return d.dropna().copy()

    def encode_one(self, rec):
        df=pd.DataFrame([rec])
        X=pd.get_dummies(df[FEATURE_COLS], columns=CAT_COLS, dummy_na=False)
        return X.reindex(columns=self.columns, fill_value=0)

    def latest_signal(self, pair, df15, df1h, df4h, rr=1.8):
        h1=self.prepare_1h_live(df1h); m4=self.prepare_4h_live(df4h); d15=self.prepare_15m_live(df15)
        if len(h1)<120 or len(m4)<120 or len(d15)<120: return None
        # Use latest confirmed 1H candle and check if a 15m trigger occurred after it.
        i=len(h1)-1; t=h1.index[i]; row=h1.iloc[i]
        mac=macro_at(m4,t)
        if mac is None: return None
        for side,setup in setup_candidates_at(h1,i):
            if self.allowed_setups!='ALL' and setup not in self.allowed_setups: continue
            if side=='SHORT' and setup not in SHORT_SETUPS: continue
            if side=='LONG' and setup not in LONG_SETUPS: continue
            if side=='SHORT' and not bool(mac.allow_short): continue
            if side=='LONG' and not bool(mac.allow_long): continue
            if side=='LONG' and mac.macro_state not in ['RECOVERY','EXPANSION_UP']: continue
            trig_i,trig_type=trigger_15m(d15,t,side,setup)
            if trig_i is None: continue
            geom=geometry(d15,row,trig_i,side,rr=rr)
            if geom is None: continue
            entry_i,entry,sl,tp,risk_pct=geom
            rec={'pair':pair,'side':side,'setup':setup,'trigger_type':trig_type,'risk_pct':risk_pct,'tp_dist_pct':abs(tp-entry)/entry,'sl_dist_pct':abs(entry-sl)/entry}
            rec.update(get_4h_features(mac)); rec.update(get_1h_features(row)); rec.update(get_15m_features(d15,trig_i))
            if not all(np.isfinite(rec[c]) for c in NUM_COLS): continue
            prob=float(self.model.predict_proba(self.encode_one(rec))[:,1][0])
            if prob < self.threshold: continue
            return {'pair':pair,'side':side,'setup':setup,'probability':prob,'entry':float(entry),'sl':float(sl),'tp':float(tp),'risk_pct':float(risk_pct),'trigger_time':str(d15.index[trig_i]),'signal_time':str(t),'meta':{'m4_state':str(mac.macro_state),'h1_state':str(row.state),'trigger_type':trig_type}}
        return None
