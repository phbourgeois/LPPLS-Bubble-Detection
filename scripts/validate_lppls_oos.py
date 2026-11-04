"""Walk-forward LPPLS null calibration and real-market holdout, no remote calls.

Input: date-first weekly CSV. Every signal is computed from closes available at
that Friday; 8-week future price extrema are read ONLY in the evaluation layer.
No horizon or alpha tuning after observing the holdout.

Run: PYTHONPATH=src python scripts/validate_lppls_oos.py --input data/external/plotly_stockdata_weekly_2007_2016.csv
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from lppls_bubble.prices import weekly_prices
from lppls_bubble.statistical import StatisticalConfig, calibrated_window, decide_asof

SOURCE = ROOT/'data/external/plotly_stockdata_weekly_2007_2016.csv'
OUT = ROOT/'docs/statistical_validation'
HOLDOUT_START = '2013-01-04'
HOLDOUT_END = '2016-02-26'
FUTURE_WEEKS = 8
DRAWDOWN_THRESHOLD = -0.10
RALLY_THRESHOLD = 0.10
ASSETS = ('AAPL','IBM','MSFT','SBUX','GSPC')


def eligible_windows(weekly: pd.DataFrame, t: int, config: StatisticalConfig) -> dict[str,dict[int,np.ndarray]]:
    """No zero fills or compressed missing calendar weeks allowed."""
    found={}
    for asset in weekly.columns:
        for window in config.windows:
            if t+1<window:continue
            values=weekly[asset].iloc[t+1-window:t+1].to_numpy(float)
            if len(values)==window and np.isfinite(values).all() and (values>0).all():
                found.setdefault(asset,{})[window]=np.log(values)
    return found


def aggregate_alert(rows: list[dict], asset: str) -> tuple[str,float]:
    selected=[r for r in rows if r['asset']==asset and r['significant']]
    if not selected:
        return 'NONE',1.0
    labels=set(r['signal'] for r in selected)
    if len(labels)>1:
        return 'CONFLICT',min(r['q_bh'] for r in selected)
    return next(iter(labels)),min(r['q_bh'] for r in selected)


def decision_dates(weekly: pd.DataFrame, horizon: int=FUTURE_WEEKS) -> list[int]:
    start=int(weekly.index.searchsorted(pd.Timestamp(HOLDOUT_START)))
    end=int(weekly.index.searchsorted(pd.Timestamp(HOLDOUT_END),side='right'))
    return [t for t in range(start,end-horizon,horizon)]


def evaluate(weekly:pd.DataFrame,config:StatisticalConfig) -> tuple[pd.DataFrame,pd.DataFrame,dict]:
    """Forecasts frozen at t; outcome measured from t+1 through t+8."""
    weekly=weekly.loc[:HOLDOUT_END].copy()
    if not (weekly.index.is_monotonic_increasing and weekly.index.is_unique):
        raise ValueError('Weekly dates must be increasing and unique.')
    assert all(d.weekday()==4 for d in weekly.index), 'Week-end must be Friday.'
    assert all(a in weekly.columns for a in ASSETS)
    positions=decision_dates(weekly)
    all_fits=[];records=[]
    for t in positions:
        asof=weekly.index[t].date().isoformat()
        candidates=eligible_windows(weekly,t,config)
        results=decide_asof(candidates,config,asof)
        all_fits+=results
        for asset in ASSETS:
            if asset not in candidates:continue
            p0=float(weekly[asset].iloc[t])
            future=weekly[asset].iloc[t+1:t+1+FUTURE_WEEKS].to_numpy(dtype=float)
            if len(future)!=FUTURE_WEEKS or not np.isfinite(future).all():continue
            alert,q=aggregate_alert(results,asset)
            prior=weekly[asset].iloc[t-26]
            momentum=p0/prior-1 if t>=26 and np.isfinite(prior) and prior>0 else np.nan
            records.append(dict(asof=asof,asset=asset,is_benchmark=asset=='GSPC',
                                q_min=float(q),alert=alert,momentum_26=float(momentum),
                                momentum_up=bool(momentum>=.20),
                                momentum_down=bool(momentum<=-.20),
                                future_min_8w=float(np.min(future/p0-1)),
                                future_max_8w=float(np.max(future/p0-1)),
                                drawdown_10pct=bool(np.min(future/p0-1)<=DRAWDOWN_THRESHOLD),
                                rally_10pct=bool(np.max(future/p0-1)>=RALLY_THRESHOLD)))
    fits=pd.DataFrame(all_fits)
    outcomes=pd.DataFrame(records)
    return fits,outcomes,summary_metrics(fits,outcomes,config,positions)


def _precision_recall(flag: pd.Series,event:pd.Series) -> dict:
    f=flag.astype(bool);e=event.astype(bool)
    tp=int((f&e).sum());alerts=int(f.sum());positives=int(e.sum());n=len(f)
    return dict(n=n,alerts=alerts,events=positives,true_positive=tp,
                precision=(tp/alerts if alerts else None),
                recall=(tp/positives if positives else None),
                event_base_rate=(positives/n if n else None),
                lift=((tp/alerts)/(positives/n) if alerts and positives else None))


def summary_metrics(fits:pd.DataFrame,outcomes:pd.DataFrame,config:StatisticalConfig,
                    positions:list[int]) -> dict:
    eq=outcomes.loc[~outcomes.is_benchmark]
    index=outcomes.loc[outcomes.is_benchmark]
    def panel(data):
        return dict(up_lppls=_precision_recall(data.alert=='UP',data.drawdown_10pct),
                    up_momentum=_precision_recall(data.momentum_up,data.drawdown_10pct),
                    down_lppls=_precision_recall(data.alert=='DOWN',data.rally_10pct),
                    down_momentum=_precision_recall(data.momentum_down,data.rally_10pct))
    return dict(config=asdict(config),holdout_start=HOLDOUT_START,
                holdout_end=HOLDOUT_END,source_last_week=outcomes['asof'].max(),
                decision_count=len(positions),panel_rows=len(outcomes),
                tested_fits=len(fits), significant_fits=int(fits.significant.sum()),
                equities=panel(eq),index_GSPC=panel(index),
                no_holdout_parameter_optimization=True,
                outcome='10% future close-to-extreme move over 8 complete weeks; no portfolio returns',
                caution='BH within as-of date only; serial/cross-asset dependence, adjusted-price provenance and survivorship unresolved')


def negative_positive_controls(config:StatisticalConfig, n_null:int=100, n_lppls:int=80) -> tuple[pd.DataFrame,dict]:
    """Synthetic size and toy-model power measured separately; no tuning."""
    rows=[];rng=np.random.default_rng(731221)
    n=104
    for i in range(n_null+n_lppls):
        if i<n_null:
            # Stationary Gaussian returns, no log periodic component.
            logy=4+np.cumsum(rng.normal(.0005,.018,n))
            kind='iid_gaussian_null'
        else:
            t=np.arange(n);tau=n-1+26-t
            # Exact grid candidate, perturbed with independent observational noise.
            logy=5-.08*tau**.5+.025*tau**.5*np.cos(9.5*np.log(tau)+.7)+rng.normal(0,.015,n)
            kind='planted_lppls'
        fit=calibrated_window(logy,StatisticalConfig(windows=(104,),bootstrap_draws=config.bootstrap_draws,
                  block_weeks=config.block_weeks,alpha=config.alpha,min_cycles=config.min_cycles,
                  seed=config.seed),f'scenario-{i}',f'SIM-{i}')
        rows.append(dict(kind=kind,series=i,p_joint=fit['p_joint'],gain=fit['oscillation_gain'],
                         signal=fit['signal'],p_below_alpha=fit['p_joint']<=config.alpha,
                         cycles_ok=fit['eligible'],pass_both=(fit['p_joint']<=config.alpha and fit['eligible'])))
    df=pd.DataFrame(rows)
    stats={kind:dict(n=len(g),passed=int(g.pass_both.sum()),rate=float(g.pass_both.mean()))
           for kind,g in df.groupby('kind')}
    return df,stats


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',type=Path,default=SOURCE)
    parser.add_argument('--output',type=Path,default=OUT)
    parser.add_argument('--draws',type=int,default=199)
    parser.add_argument('--only-oos',action='store_true')
    args=parser.parse_args()
    config=StatisticalConfig(bootstrap_draws=args.draws)
    config.validate()
    prices=weekly_prices(args.input)
    # Reject a source that stops short of the preregistered holdout.
    if prices.index.min()>pd.Timestamp('2007-01-05') or prices.index.max()<pd.Timestamp('2016-02-26'):
        raise ValueError('Le jeu de données ne couvre pas le protocole réel préétabli.')
    fits,records,report=evaluate(prices,config)
    args.output.mkdir(parents=True,exist_ok=True)
    fits.to_csv(args.output/'oos_lppls_fits.csv',index=False)
    records.to_csv(args.output/'oos_events.csv',index=False)
    if not args.only_oos:
        controls,stats=negative_positive_controls(config)
        controls.to_csv(args.output/'null_and_power_controls.csv',index=False)
        report['controls']=stats
    report['source']=str(args.input)
    (args.output/'summary.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
