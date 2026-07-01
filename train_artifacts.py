"""Train and save ANN MTF V3 artifacts for the paper bot."""
from pathlib import Path
import json
import sys
import joblib
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Reuse V3 functions. The bot will only need the fitted model, columns, threshold, and setup whitelist.
from ann_mtf_transition_v3 import (
    generate_pair_dataset, make_splits, encode_fit, build_model, select_stable, CORE, TRANSFER
)

ART = Path(__file__).resolve().parent / 'artifacts'
ART.mkdir(exist_ok=True)


def main():
    core_parts=[]
    for sym in CORE:
        core_parts.append(generate_pair_dataset(sym))
    core=pd.concat(core_parts,ignore_index=True)
    core,bounds=make_splits(core)
    train=core[core.split=='train1'].copy()
    Xtr=encode_fit(train)
    cols=list(Xtr.columns)
    y=train.label.astype(int).values

    # Use the selected V3 architecture from research result.
    cfg={'hidden':(16,8),'alpha':0.05}
    model=build_model(cfg['hidden'],cfg['alpha'],seed=303)
    model.fit(Xtr,y)
    best,diag=select_stable(model,Xtr.columns,core,[0.50,0.54,0.58,0.62,0.66,0.70,0.74])

    # Research selected threshold 0.54 and stable setup list. Keep dynamic result if stable; otherwise fallback.
    if not bool(best.get('stable', False)):
        best={'filter':'STABLE_GOOD_SETUPS','setups':'capitulation_continuation,capitulation_recovery,distribution_break,recovery_continuation,compression_up_break,expansion_pullback_short','threshold':0.54}

    meta={
        'model_version':'ann_mtf_v3',
        'core_pairs':CORE,
        'transfer_pairs':TRANSFER,
        'dropped_pairs':['BNB','HYPE'],
        'config':{'hidden':[16,8],'alpha':0.05},
        'threshold':float(best['threshold']),
        'setup_filter':best['filter'],
        'allowed_setups':best['setups'].split(',') if best['setups']!='ALL' else 'ALL',
        'feature_columns':cols,
        'split_bounds':{k:str(v) for k,v in bounds.items()},
    }
    joblib.dump(model, ART/'ann_mtf_v3_model.joblib')
    (ART/'ann_mtf_v3_meta.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
    diag.to_csv(ART/'training_selection_diag.csv',index=False)
    print('saved artifacts', ART)
    print(json.dumps(meta,indent=2))

if __name__=='__main__': main()
