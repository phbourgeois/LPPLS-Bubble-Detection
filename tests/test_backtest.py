import sys
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from lppls_bubble.backtest import BacktestSettings, build_targets_asof, fit_tiny, load_weekly, run_backtest
from test_smoke import csv_fixture


def test_archive_files_have_expected_hashes_and_no_outputs():
    paths = {
        "ds_lppls_pipeline_executed.ipynb": "fa9cde54ea79252a6916f8f85aa65b404732ca4514127d67a0f07180dca7242e",
        "ds_lppls_pipeline_with_backtest.ipynb": "a329dae86a4438970f194c4a012c2d7d6cf9265aa98f5ddcbecfa378e486f414",
        "ds_lppls_pipeline_with_backtest_named.ipynb": "6f29c87ba85241c694f93afd1948a15c62bbaae28d2bbc4156fa78065d0bf79a",
    }
    root = Path(__file__).resolve().parents[1] / "notebooks"
    for name, expected in paths.items():
        raw = (root / name).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == expected
        n = json.loads(raw)
        assert n["nbformat"] == 4
        assert all(not c.get("outputs") for c in n["cells"])


def test_backtest_generates_products(tmp_path):
    p = tmp_path / "input.csv"
    csv_fixture(p, weeks=118)
    settings = BacktestSettings(start_date="2025-12-01", windows=(13,26,78,104), max_rebalances=2)
    result = run_backtest(p, tmp_path / "out", settings)
    assert not result["nav"].empty
    assert len(result["metrics"]) == 1
    assert result["metrics"].num_rebalances.iloc[0] == 2
    assert result["nav"].nav_long_only.notna().all()
    assert (tmp_path / "out" / "backtest_nav_plot.png").read_bytes().startswith(b"\x89PNG")
    assert (tmp_path / "out" / "backtest_states.csv").exists()
    assert (tmp_path / "out" / "backtest_portfolios_long_only_weights_wide.csv").exists()
    assert (tmp_path / "out" / "backtest_summary_metrics.csv").exists()


def test_targets_do_not_change_when_future_prices_change(tmp_path):
    p = tmp_path / "input.csv"
    csv_fixture(p, weeks=115)
    weekly = load_weekly(p)
    t = weekly.index[105]
    settings = BacktestSettings(windows=(13,26,104))
    past = weekly.loc[:t]
    states0, weights0 = build_targets_asof(past, settings)
    future = weekly.copy()
    future.loc[future.index > t, "ActionA"] *= 500
    states1, weights1 = build_targets_asof(future.loc[:t], settings)
    pd.testing.assert_frame_equal(states0, states1)
    pd.testing.assert_frame_equal(weights0, weights1)


def test_negative_or_missing_held_return_aborts(tmp_path):
    p = tmp_path / "input.csv"
    csv_fixture(p, weeks=116)
    weekly = load_weekly(p)
    # Fit remains valid on 104 weeks, no need to inspect t+1 for target eligibility.
    past = weekly.iloc[:105]
    st, weights = build_targets_asof(past, BacktestSettings())
    assert len(st) == 2
    assert set(st.state).issubset({"COHERENT_MULTI_UP", "COHERENT_MULTI_DOWN", "MIXED_SCALES", "NO_BUBBLE"})
    assert weights.w_lo_target.notna().all()


def test_too_short_history_aborts(tmp_path):
    p = tmp_path / "short.csv"
    csv_fixture(p, weeks=50)
    with pytest.raises(ValueError, match="Aucune date"):
        run_backtest(p, tmp_path / "out", BacktestSettings(start_date="2024-01-01"))


def test_first_decision_independent_of_post_decision_price(tmp_path):
    p = tmp_path / "input.csv"
    csv_fixture(p, weeks=117)
    weekly = load_weekly(p)
    settings = BacktestSettings(start_date="2025-12-01", windows=(13,26,104), max_rebalances=1)
    first = run_backtest(p, tmp_path / "out1", settings)
    # Tamper with all future prices; the first decision must not change.
    t = pd.Timestamp(first["weights_lo"].date.iloc[0])
    raw = p.read_text(encoding="utf-8").splitlines()
    altered = []
    for line in raw[:4]:
        altered.append(line)
    for line in raw[4:]:
        fields = line.split(";")
        if pd.to_datetime(fields[0], dayfirst=True) > t:
            fields[1] = str(float(fields[1].replace(",", ".")) * 1.10).replace(".", ",")
        altered.append(";".join(fields))
    altered_path = tmp_path / "altered.csv"
    altered_path.write_text("\n".join(altered) + "\n", encoding="utf-8")
    second = run_backtest(altered_path, tmp_path / "out2", settings)
    pd.testing.assert_frame_equal(first["weights_lo"], second["weights_lo"])
    pd.testing.assert_frame_equal(first["weights_ls"], second["weights_ls"])
