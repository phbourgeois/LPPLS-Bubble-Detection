"""Regression tests for complete weeks, causality, attribution and reports."""
from pathlib import Path
import sys
import numpy as np
import pandas as pd
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lppls_bubble.backtest import BacktestSettings, run_backtest
from lppls_bubble.backtest_audit import weekly_price_alerts
from lppls_bubble.prices import completed_weekly_prices


def _csv_fixture(path: Path, n_weeks: int = 115) -> Path:
    # Two assets with complete prices and no artificial price adjustment needed.
    dates = pd.date_range("2023-01-06", periods=n_weeks, freq="W-FRI")
    x = 100 * np.exp(np.linspace(0, .25, n_weeks) + .02 * np.sin(np.arange(n_weeks) / 5))
    y = 70 * np.exp(np.linspace(0, -.2, n_weeks) + .01 * np.cos(np.arange(n_weeks) / 6))
    pd.DataFrame({"Date": dates.strftime("%Y-%m-%d"), "A": x, "B": y}).to_csv(path, index=False, sep=";")
    return path


def test_final_partial_week_excluded_but_history_kept():
    dates = pd.to_datetime(["2026-10-23", "2026-10-30", "2026-11-03"])
    df = pd.DataFrame({"A": [100., 105., 110.]}, index=dates)
    weekly = completed_weekly_prices(df)
    assert weekly.index[-1] == pd.Timestamp("2026-10-30")
    assert weekly.A.iloc[-1] == 105
    assert completed_weekly_prices(df, include_partial=True).index[-1] == pd.Timestamp("2026-11-06")


def test_quality_flags_week_between_rebalances():
    dates = pd.date_range("2024-01-05", periods=12, freq="W-FRI")
    frame = pd.DataFrame({"A": [10., 10., 10., 10., 10., 10., 10., 10., 50., 5., 6., 6.]}, index=dates)
    flagged = weekly_price_alerts(frame, dates[0], dates[-1], stale_weeks=20)
    assert list(flagged.date) == [str(dates[8].date()), str(dates[9].date())]
    assert set(flagged.severity) == {"CRITICAL_REVIEW"}


def test_full_period_run_reconciles_reports_and_attribution(tmp_path):
    input_csv = _csv_fixture(tmp_path / "prices.csv", 117)
    settings = BacktestSettings(
        start_date="2024-01-05", windows=(13, 26, 78, 104),
        hold_weeks=4, max_rebalances=None, fee_bps=2.0,
    )
    result = run_backtest(input_csv, tmp_path / "out", settings)
    nav, attr, recon = result["nav"], result["attribution"], result["reconciliation"]
    assert nav.date.iloc[-1] == "2025-03-28"
    assert (tmp_path / "out" / "backtest_report.html").exists()
    assert (tmp_path / "out" / "backtest_report.pdf").read_bytes().startswith(b"%PDF-")
    assert (tmp_path / "out" / "backtest_attribution_weekly.csv").exists()
    assert (tmp_path / "out" / "backtest_quality_weekly_alerts.csv").exists()
    for strategy in ("long_only", "long_short"):
        rows = recon[recon.strategy == strategy].set_index("date")
        contributions = attr[attr.strategy == strategy].groupby("date")["return_contribution"].sum()
        assert np.allclose(contributions.loc[rows.index], rows.gross_asset_return)
        assert np.allclose(rows.gross_asset_return + rows.transaction_cost_contribution, rows.net_return)
        assert np.allclose(rows.expected_net_return, rows.net_return)
        assert np.allclose(
            rows.transaction_cost_contribution,
            -(1 + rows.gross_asset_return) * rows.absolute_traded_weight * settings.fee_bps / 10000,
        )
        assert np.max(abs(rows.reconciliation_error)) < 1e-10
        assert np.allclose(rows.net_return, nav.set_index("date")["ret_" + strategy])
    metrics = result["metrics"].iloc[0]
    assert "annualized_return_long_only" in metrics.index
    assert "annualized_volatility_long_short" in metrics.index
    assert "max_single_asset_weight_long_only" in metrics.index
    assert metrics.num_rebalances > 0
    assert metrics.annualized_return_long_only == pytest.approx(
        nav.nav_long_only.iloc[-1] ** (52 / (len(nav) - 1)) - 1,
        rel=1e-8,
    )


def test_bounded_run_still_available(tmp_path):
    input_csv = _csv_fixture(tmp_path / "prices.csv", 116)
    cfg = BacktestSettings(start_date="2024-01-05", windows=(13, 26, 78, 104),
                           hold_weeks=4, max_rebalances=2)
    result = run_backtest(input_csv, tmp_path / "out", cfg)
    assert int(result["metrics"].num_rebalances.iloc[0]) == 2
    assert len(result["nav"]) == 9
