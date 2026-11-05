"""Integration regression: analysed CSV used consistently in LPPLS and backtest."""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from lppls_bubble.data_review import audit_prices, validate_and_apply
from lppls_bubble.legacy_engine import run_snapshot
from lppls_bubble.backtest import BacktestSettings, run_backtest


def _sample(path: Path) -> Path:
    dates = pd.date_range("2023-01-06", periods=118, freq="W-FRI")
    n = np.arange(len(dates))
    a = 100*np.exp(.001*n + .02*np.sin(n/8))
    a[107] *= 6
    b = 90*np.exp(.0015*n + .01*np.cos(n/7))
    pd.DataFrame({"Date":dates.strftime("%Y-%m-%d"),"A":a,"B":b}).to_csv(
        path,sep=";",index=False)
    return path


def test_retro_exclusion_applies_to_both_models_and_zip_source_is_untouched(tmp_path):
    source = _sample(tmp_path / "source.csv")
    original = source.read_bytes()
    audit = audit_prices(source, stale_weeks=30)
    assert "A" in set(audit.asset)
    target = audit.index[audit.asset.eq("A")][0]
    audit.loc[target, ["action", "reason"]] = ["EXCLUDE_ASSET_RETRO", "Sensitivity"]
    _, selected, events, dropped, label = validate_and_apply(audit, source)
    assert events is None
    assert dropped.asset.tolist() == ["A"]
    assert label == "RETROSPECTIVE_SENSITIVITY"
    assert source.read_bytes() == original
    analysed = tmp_path / "analysed.csv"
    analysed.write_bytes(selected)
    snap = run_snapshot(analysed, tmp_path / "snapshot", window_weeks=(13,26,78,104))
    assert set(snap["bubble_type"].asset) == {"B"}
    cfg = BacktestSettings(start_date="2025-01-10", windows=(13,26,78,104),
                           max_rebalances=2, hold_weeks=4)
    result = run_backtest(analysed,tmp_path/"backtest",cfg)
    assert set(result["states"].asset) == {"B"}
    assert not result["nav"].empty
    assert (tmp_path / "backtest" / "backtest_report.pdf").exists()


def test_documented_block_does_not_delete_prices(tmp_path):
    source = _sample(tmp_path / "source.csv")
    audit = audit_prices(source, stale_weeks=30)
    row = audit.index[audit.asset.eq("A")][0]
    published_at = audit.loc[row, "date"]
    audit.loc[row, "action"] = "BLOCK_ASOF"
    audit.loc[row, "reason"] = "Published issuer notice"
    audit.loc[row, "evidence"] = "https://example.org/notice"
    audit.loc[row, "published_at"] = published_at
    _, selected, ledger, excluded, label = validate_and_apply(audit, source)
    assert selected == source.read_bytes()
    assert excluded.empty
    assert ledger is not None and b"BLOCK" in ledger
    assert label == "DOCUMENTED_ASOF_CLAIM_UNVERIFIED"
