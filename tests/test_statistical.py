"""No network, no GitHub Actions: deterministic LPPLS inference checks."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lppls_bubble.prices import weekly_prices
from lppls_bubble.statistical import (StatisticalConfig, calibrated_window,
    benjamini_hochberg, decide_asof, _bootstrap_returns)
from scripts.validate_lppls_oos import (eligible_windows, aggregate_alert, decision_dates)


def test_iso_and_french_dates_are_parsed_same_calendar(tmp_path):
    dates=pd.date_range('2011-01-07',periods=28,freq='W-FRI')
    iso=pd.DataFrame({'date':dates.strftime('%Y-%m-%d'),'AAPL':np.arange(28)+10})
    fr=pd.DataFrame({'Name':dates.strftime('%d/%m/%Y'),'AAPL':np.arange(28)+10})
    p1=tmp_path/'iso.csv';p2=tmp_path/'fr.csv'
    iso.to_csv(p1,index=False);fr.to_csv(p2,index=False,sep=';')
    a=weekly_prices(p1);b=weekly_prices(p2)
    pd.testing.assert_frame_equal(a,b)
    assert str(a.index[0].date())=='2011-01-07'
    assert str(a.index[-1].date())=='2011-07-15'


def test_bh_known_values():
    rejected,q=benjamini_hochberg(np.array([.01,.04,.03,.3]),.05)
    np.testing.assert_allclose(q,[.04,.05333333333333334,.05333333333333334,.3])
    assert rejected.tolist()==[True,False,False,False]


def test_joint_p_causal_deterministic():
    rng=np.random.default_rng(57)
    y=4+np.cumsum(rng.normal(.002,.01,size=104))
    c=StatisticalConfig(windows=(104,),bootstrap_draws=39)
    result=calibrated_window(y,c,'2024-01-05','ABC')
    assert result==calibrated_window(y,c,'2024-01-05','ABC')
    assert result['p_joint']>=max(result['p_block'],result['p_gaussian'])
    assert result['p_joint']>=1/40
    assert result['signal'] in ['UP','DOWN','NONE']


def test_future_prices_cannot_change_asof_signal():
    rng=np.random.default_rng(104)
    dates=pd.date_range('2020-01-03',periods=150,freq='W-FRI')
    prices=pd.DataFrame({'A':np.exp(4+np.cumsum(rng.normal(.002,.02,150))),
                         'B':np.exp(4+np.cumsum(rng.normal(0,.015,150)))},index=dates)
    config=StatisticalConfig(bootstrap_draws=39)
    t=120;asof=str(dates[t].date())
    before=decide_asof(eligible_windows(prices,t,config),config,asof)
    modified=prices.copy()
    modified.iloc[t+1:,:]*=15
    after=decide_asof(eligible_windows(modified,t,config),config,asof)
    assert before==after


def test_missing_week_excluded_and_family_still_counts_other_windows():
    rng=np.random.default_rng(97)
    dates=pd.date_range('2020-01-03',periods=120,freq='W-FRI')
    p=pd.DataFrame({'A':np.exp(4+np.cumsum(rng.normal(0,.02,120))),
                    'B':np.exp(4+np.cumsum(rng.normal(0,.02,120)))},index=dates)
    p.loc[dates[-70],'A']=np.nan
    c=StatisticalConfig(bootstrap_draws=19)
    windows=eligible_windows(p,119,c)
    assert set(windows['A'])=={52}
    assert set(windows['B'])=={52,104}
    tests=decide_asof(windows,c,str(dates[-1].date()))
    assert len(tests)==3


def test_block_bootstrap_never_reads_nonexistent_future():
    x=np.arange(1,12,dtype=float)
    a,b=_bootstrap_returns(x,12,4,np.random.default_rng(3))
    assert a.shape==b.shape==(12,len(x))
    assert set(a.ravel()).issubset(set(x))


def test_empty_no_discovery():
    assert aggregate_alert([], 'A')==('NONE',1.0)
    reject,q=benjamini_hochberg(np.array([]),.1)
    assert len(reject)==len(q)==0


def test_config_validation():
    with pytest.raises(ValueError):StatisticalConfig(windows=(13,)).validate()
    with pytest.raises(ValueError):StatisticalConfig(bootstrap_draws=10).validate()
