"""Tests de non-régression du moteur retenu. Données synthétiques uniquement."""
from pathlib import Path
import numpy as np
import pandas as pd
from lppls_bubble.backtest import BacktestSettings, load_weekly, run_backtest
from lppls_bubble.legacy_engine import run_snapshot
from lppls_bubble.prices import weekly_prices

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "research/reproducible_2026_11_04/examples/synthetic_example.csv"


def test_standard_csv_matches_datastream(tmp_path):
    sample = pd.read_csv(EXAMPLE, sep=";")
    path = tmp_path / "old.csv"
    path.write_text("Start;2022\nEnd;2025\nFrequency;Daily\n" +
                    sample.rename(columns={"date":"Name"}).to_csv(sep=";", index=False))
    pd.testing.assert_frame_equal(load_weekly(EXAMPLE), load_weekly(path), check_exact=True)


def test_missing_calendar_week_prevents_104_week_fit(tmp_path):
    sample = pd.read_csv(EXAMPLE, sep=";")
    sample["date"] = pd.to_datetime(sample.date, dayfirst=True)
    sample = sample.set_index("date").resample("W-FRI").last().reset_index()
    sample["date"] = sample.date.dt.strftime("%d/%m/%Y")
    sample.loc[len(sample)-45, "EXAMPLE_B"] = np.nan
    path = tmp_path / "missing.csv"
    sample.to_csv(path, sep=";", index=False)
    results = run_snapshot(path, tmp_path / "out")
    windows = set(results["details"].query("asset == 'EXAMPLE_B'").window_weeks)
    assert windows == {13,26,39}
    weights = results["portfolio"].set_index("asset")
    assert weights.loc["EXAMPLE_B", "weight_long_only"] == 0
    assert weights.loc["EXAMPLE_B", "weight_long_short"] == 0


def test_totally_empty_week_stays_on_calendar_axis(tmp_path):
    sample = pd.read_csv(EXAMPLE, sep=";")
    sample["date"] = pd.to_datetime(sample.date, dayfirst=True)
    sample = sample.set_index("date").resample("W-FRI").last().reset_index()
    sample["date"] = sample.date.dt.strftime("%d/%m/%Y")
    missed = pd.to_datetime(sample.loc[len(sample)-45,"date"], dayfirst=True)
    sample.loc[len(sample)-45, ["EXAMPLE_A","EXAMPLE_B"]] = np.nan
    path = tmp_path / "gap.csv"
    sample.to_csv(path, sep=";", index=False)
    weekly = weekly_prices(path)
    assert len(weekly) == 164
    assert weekly.loc[missed].isna().all()
    result = run_snapshot(path, tmp_path / "out")
    assert not result["details"].window_weeks.isin([65,78,104]).any()


def test_rebalance_fees_reconcile_with_nav(tmp_path):
    result = run_backtest(EXAMPLE, tmp_path / "out",
        BacktestSettings(start_date="2024-02-02", max_rebalances=3, hold_weeks=4, fee_bps=15))
    nav = result["nav"]
    for strategy in ("long_only", "long_short"):
        actual = nav["nav_"+strategy].pct_change().iloc[1:]
        reported = nav["ret_"+strategy].iloc[1:]
        np.testing.assert_allclose(actual, reported, atol=1e-12, rtol=0)
        np.testing.assert_allclose(nav["nav_"+strategy].iloc[0],
                                   1+nav["ret_"+strategy].iloc[0], atol=1e-12, rtol=0)
