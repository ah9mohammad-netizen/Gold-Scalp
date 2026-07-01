"""
ANN MTF Transition Framework V3
───────────────────────────────
4H macro context + 1H structure setup + 15m execution trigger.

Core training universe after user decision:
  BTC, ETH, SOL, AVAX
Transfer / young-asset test:
  ENA
Dropped:
  BNB, HYPE

Method:
  1) Generate candidate trades only when:
       4H macro permits direction
       1H structure emits transition setup
       15m confirms execution
  2) Label each candidate by whether TP is reached before SL over next 96h.
  3) Train a global ANN across core pairs.
  4) Use two rolling validation windows for threshold/setup stability.
  5) Final test remains untouched.
  6) Apply selected global model to ENA as transfer/out-of-sample young asset.

Research only. Not live execution.
"""
from __future__ import annotations

from pathlib import Path
import math
import warnings
import numpy as np
import pandas as pd
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import roc_auc_score, brier_score_loss

from market_structure_strategy import prepare as prepare_1h, df_to_md
from ann_transition_framework import setup_candidates_at, add_meta_features
from mtf_transition_strategy import prepare_4h, prepare_15m, macro_at, trigger_15m

warnings.filterwarnings("ignore")
OUT = Path('results'); OUT.mkdir(exist_ok=True)
INIT = 700.0
FEE = 0.0005
SLIP = 0.0010

CORE = ['BTC','ETH','SOL','AVAX']
TRANSFER = ['ENA']
SHORT_SETUPS = {'capitulation_continuation','distribution_break','expansion_pullback_short','compression_down_break'}
LONG_SETUPS = {'recovery_continuation','capitulation_recovery','compression_up_break'}

NUM_COLS = [
    # 4H macro
    'm4_adx14','m4_rsi14','m4_atr_pct','m4_ema200_slope','m4_ema400_slope','m4_range_pos','m4_ret24h','m4_ret72h','m4_dist_ema200','m4_dist_ema400','m4_allow_short','m4_allow_long',
    # 1H setup context
    'h1_atr_pct','h1_adx14','h1_adx_slope','h1_rsi14','h1_rsi_slope','h1_range_pos96','h1_ret24','h1_ret72','h1_ret168','h1_ema50_slope','h1_ema200_slope','h1_ema800_slope','h1_vol_z','h1_dist_ema20','h1_dist_ema50','h1_dist_ema200','h1_dist_ema800','h1_state_age',
    # 15m execution context
    'x15_rsi14','x15_atr_pct','x15_vol_z','x15_dist_ema20','x15_dist_ema50','x15_dist_ema200','x15_range_pos96','x15_body_pct','x15_break_down','x15_break_up','x15_bear_reject','x15_bull_reject',
    # trade geometry
    'risk_pct','tp_dist_pct','sl_dist_pct'
]
CAT_COLS = ['pair','side','setup','h1_state','m4_state','trigger_type']
FEATURE_COLS = NUM_COLS + CAT_COLS


def enrich_1h(h1: pd.DataFrame) -> pd.DataFrame:
    h1 = add_meta_features(h1)
    # add_meta_features creates dist_* and state_age using V1/V2 feature names
    return h1


def get_4h_features(mac):
    return {
        'm4_adx14': float(mac.adx14), 'm4_rsi14': float(mac.rsi14), 'm4_atr_pct': float(mac.atr_pct),
        'm4_ema200_slope': float(mac.ema200_slope), 'm4_ema400_slope': float(mac.ema400_slope),
        'm4_range_pos': float(mac.range_pos), 'm4_ret24h': float(mac.ret24h), 'm4_ret72h': float(mac.ret72h),
        'm4_dist_ema200': float(mac.close/mac.ema200 - 1), 'm4_dist_ema400': float(mac.close/mac.ema400 - 1),
        'm4_allow_short': float(bool(mac.allow_short)), 'm4_allow_long': float(bool(mac.allow_long)),
        'm4_state': str(mac.macro_state)
    }


def get_1h_features(row):
    return {
        'h1_atr_pct': float(row.atr_pct), 'h1_adx14': float(row.adx14), 'h1_adx_slope': float(row.adx_slope),
        'h1_rsi14': float(row.rsi14), 'h1_rsi_slope': float(row.rsi_slope), 'h1_range_pos96': float(row.range_pos96),
        'h1_ret24': float(row.ret24), 'h1_ret72': float(row.ret72), 'h1_ret168': float(row.ret168),
        'h1_ema50_slope': float(row.ema50_slope), 'h1_ema200_slope': float(row.ema200_slope), 'h1_ema800_slope': float(row.ema800_slope),
        'h1_vol_z': float(row.vol_z), 'h1_dist_ema20': float(row.dist_ema20), 'h1_dist_ema50': float(row.dist_ema50),
        'h1_dist_ema200': float(row.dist_ema200), 'h1_dist_ema800': float(row.dist_ema800), 'h1_state_age': float(row.state_age),
        'h1_state': str(row.state)
    }


