"""Regression tests for comparable original and mixed-scale LPPLS portfolios."""
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from lppls_bubble.backtest import BacktestSettings, run_backtest
from lppls_bubble.backtest_comparison import (
    SCENARIOS, _mixed_targets, _replay, run_strategy_comparison,
)


def _sample_states():
    return pd.DataFrame({
        "asset": ["A", "B", "C", "D", "E", "F"],
        "state": [
            "COHERENT_MULTI_DOWN", "COHERENT_MULTI_UP", "MIXED_SCALES",
            "MIXED_SCALES", "MIXED_SCALES", "INELIGIBLE",
        ],
        "bubble_short_term": ["DOWN", "UP", "UP", "DOWN", "MIXED", "NONE"],
        "bubble_long_term": ["DOWN", "UP", "DOWN", "UP", "UP", "NONE"],
        "priority_score": [20., 30., 40., 50., 60., 0.],
    })


def _sample_prices(weeks=110):
    dates = pd.date_range("2023-01-06", periods=weeks, freq="W-FRI")
    values = {
        asset: 90. * np.exp((i+1)*.0002*np.arange(weeks)
                             + .02*np.sin(np.arange(weeks)/7 + i))
        for i, asset in enumerate(_sample_states().asset)
    }
    return pd.DataFrame(values, index=dates)


def test_mixed_signals_keep_only_explicit_opposites():
    states = _sample_states()
    prices = _sample_prices()
    targets = _mixed_targets(states, prices)
    b = targets["benchmark_equal_weight"]
    ml = targets["mixed_long_only"]
    mls = targets["mixed_long_short"]
    assert b.sum() == pytest.approx(5/5)
    assert b["F"] == 0.0
    assert ml.sum() == pytest.approx(1.0)
    assert ml["A"] > 0 and ml["C"] > 0
    assert all(ml[x] == 0 for x in ("B", "D", "F"))\n    assert ml["E"] > 0  # ambiguous MIXED retained as in original
    assert mls["A"] > 0 and mls["C"] > 0
    assert mls["B"] < 0 and mls["D"] < 0
    assert mls["E"] > 0 and mls["F"] == 0
    assert mls.clip(lower=0).sum() == pytest.approx(.5)
    assert -mls.clip(upper=0).sum() == pytest.approx(.5)
    # Same short score weighting as original (not inverse volatility).
    assert mls["D"]/mls["B"] == pytest.approx(50./30.)


def test_replay_uses_only_weekly_returns_after_decisions():
    prices = _sample_prices(108)
    timeline = prices.index[-5:]
    states = _sample_states()
    targets = _mixed_targets(states, prices.loc[:timeline[0]])
    by_date = {
        timeline[0]: {
            **targets,
            "original_long_only": targets["benchmark_equal_weight"],
            "original_long_short": targets["benchmark_equal_weight"],
        },
    }
    nav, exposures, trades = _replay(prices, timeline, by_date, fee_bps=1.0)
    assert len(nav) == 5 and set(trades.strategy) == set(SCENARIOS)
    assert (nav.iloc[0].filter(like="nav_") < 1.0).all()  # setup trading cost
    # All strategies start flat, and the first NAV row is the setup fee only.
    assert (exposures.loc[exposures.date == timeline[0].date().isoformat(),
                          "long_exposure"] == 0).all()


def test_replayed_original_NAV_and_standalone_reports(tmp_path):
    dates = pd.date_range("2023-01-06", periods=116, freq="W-FRI")
    t = np.arange(len(dates))
    frame = pd.DataFrame({
        "Date": dates.strftime("%Y-%m-%d"),
        "A": 100*np.exp(.001*t+.018*np.sin(t/8)),
        "B": 80*np.exp(-.0005*t+.02*np.cos(t/9)),
        "C": 90*np.exp(.0008*t+.015*np.sin(t/5)),
    })
    csv = tmp_path / "market.csv"
    frame.to_csv(csv, sep=";", index=False)
    cfg = BacktestSettings(
        start_date="2025-01-03", hold_weeks=4,
        windows=(13, 26, 78, 104), max_rebalances=2, fee_bps=2.0,
    )
    report_context = {
        "study_type": "RETROSPECTIVE_SENSITIVITY",
        "source_asset_count": 4, "snapshot_assets": 4,
        "backtest_assets": 3,
        "excluded_assets": [{
            "asset": "TEST EXCLUDED", "scope": "BACKTEST_ONLY",
            "classification": "RETROSPECTIVE_SENSITIVITY",
            "justification": "Test documented discontinuity",
        }],
    }
    result = run_backtest(
        csv, tmp_path / "results", cfg, report_context=report_context,
    )
    comparison = result["comparison"]
    assert set(comparison["metrics"].strategy) == set(SCENARIOS)
    assert len(comparison["nav"]) == len(result["nav"])
    np.testing.assert_allclose(
        result["nav"].nav_long_only,
        comparison["nav"].nav_original_long_only,
        atol=1e-10,
    )
    np.testing.assert_allclose(
        result["nav"].nav_long_short,
        comparison["nav"].nav_original_long_short,
        atol=1e-10,
    )
    outdir = tmp_path / "results"
    for name in (
        "backtest_comparison_metrics.csv",
        "backtest_comparison_nav.csv",
        "backtest_comparison_exposures.csv",
        "backtest_comparison_targets.csv",
        "backtest_comparison_gaps.csv",
        "backtest_comparison_nav.png",
        "backtest_report.html", "backtest_report.pdf",
    ):
        assert (outdir/name).is_file(), name
    html = (outdir/"backtest_report.html").read_text(encoding="utf-8")
    assert "TEST EXCLUDED" in html
    assert "RETROSPECTIVE_SENSITIVITY" in html
    assert "benchmark_equal_weight" in html
    assert "mixed_long_short" in html
    assert (outdir/"backtest_report.pdf").read_bytes().startswith(b"%PDF-")
