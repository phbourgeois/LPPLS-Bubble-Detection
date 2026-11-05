"""Regression tests: one full-grid LPPLS estimator for snapshot and backtest."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from lppls_bubble.lppls_fit import GRID_VERSION, GRID_SIZE, fit_lppls, classify_lppls, _designs
from lppls_bubble.backtest import BacktestSettings, build_targets_asof, fit_tiny, classify
from lppls_bubble.legacy_engine import run_snapshot


def reference_full_grid(y):
    """Independent straightforward legacy least-squares loop: all 343 candidates."""
    n = len(y)
    t = np.arange(n, dtype=float)
    ahead_max = min(1.5*n, max(6,n))
    best = None
    for m in np.linspace(.1,.9,7):
        for omega in np.linspace(6.0,13.0,7):
            for ahead in np.linspace(1, ahead_max,7):
                tc = n-1+ahead
                tau = tc-t
                x1 = tau**m
                a = omega*np.log(tau)
                X = np.column_stack((np.ones(n),x1,x1*np.cos(a),x1*np.sin(a)))
                beta, *_ = np.linalg.lstsq(X,y,rcond=None)
                resid = X@beta-y
                sse = float(np.dot(resid,resid))
                if best is None or sse < best["sse"]:
                    best = {"sse":sse,"B":float(beta[1]),"m":m,"omega":omega,"tc":tc,
                            "r2":1-sse/np.sum((y-y.mean())**2)}
    return best


@pytest.mark.parametrize("n", [13,26,39,52,65,78,104])
def test_cached_full_grid_matches_original_legacy_solver(n):
    rng = np.random.default_rng(20261105+n)
    for _ in range(3):
        y = np.log(100)+np.cumsum(rng.normal(0,.015,n))
        ref = reference_full_grid(y)
        fit = fit_lppls(y)
        for k in ("sse","B","m","omega","tc","r2"):
            assert fit[k] == pytest.approx(ref[k], rel=1e-7, abs=1e-9)
        assert classify_lppls(fit) == classify(fit_tiny(y))
    design,pinv,grid = _designs(n)
    assert design.shape == (343,n,4)
    assert pinv.shape == (343,4,n)
    assert grid.shape == (343,3)
    assert GRID_SIZE == 343
    assert GRID_VERSION == "legacy_full_7x7x7_v1"


def test_snapshot_and_backtest_last_date_share_signals(tmp_path):
    idx = pd.date_range("2023-01-06", periods=115, freq="W-FRI")
    a = 100*np.exp(.001*np.arange(len(idx))+.02*np.sin(np.arange(len(idx))/5))
    b = 80*np.exp(-.0009*np.arange(len(idx))+.016*np.cos(np.arange(len(idx))/9))
    csv = tmp_path/"prices.csv"
    pd.DataFrame({"Date":idx.strftime("%Y-%m-%d"),"A":a,"B":b}).to_csv(csv,sep=";",index=False)
    windows = (13,26,39,52,65,78,104)
    snapshot = run_snapshot(csv,tmp_path/"snapshot",windows)
    assert snapshot["grid_version"] == GRID_VERSION
    states,_ = build_targets_asof(snapshot["weekly"], BacktestSettings(windows=windows))
    bubble = snapshot["bubble_type"].set_index("asset")
    states = states.set_index("asset")
    for asset in ("A","B"):
        assert states.loc[asset,"state"] == bubble.loc[asset,"bubble_multiscale_state"]
        assert states.loc[asset,"bubble_short_term"] == bubble.loc[asset,"bubble_short_term"]
        assert states.loc[asset,"bubble_long_term"] == bubble.loc[asset,"bubble_long_term"]
        assert states.loc[asset,"priority_score"] == pytest.approx(
            bubble.loc[asset,"priority_score"], abs=1e-7
        )


def test_grid_is_shared_and_future_data_never_changes_prior_signal():
    rng = np.random.default_rng(42)
    p = pd.DataFrame(
        {"A":100*np.exp(np.cumsum(rng.normal(0,.012,118)))},
        index=pd.date_range("2024-01-05",periods=118,freq="W-FRI")
    )
    cfg = BacktestSettings(windows=(13,26,39,52,65,78,104))
    first,_ = build_targets_asof(p.iloc[:110],cfg)
    changed = p.copy()
    changed.iloc[110:,0] *= 300
    second,_ = build_targets_asof(changed.iloc[:110],cfg)
    pd.testing.assert_frame_equal(first,second)
