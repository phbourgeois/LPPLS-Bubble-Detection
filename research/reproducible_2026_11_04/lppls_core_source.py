"""Reproducible exploratory LPPLS pipeline and weekly backtest.

Not investment advice. The grid-based estimator is heuristic rather than a statistically
certified LPPLS bubble detector. Inputs are closing prices, assumed unadjusted unless
provided otherwise. Missing returns are not silently replaced by investment returns.
"""
from __future__ import annotations
from pathlib import Path
import json
import numpy as np
import pandas as pd

WINDOWS = (13, 26, 39, 52, 65, 78, 104)
DETAIL_COLS = ['asset','window_weeks','start_date','end_date','n_obs','A','B','C','m','omega','phi','tc_weeks_ahead','r2','rmse','is_valid','signal']


def load_prices(path: str | Path) -> pd.DataFrame:
    """Read plain or Datastream-style CSV, comma decimals, semicolon or comma separator.

    For Datastream CSV the first 3 metadata rows precede the Name/date header.
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f'Fichier absent: {path}. Déposez Miscellanous.csv à côté du notebook.')
    best = None
    for skip in (0, 3):
        for sep in (';', ',','\t'):
            try:
                raw = pd.read_csv(path, sep=sep, skiprows=skip, dtype=str, encoding='utf-8-sig', low_memory=False)
            except (ValueError, UnicodeError, pd.errors.ParserError):
                continue
            if raw.shape[1] < 2:
                continue
            dates = pd.to_datetime(raw.iloc[:, 0], dayfirst=True, errors='coerce')
            rate = float(dates.notna().mean())
            if best is None or rate > best[0]:
                best = (rate, raw, dates)
    if best is None or best[0] < 0.5:
        raise ValueError('CSV invalide : première colonne attendue = dates, autres colonnes = cours.')
    _, raw, dates = best
    data = pd.DataFrame(index=pd.DatetimeIndex(dates, name='date'))
    for i in range(1, raw.shape[1]):
        name = str(raw.columns[i]).strip()
        if not name or name.lower().startswith('unnamed'):
            continue
        s = raw.iloc[:,i].astype('string').str.strip()
        s = s.str.replace(' ', '', regex=False).str.replace('\u00a0','',regex=False)
        # European decimal notation; otherwise ordinary numeric notation.
        comma_decimal = s.str.contains(',',regex=False).sum() > s.str.contains('\\.',regex=True).sum()
        if comma_decimal:
            s = s.str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
        vals = pd.to_numeric(s, errors='coerce')
        data[name] = vals.to_numpy()
    data = data.loc[data.index.notna()].sort_index()
    data = data[~data.index.duplicated(keep='last')]
    data = data.loc[:,~data.columns.duplicated(keep='first')]
    data = data.where(data > 0)
    data = data.dropna(axis=1,how='all').dropna(axis=0,how='all')
    if data.empty:
        raise ValueError('Aucun cours numérique strictement positif disponible.')
    return data


def to_weekly(daily: pd.DataFrame) -> pd.DataFrame:
    """Last non-missing observed price in each Friday-ended week."""
    return daily.resample('W-FRI').last().dropna(how='all')


def fit_lppls(log_prices, grid='full') -> dict:
    """Grid-search m, omega, tc, OLS for A,B,C1,C2; exploratory only."""
    y = np.asarray(log_prices, dtype=float)
    n = len(y)
    if n < 12 or not np.isfinite(y).all() or np.std(y) == 0:
        return {'success':False,'n':n}
    t = np.arange(n,dtype=float)
    if grid == 'tiny':
        m_grid, omega_grid, ahead_grid = (0.2,0.5,0.8), (7.,9.5,12.), (1.,0.25*n,0.75*n)
    else:
        m_grid, omega_grid, ahead_grid = np.linspace(.1,.9,7),np.linspace(6.,13.,7),np.linspace(1.,n,7)
    best=None
    sst = float(np.sum((y-y.mean())**2))
    for m in m_grid:
        for omega in omega_grid:
            for ahead in ahead_grid:
                tc = n-1+float(ahead)
                tau=tc-t
                power=tau**m
                angle=omega*np.log(tau)
                X=np.column_stack((np.ones(n),power,power*np.cos(angle),power*np.sin(angle)))
                try:
                    beta,_,rank,_ = np.linalg.lstsq(X,y,rcond=None)
                except np.linalg.LinAlgError:
                    continue
                if rank < 4:
                    continue
                residual=y-X@beta
                sse=float(residual@residual)
                if best is None or sse < best['sse']:
                    A,B,C1,C2=map(float,beta)
                    best={'success':True,'n':n,'A':A,'B':B,'C':float(np.hypot(C1,C2)),
                          'm':float(m),'omega':float(omega),'phi':float(np.arctan2(-C2,C1)),
                          'tc':tc,'tc_weeks_ahead':float(ahead),'r2':float(1-sse/sst),
                          'rmse':float(np.sqrt(sse/n)),'sse':sse}
    return best or {'success':False,'n':n}


def classify_fit(fit):
    if not fit.get('success',False):
        return False,'NONE'
    valid= (0.1 <= fit['m'] <= .9 and 6. <= fit['omega'] <= 13.
            and 0 < fit['tc_weeks_ahead'] <= 1.5*fit['n'] and fit['r2'] >= .2)
    if not valid or not np.isfinite(fit['B']):
        return False,'NONE'
    return True, 'UP' if fit['B'] < 0 else 'DOWN'


def calculate_details(weekly, windows=WINDOWS, grid='full'):
    rows=[]
    for asset in weekly.columns:
        s=weekly[asset].dropna()
        # Preserve chronological windows without closing gaps artificially.
        for window_size in windows:
            sample=weekly[asset].iloc[-window_size:]
            if len(sample) != window_size or sample.isna().any():
                continue
            logp=np.log(sample.to_numpy(dtype=float))
            fit=fit_lppls(logp,grid=grid)
            valid,signal=classify_fit(fit)
            rows.append({'asset':asset,'window_weeks':window_size,
                         'start_date':sample.index[0].date().isoformat(),
                         'end_date':sample.index[-1].date().isoformat(),
                         'n_obs':len(sample),
                         **{k:fit.get(k,np.nan) for k in ('A','B','C','m','omega','phi','tc_weeks_ahead','r2','rmse')},
                         'is_valid':bool(valid),'signal':signal})
    return pd.DataFrame(rows,columns=DETAIL_COLS)


def summarize(details):
    if details.empty:
        return pd.DataFrame(columns=['asset','valid_frac','tc_weeks_ahead_median'])
    assets=details['asset'].drop_duplicates().tolist()
    wide=pd.DataFrame({'asset':assets}).set_index('asset')
    for metric in ('signal','is_valid','tc_weeks_ahead','r2'):
        pivot=details.pivot(index='asset',columns='window_weeks',values=metric)
        pivot.columns=[f'{metric}_{int(w)}w' for w in pivot.columns]
        wide=wide.join(pivot,how='left')
    valid_cols=[c for c in wide if c.startswith('is_valid_')]
    wide['valid_frac']=wide[valid_cols].fillna(False).astype(float).mean(axis=1)
    medians=[]
    for _,row in wide.iterrows():
        vals=[]
        for w in WINDOWS:
            if row.get(f'is_valid_{w}w',False) is True or row.get(f'is_valid_{w}w',False)==True:
                v=row.get(f'tc_weeks_ahead_{w}w',np.nan)
                if pd.notna(v): vals.append(float(v))
        medians.append(float(np.median(vals)) if vals else np.nan)
    wide['tc_weeks_ahead_median']=medians
    return wide.reset_index()


def bubble_classification(wide):
    if wide.empty:
        return pd.DataFrame(columns=['asset','bubble_short_term','bubble_long_term','bubble_multiscale_state','valid_frac','tc_weeks_ahead_median','priority_score'])
    def aggregate(row,window_sizes):
        sigs=[]
        for w in window_sizes:
            valid=row.get(f'is_valid_{w}w',False)
            signal=row.get(f'signal_{w}w','NONE')
            if pd.notna(valid) and bool(valid) and signal in ('UP','DOWN'):
                sigs.append(signal)
        if not sigs:return 'NONE'
        if sigs.count('UP')>sigs.count('DOWN'):return 'UP'
        if sigs.count('DOWN')>sigs.count('UP'):return 'DOWN'
        return 'MIXED'
    out=[]
    for _,row in wide.iterrows():
        short,long=aggregate(row,(13,26)),aggregate(row,(78,104))
        state=(f'COHERENT_MULTI_{short}' if short in ('UP','DOWN') and short==long
               else 'NO_BUBBLE' if short==long=='NONE' else 'MIXED_SCALES')
        med=row['tc_weeks_ahead_median']
        bonus=2. if state.startswith('COHERENT_MULTI_') else (0.5 if state=='MIXED_SCALES' else 0.)
        score=100*(bonus+row['valid_frac'])/(1.+max(0,med)/10 if pd.notna(med) else 1.)
        out.append({'asset':row['asset'],'bubble_short_term':short,'bubble_long_term':long,
                    'bubble_multiscale_state':state,'valid_frac':row['valid_frac'],
                    'tc_weeks_ahead_median':med,'priority_score':score})
    return pd.DataFrame(out).sort_values('priority_score',ascending=False)


def targets(weekly, bubble_type):
    """Weights from the current and past prices only; missing assets remain at zero."""
    assets=weekly.columns
    state=bubble_type.set_index('asset') if not bubble_type.empty else pd.DataFrame(index=assets)
    rets=weekly.pct_change(fill_method=None)
    vol=rets.tail(52).std(min_count=13)
    inv=1/vol.where(vol>0)
    inv=inv.replace([np.inf,-np.inf],np.nan).fillna(0.)
    up=set(state.index[state['bubble_multiscale_state']=='COHERENT_MULTI_UP']) if len(state) else set()
    longs=[a for a in assets if a in state.index and a not in up and inv.get(a,0)>0]
    shorts=[a for a in assets if a in up and inv.get(a,0)>0]
    lo=pd.Series(0.,index=assets)
    ls=pd.Series(0.,index=assets)
    if longs:
        weights=inv[longs]/inv[longs].sum()
        lo.loc[longs]=weights
        ls.loc[longs]=weights*(0.5 if shorts else 1.)
    if shorts:
        score=state.loc[shorts,'priority_score'].clip(lower=0)
        if score.sum()>0:
            ls.loc[shorts]=-score/score.sum()*(0.5 if longs else 0.5)
    return lo,ls


def write_snapshot_outputs(weekly, outdir, grid='full'):
    from matplotlib import pyplot as plt
    outdir=Path(outdir);outdir.mkdir(parents=True,exist_ok=True)
    details=calculate_details(weekly,grid=grid)
    if details.empty:
        raise ValueError('Aucun actif avec 104 semaines consécutives de prix valides.')
    wide=summarize(details)
    bubble=bubble_classification(wide)
    bubble_wide=wide.drop(columns=['valid_frac','tc_weeks_ahead_median']).merge(bubble,on='asset',how='left')
    lo,ls=targets(weekly,bubble)
    portfolio=bubble[['asset','bubble_multiscale_state','priority_score']].copy()
    portfolio['weight_long_only']=portfolio['asset'].map(lo).fillna(0)
    portfolio['weight_long_short']=portfolio['asset'].map(ls).fillna(0)
    portfolio['rationale']=np.where(portfolio['bubble_multiscale_state']=='COHERENT_MULTI_UP',
              'Sous-pondération / short (signal LPPLS UP)', 'Éligible à la poche acheteuse')
    outputs={'details_by_scale_all_series.csv':details,'summary_by_scale_wide.csv':wide,
             'bubble_type_by_asset.csv':bubble,'bubble_summary_by_scale_wide.csv':bubble_wide,
             'portfolio_construction.csv':portfolio}
    for filename,frame in outputs.items():
        frame.to_csv(outdir/filename,index=False)
    heat=details.assign(signal_num=details['signal'].map({'UP':1,'DOWN':-1}).fillna(0)*details['is_valid'].astype(int))
    matrix=heat.pivot(index='asset',columns='window_weeks',values='signal_num').reindex(bubble['asset'])
    fig,ax=plt.subplots(figsize=(10,max(5,len(matrix)*0.32)))
    plot=ax.imshow(matrix.fillna(0).to_numpy(),aspect='auto',vmin=-1,vmax=1,cmap='coolwarm')
    ax.set_yticks(range(len(matrix)),labels=matrix.index,fontsize=7)
    ax.set_xticks(range(len(matrix.columns)),labels=[str(c)+'w' for c in matrix.columns])
    ax.set_title('LPPLS : UP=+1 / DOWN=-1 / invalide=0')
    fig.colorbar(plot,ax=ax);fig.tight_layout();fig.savefig(outdir/'heatmap_global.png',dpi=150);plt.close(fig)
    return outputs


def run_backtest(weekly, outdir, start_date='2024-02-01', rebalance_weeks=4,
                 costs_bps=0., grid='tiny', max_rebalances=None):
    """Weekly mark-to-market, fixed target weights between rebalances, no future eligibility.

    A Friday signal is invested starting with the following weekly return.
    Missing next-week returns prohibit investing that asset at the prior rebalance only
    if its *current* price is unavailable; subsequent missing returns are flagged as
    missing-data events and the position is valued with 0 for that week (stale-price
    convention, not an observed 0% return). This assumption must be reviewed.
    """
    from matplotlib import pyplot as plt
    outdir=Path(outdir);outdir.mkdir(parents=True,exist_ok=True)
    if rebalance_weeks<1:raise ValueError('rebalance_weeks doit être >=1')
    returns=weekly.pct_change(fill_method=None)
    dates=weekly.index
    candidate=[d for d in dates if d>=pd.Timestamp(start_date) and dates.get_loc(d)>=max(WINDOWS)-1]
    if len(candidate)<2:raise ValueError('Historique insuffisant pour le backtest (104 semaines + dates futures).')
    rebalances=list(candidate[::rebalance_weeks])
    rebalances=[d for d in rebalances if dates.get_loc(d)<len(dates)-1]
    if max_rebalances is not None:rebalances=rebalances[:max_rebalances]
    if not rebalances:raise ValueError('Aucune date de rééquilibrage admissible.')
    assets=list(weekly.columns)
    saved=[]; rows=[]; turn=[]; state_rows=[];missing_rows=[]
    prior_lo=pd.Series(0.,index=assets);prior_ls=prior_lo.copy()
    nav_lo=nav_ls=nav_eq=1.
    active_lo=prior_lo.copy();active_ls=prior_ls.copy();active_eq=prior_lo.copy()
    history_dates=[d for d in dates if d>=rebalances[0]]
    rebal_set=set(rebalances)
    for j,d in enumerate(history_dates):
        if j==0:
            rlo=rls=req=0.
        else:
            ret=returns.loc[d].reindex(assets)
            impacted=ret.isna() & ((active_lo.abs()+active_ls.abs()+active_eq.abs())>0)
            for a in ret.index[impacted]:missing_rows.append({'date':d.date().isoformat(),'asset':a,'convention':'stale-price, return forced 0'})
            ret=ret.fillna(0.)
            rlo=float((active_lo*ret).sum())
            rls=float((active_ls*ret).sum())
            req=float((active_eq*ret).sum())
            nav_lo*=1+rlo;nav_ls*=1+rls;nav_eq*=1+req
        if d in rebal_set:
            history=weekly.loc[:d]
            # Exactly 104 consecutive calendar weeks, and price observable at decision date.
            eligible=[a for a in assets if len(history[a])>=104 and history[a].iloc[-104:].notna().all()]
            if eligible:
                bt=bubble_classification(summarize(calculate_details(history[eligible],grid=grid)))
                target_lo,target_ls=targets(history[eligible],bt)
                target_lo=target_lo.reindex(assets).fillna(0.)
                target_ls=target_ls.reindex(assets).fillna(0.)
                state=bt.set_index('asset')['bubble_multiscale_state']
            else:
                target_lo=prior_lo*0;target_ls=prior_ls*0;state=pd.Series(dtype='object')
            eq=pd.Series(0.,index=assets)
            if eligible:eq.loc[eligible]=1./len(eligible)
            # All positions intentionally reset to targets; no unnormalized lazy rebalance.
            turnover_lo=float((target_lo-active_lo).abs().sum())
            turnover_ls=float((target_ls-active_ls).abs().sum())
            charge_lo=turnover_lo*costs_bps/10000.
            charge_ls=turnover_ls*costs_bps/10000.
            nav_lo*=max(0.,1.-charge_lo);nav_ls*=max(0.,1.-charge_ls)
            active_lo,active_ls,active_eq=target_lo,target_ls,eq
            prior_lo,prior_ls=active_lo.copy(),active_ls.copy()
            turn.append({'date':d.date().isoformat(),'turnover_long_only_one_way':turnover_lo,
                         'turnover_long_short_one_way':turnover_ls,'cost_long_only':charge_lo,'cost_long_short':charge_ls})
            for a in assets:
                saved.append({'date':d.date().isoformat(),'asset':a,'weight_long_only':float(active_lo[a]),
                              'weight_long_short':float(active_ls[a]),'weight_equal_weight':float(active_eq[a])})
                state_rows.append({'date':d.date().isoformat(),'asset':a,'state':state.get(a,'INELIGIBLE')})
        rows.append({'date':d.date().isoformat(),'nav_long_only':nav_lo,'nav_long_short':nav_ls,
                     'nav_equal_weight':nav_eq,'ret_long_only':rlo,'ret_long_short':rls,'ret_equal_weight':req})
    weights=pd.DataFrame(saved)
    weights[['date','asset','weight_long_only']].rename(columns={'weight_long_only':'weight'}).to_csv(outdir/'backtest_portfolios_long_only_weights.csv',index=False)
    weights[['date','asset','weight_long_short']].rename(columns={'weight_long_short':'weight'}).to_csv(outdir/'backtest_portfolios_long_short_weights.csv',index=False)
    weights.pivot(index='date',columns='asset',values='weight_long_only').fillna(0).to_csv(outdir/'backtest_portfolios_long_only_weights_wide.csv')
    weights.pivot(index='date',columns='asset',values='weight_long_short').fillna(0).to_csv(outdir/'backtest_portfolios_long_short_weights_wide.csv')
    pd.DataFrame(state_rows).to_csv(outdir/'backtest_states.csv',index=False)
    pd.DataFrame(turn).to_csv(outdir/'backtest_turnover.csv',index=False)
    pd.DataFrame(missing_rows,columns=['date','asset','convention']).to_csv(outdir/'backtest_missing_returns.csv',index=False)
    nav=pd.DataFrame(rows);nav.to_csv(outdir/'backtest_nav_weekly.csv',index=False)
    metrics=[]
    for name in ('long_only','long_short','equal_weight'):
        v=nav['nav_'+name];r=nav['ret_'+name].iloc[1:]
        years=len(r)/52.
        metrics.append({'strategy':name,'start_date':nav['date'].iloc[0],'end_date':nav['date'].iloc[-1],
                        'total_return':float(v.iloc[-1]-1),'annualized_return':float(v.iloc[-1]**(1/years)-1) if years and v.iloc[-1]>0 else np.nan,
                        'annualized_volatility':float(r.std(ddof=1)*np.sqrt(52)),
                        'sharpe_rf_zero':float(r.mean()/r.std(ddof=1)*np.sqrt(52)) if r.std(ddof=1)>0 else np.nan,
                        'max_drawdown':float((1-v/v.cummax()).max()),'n_rebalances':len(rebalances),
                        'cost_bps':costs_bps,'missing_return_observations':len(missing_rows)})
    metricdf=pd.DataFrame(metrics)
    metricdf.to_csv(outdir/'backtest_summary_metrics.csv',index=False)
    fig,ax=plt.subplots(figsize=(10,5))
    for name in ('long_only','long_short','equal_weight'):
        ax.plot(pd.to_datetime(nav['date']),nav['nav_'+name],label=name)
    ax.legend();ax.set_title('Backtest LPPLS — NAV hebdomadaire (exploratoire)')
    ax.set_ylabel('Valeur de 1 unité');fig.tight_layout();fig.savefig(outdir/'backtest_nav_plot.png',dpi=150);plt.close(fig)
    return metricdf