def get_15m_features(d15, k):
    r = d15.iloc[k]
    rng_pos = (r.close - r.lo96) / (r.hi96 - r.lo96) if (r.hi96-r.lo96) else np.nan
    return {
        'x15_rsi14': float(r.rsi14), 'x15_atr_pct': float(r.atr14/r.close), 'x15_vol_z': float(r.vol_z),
        'x15_dist_ema20': float(r.close/r.ema20 - 1), 'x15_dist_ema50': float(r.close/r.ema50 - 1), 'x15_dist_ema200': float(r.close/r.ema200 - 1),
        'x15_range_pos96': float(np.clip(rng_pos, 0, 1)), 'x15_body_pct': float(r.body_pct),
        'x15_break_down': float(r.close < d15.lo32.iloc[k-1]), 'x15_break_up': float(r.close > d15.hi32.iloc[k-1]),
        'x15_bear_reject': float(bool(r.bear_reject)), 'x15_bull_reject': float(bool(r.bull_reject)),
    }


def geometry(d15, h1_row, trig_i, side, rr=1.8):
    entry_i = trig_i + 1
    if entry_i >= len(d15): return None
    raw = float(d15.open.iloc[entry_i])
    entry = raw*(1+SLIP) if side=='LONG' else raw*(1-SLIP)
    a = float(h1_row.atr14)
    if not math.isfinite(a) or a <= 0: return None
    if side == 'LONG':
        sl = min(float(d15.lo96.iloc[trig_i]), entry - 0.9*a)
        sl = max(sl, entry - 2.2*a)
        risk = entry - sl; tp = entry + rr*risk
    else:
        sl = max(float(d15.hi96.iloc[trig_i]), entry + 0.9*a)
        sl = min(sl, entry + 2.2*a)
        risk = sl - entry; tp = entry - rr*risk
    if risk <= 0: return None
    risk_pct = risk/entry
    if risk_pct < 0.0025 or risk_pct > 0.10: return None
    return entry_i, entry, sl, tp, risk_pct


def label_trade(d15, m4, entry_i, side, entry, sl, tp, horizon_bars=96*4):
    max_j = min(len(d15)-1, entry_i+horizon_bars)
    exit_raw = float(d15.close.iloc[max_j]); exit_i = max_j; reason = 'TIME'
    for j in range(entry_i, max_j+1):
        r = d15.iloc[j]
        macj = macro_at(m4, d15.index[j])
        if side == 'LONG':
            if r.low <= sl: exit_raw=sl; exit_i=j; reason='SL'; break
            if r.high >= tp: exit_raw=tp; exit_i=j; reason='TP'; break
            if macj is not None and macj.macro_state in ['DISTRIBUTION','CAPITULATION','EXPANSION_DOWN'] and r.close < r.ema50:
                exit_raw=float(r.close); exit_i=j; reason='MACRO_FLIP'; break
        else:
            if r.high >= sl: exit_raw=sl; exit_i=j; reason='SL'; break
            if r.low <= tp: exit_raw=tp; exit_i=j; reason='TP'; break
            if macj is not None and macj.macro_state in ['RECOVERY','EXPANSION_UP'] and r.close > r.ema50:
                exit_raw=float(r.close); exit_i=j; reason='MACRO_FLIP'; break
    ex = exit_raw*(1-SLIP) if side=='LONG' else exit_raw*(1+SLIP)
    gross = ex/entry - 1 if side=='LONG' else entry/ex - 1
    net = gross - 2*FEE
    return int(net > 0), 100*net, exit_i, reason


def generate_pair_dataset(sym: str) -> pd.DataFrame:
    h1 = enrich_1h(prepare_1h(sym)); m4 = prepare_4h(sym); d15 = prepare_15m(sym)
    if h1.empty or m4.empty or d15.empty:
        return pd.DataFrame()
    # Full MTF dataset only where 15m exists.
    h1 = h1[(h1.index >= d15.index[0]) & (h1.index <= d15.index[-1])].copy()
    rows=[]; last_trigger_by_setup={}
    for i in range(100, len(h1)-2):
        t = h1.index[i]
        row = h1.iloc[i]
        mac = macro_at(m4, t)
        if mac is None: continue
        candidates = setup_candidates_at(h1, i)
        if not candidates: continue
        for side, setup in candidates:
            if side == 'SHORT' and setup not in SHORT_SETUPS: continue
            if side == 'LONG' and setup not in LONG_SETUPS: continue
            if side == 'SHORT' and not bool(mac.allow_short): continue
            if side == 'LONG' and not bool(mac.allow_long): continue
            # Learned bias from V1/V2: generic longs are dangerous unless macro is truly supportive.
            if side == 'LONG' and mac.macro_state not in ['RECOVERY','EXPANSION_UP']:
                continue
            trig_i, trig_type = trigger_15m(d15, t, side, setup)
            if trig_i is None: continue
            # Avoid generating duplicate same-setup triggers too close together.
            key=(side,setup)
            if key in last_trigger_by_setup and trig_i - last_trigger_by_setup[key] < 8:
                continue
            geom = geometry(d15, row, trig_i, side)
            if geom is None: continue
            entry_i, entry, sl, tp, risk_pct = geom
            label, label_ret, exit_i, exit_reason = label_trade(d15, m4, entry_i, side, entry, sl, tp)
            rec = {'pair':sym, 'signal_time':t, 'trigger_time':d15.index[trig_i], 'entry_time':d15.index[entry_i],
                   'side':side, 'setup':setup, 'trigger_type':trig_type, 'label':label, 'label_ret':label_ret,
                   'entry_i':entry_i, 'exit_i':exit_i, 'exit_reason':exit_reason, 'entry':entry, 'sl':sl, 'tp':tp,
                   'risk_pct':risk_pct, 'tp_dist_pct':abs(tp-entry)/entry, 'sl_dist_pct':abs(entry-sl)/entry}
            rec.update(get_4h_features(mac)); rec.update(get_1h_features(row)); rec.update(get_15m_features(d15, trig_i))
            if all(np.isfinite(rec[c]) for c in NUM_COLS):
                rows.append(rec); last_trigger_by_setup[key]=trig_i
    df=pd.DataFrame(rows)
    print(sym, 'dataset', len(df), 'pos', round(100*df.label.mean(),1) if len(df) else None, 'range', df.entry_time.min() if len(df) else None, df.entry_time.max() if len(df) else None)
    return df


def make_splits(df: pd.DataFrame):
    # Global time boundaries from core dataset.
    times = pd.to_datetime(df.entry_time).sort_values().reset_index(drop=True)
    b1 = times.iloc[int(len(times)*0.45)]
    b2 = times.iloc[int(len(times)*0.60)]
    b3 = times.iloc[int(len(times)*0.75)]
    def split_row(t):
        if t < b1: return 'train1'
        if t < b2: return 'val1'
        if t < b3: return 'val2'
        return 'test'
    out=df.copy(); out['split']=pd.to_datetime(out.entry_time).apply(split_row)
    return out, {'train1_end':b1, 'val1_end':b2, 'val2_end':b3}


def encode_fit(train):
    return pd.get_dummies(train[FEATURE_COLS], columns=CAT_COLS, dummy_na=False)

def encode_like(df, cols):
    X=pd.get_dummies(df[FEATURE_COLS], columns=CAT_COLS, dummy_na=False)
    return X.reindex(columns=cols, fill_value=0)


def build_model(hidden=(16,), alpha=0.03, seed=1):
    return Pipeline([
        ('scaler', StandardScaler()),
        ('mlp', MLPClassifier(hidden_layer_sizes=hidden, alpha=alpha, activation='relu', solver='adam',
                              learning_rate_init=0.0007, max_iter=700, early_stopping=True,
                              validation_fraction=0.18, n_iter_no_change=40, random_state=seed))
    ])


def simulate(df, probs, threshold, allowed_setups=None):
    if len(df)==0: return [], summarize([])
    sim=df.copy(); sim['prob']=probs
    if allowed_setups is not None:
        sim=sim[sim.setup.isin(allowed_setups)]
    sim=sim[sim.prob>=threshold].sort_values('entry_time')
    equity=INIT; trades=[]; last_exit_by_pair={}
    for _,r in sim.iterrows():
        last=last_exit_by_pair.get(r.pair, pd.Timestamp.min.tz_localize('UTC'))
        if pd.Timestamp(r.entry_time) <= last: continue
        equity *= 1 + float(r.label_ret)/100
        last_exit_time = pd.Timestamp(r.entry_time) + pd.Timedelta(minutes=15*int(r.exit_i-r.entry_i+1))
        last_exit_by_pair[r.pair]=last_exit_time
        trades.append({'pair':r.pair,'time':r.entry_time,'side':r.side,'setup':r.setup,'m4_state':r.m4_state,'h1_state':r.h1_state,'prob':round(float(r.prob),4),'label':int(r.label),'net_pct':float(r.label_ret),'exit_reason':r.exit_reason,'bars':int(r.exit_i-r.entry_i+1),'equity':equity})
    return trades, summarize(trades)


def summarize(trades):
    if not trades:
        return dict(trades=0,win_rate=0,return_pct=0,final=INIT,profit_factor=0,expectancy=0,max_dd=0,sharpe=0,avg_prob=0,avg_bars=0)
    r=np.array([t['net_pct']/100 for t in trades]); wins=r[r>0]; losses=r[r<=0]
    eq=np.array([INIT]+[t['equity'] for t in trades]); peak=np.maximum.accumulate(eq); dd=(eq/peak-1)*100
    return dict(trades=len(trades),win_rate=round(100*len(wins)/len(trades),1),return_pct=round(100*(eq[-1]/INIT-1),1),final=round(eq[-1],2),profit_factor=round(wins.sum()/abs(losses.sum()),2) if len(losses) and abs(losses.sum())>0 else np.inf,expectancy=round(100*r.mean(),3),max_dd=round(abs(dd.min()),1),sharpe=round(r.mean()/r.std(ddof=1)*math.sqrt(len(r)),2) if len(r)>1 and r.std(ddof=1)>0 else 0,avg_prob=round(np.mean([t['prob'] for t in trades]),3),avg_bars=round(np.mean([t['bars'] for t in trades]),1))


def obj(st):
    if st['trades'] < 8: return -1e9
    if st['profit_factor'] < 1.15: return -1e9
    return st['return_pct'] + 0.45*st['win_rate'] + 4*min(st['profit_factor'],4) - 0.8*st['max_dd'] + min(st['trades'],60)*0.25


def select_stable(model, cols, data, thresholds):
    # Select threshold + optional setup filter that survives both val1 and val2.
    val1=data[data.split=='val1'].copy(); val2=data[data.split=='val2'].copy()
    p1=model.predict_proba(encode_like(val1,cols))[:,1]; p2=model.predict_proba(encode_like(val2,cols))[:,1]
    setup_perf=[]
    for setup,g in val1.groupby('setup'):
        if len(g)>=4 and g.label_ret.mean()>0: setup_perf.append(setup)
    for setup,g in val2.groupby('setup'):
        if len(g)>=4 and g.label_ret.mean()>0 and setup not in setup_perf: setup_perf.append(setup)
    candidates={'ALL':None}
    if setup_perf: candidates['STABLE_GOOD_SETUPS']=setup_perf
    best=None; rows=[]
    for filt,setups in candidates.items():
        for th in thresholds:
            tr1,st1=simulate(val1,p1,th,setups); tr2,st2=simulate(val2,p2,th,setups)
            stable=(st1['trades']>=5 and st2['trades']>=5 and st1['return_pct']>0 and st2['return_pct']>0 and st1['profit_factor']>1.1 and st2['profit_factor']>1.1)
            sc=(obj(st1)+obj(st2))/2 if stable else -1e9
            row={'filter':filt,'setups':','.join(setups) if setups else 'ALL','threshold':th,'stable':stable,'score':sc,**{f'val1_{k}':v for k,v in st1.items()},**{f'val2_{k}':v for k,v in st2.items()}}
            rows.append(row)
            if best is None or sc>best['score']: best=row
    return best, pd.DataFrame(rows)


def main():
    core_parts=[]; transfer_parts=[]
    for sym in CORE:
        core_parts.append(generate_pair_dataset(sym))
    core=pd.concat(core_parts,ignore_index=True)
    core, bounds=make_splits(core)
    for sym in TRANSFER:
        df=generate_pair_dataset(sym)
        if len(df):
            # Apply same global boundaries where possible; ENA likely mostly val2/test by calendar.
            df['split']='transfer'
            transfer_parts.append(df)
    transfer=pd.concat(transfer_parts,ignore_index=True) if transfer_parts else pd.DataFrame()
    core.to_csv(OUT/'ann_mtf_v3_dataset_core.csv',index=False)
    transfer.to_csv(OUT/'ann_mtf_v3_dataset_transfer.csv',index=False)

    train=core[core.split=='train1'].copy()
    Xtr=encode_fit(train); cols=Xtr.columns; y=train.label.astype(int).values
    configs=[{'hidden':(12,), 'alpha':0.03},{'hidden':(16,), 'alpha':0.03},{'hidden':(24,), 'alpha':0.05},{'hidden':(16,8), 'alpha':0.05}]
    thresholds=[0.50,0.54,0.58,0.62,0.66,0.70,0.74]
    model_rows=[]; all_sel=[]; best_global=None
    for mi,cfg in enumerate(configs):
        print('train model',cfg)
        model=build_model(cfg['hidden'],cfg['alpha'],seed=300+mi); model.fit(Xtr,y)
        best,diag=select_stable(model,cols,core,thresholds)
        diag['model_id']=mi; diag['hidden']=str(cfg['hidden']); diag['alpha']=cfg['alpha']; all_sel.append(diag)
        row={'model_id':mi,'hidden':str(cfg['hidden']),'alpha':cfg['alpha'],**best}
        model_rows.append(row)
        if best_global is None or best['score']>best_global['score']:
            best_global={'model':model,'cfg':cfg,'model_id':mi,'selection':best,'score':best['score']}
    model_df=pd.DataFrame(model_rows).sort_values('score',ascending=False)
    sel_diag=pd.concat(all_sel,ignore_index=True)
    model_df.to_csv(OUT/'ann_mtf_v3_model_selection.csv',index=False)
    sel_diag.to_csv(OUT/'ann_mtf_v3_selection_diagnostics.csv',index=False)

    # Final evaluation
    model=best_global['model']; sel=best_global['selection']; th=float(sel['threshold']); setups=None if sel['setups']=='ALL' else sel['setups'].split(',')
    rows=[]; trades=[]
    for split in ['train1','val1','val2','test']:
        df=core[core.split==split].copy(); probs=model.predict_proba(encode_like(df,cols))[:,1]
        tr,st=simulate(df,probs,th,setups); rows.append({'universe':'CORE','split':split,**st})
        for t in tr: trades.append({'universe':'CORE','split':split,**t})
    if len(transfer):
        probs=model.predict_proba(encode_like(transfer,cols))[:,1]
        tr,st=simulate(transfer,probs,th,setups); rows.append({'universe':'TRANSFER_ENA','split':'transfer',**st})
        for t in tr: trades.append({'universe':'TRANSFER_ENA','split':'transfer',**t})
    res=pd.DataFrame(rows); trd=pd.DataFrame(trades)
    res.to_csv(OUT/'ann_mtf_v3_results.csv',index=False); trd.to_csv(OUT/'ann_mtf_v3_trades.csv',index=False)
    if len(trd):
        setup=trd.groupby(['universe','split','pair','setup','side']).agg(trades=('net_pct','size'),wr=('net_pct',lambda x:round(100*(x>0).mean(),1)),ret_sum=('net_pct',lambda x:round(x.sum(),1)),avg=('net_pct',lambda x:round(x.mean(),2)),avg_prob=('prob',lambda x:round(x.mean(),3))).reset_index().sort_values(['universe','split','ret_sum'],ascending=[True,True,False])
        setup.to_csv(OUT/'ann_mtf_v3_setup_breakdown.csv',index=False)
    else: setup=pd.DataFrame()

    profile=core.groupby(['pair','split']).agg(candidates=('label','size'),pos_rate=('label',lambda x:round(100*x.mean(),1)),avg_ret=('label_ret',lambda x:round(x.mean(),2))).reset_index()
    profile.to_csv(OUT/'ann_mtf_v3_profile.csv',index=False)
    rep=['# ANN MTF Transition Framework V3','','Core training universe: BTC, ETH, SOL, AVAX. ENA is transfer-only because history is too short.','','## Split boundaries','',df_to_md(pd.DataFrame([bounds])),'','## Candidate profile','',df_to_md(profile),'','## Model / threshold stability selection','',df_to_md(model_df),'','## Selected model','',f"Model: {best_global['cfg']}, threshold={th}, setup_filter={sel['filter']}, setups={sel['setups']}",'','## Results','',df_to_md(res)]
    if len(setup): rep += ['','## Setup breakdown','',df_to_md(setup.head(120))]
    rep += ['','## Interpretation rule','','A model is only acceptable if val1, val2, and final test are all positive with acceptable drawdown and enough trades. ENA is not used for training and should be treated as transfer/paper-only.']
    (OUT/'ann_mtf_v3_report.md').write_text('\n'.join(rep),encoding='utf-8')
    print('\nSELECTED',best_global['cfg'],sel)
    print(res.to_string(index=False))
    print('Saved results/ann_mtf_v3_report.md')

if __name__=='__main__': main()
