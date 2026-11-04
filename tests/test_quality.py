"""Causal quality checks, independent of external market data."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from lppls_bubble.quality import load_event_register, quality_asof
from lppls_bubble.backtest import BacktestSettings, build_targets_asof


def prices():
    idx = pd.date_range("2024-01-05", periods=110, freq="W-FRI")
    a = np.linspace(100, 120, len(idx))
    b = a.copy()
    b[-8:] = b[-9]
    return pd.DataFrame({"A": a, "B": b}, index=idx)


def test_alerts_are_advisory_not_blocks():
    p = prices()
    p.loc[p.index[-1], "A"] *= 2
    q = quality_asof(p).set_index("asset")
    assert q.loc["A", "extreme_return_alert"]
    assert q.loc["B", "stale_alert"]
    assert not q.event_block.any()
    assert q.history_complete.all()


def test_event_publication_and_release_causal(tmp_path):
    p = prices()
    t = p.index[-1]
    f = tmp_path / "events.csv"
    pd.DataFrame([
        {"asset": "A", "published_at": str((t - pd.Timedelta(weeks=1)).date()), "action": "BLOCK", "source": "verified-url"},
        {"asset": "A", "published_at": str((t + pd.Timedelta(days=1)).date()), "action": "RELEASE", "source": "verified-url-2"},
    ]).to_csv(f, index=False)
    events = load_event_register(f)
    assert quality_asof(p, events).set_index("asset").loc["A", "event_block"]
    future = p.reindex(p.index.append(pd.DatetimeIndex([t + pd.Timedelta(weeks=1)]))).ffill()
    assert not quality_asof(future, events).set_index("asset").loc["A", "event_block"]


def test_future_prices_and_future_events_do_not_change_prior_decision(tmp_path):
    p = prices()
    t = p.index[-2]
    f = tmp_path / "events.csv"
    pd.DataFrame([{"asset": "A", "published_at": str(p.index[-1].date()), "action": "BLOCK", "source": "notice"}]).to_csv(f, index=False)
    events = load_event_register(f)
    earlier = quality_asof(p.loc[:t], events)
    altered = p.copy()
    altered.loc[altered.index > t, "A"] *= 400
    pd.testing.assert_frame_equal(earlier, quality_asof(altered.loc[:t], events))
    assert not earlier.event_block.any()


def test_documented_block_removes_asset_from_both_sleeves():
    p = prices()
    cfg = BacktestSettings(windows=(13, 26, 78, 104))
    state, positions = build_targets_asof(p, cfg, blocked_assets=frozenset({"A"}))
    assert state.set_index("asset").loc["A", "state"] == "INELIGIBLE"
    assert positions.set_index("asset").loc["A", ["w_lo_target", "w_ls_target"]].eq(0).all()


def test_default_policy_is_preserved():
    cfg = BacktestSettings()
    assert cfg.quality_policy == "audit"
    assert cfg.quality_extreme_return == 0.5
    assert cfg.quality_stale_weeks == 8
    assert BacktestSettings().fee_bps == 0


def test_invalid_register_is_rejected(tmp_path):
    f = tmp_path / "events.csv"
    pd.DataFrame([{"asset": "A", "published_at": "2024-04-01", "action": "DELETE", "source": "url"}]).to_csv(f, index=False)
    with pytest.raises(ValueError, match="BLOCK or RELEASE"):
        load_event_register(f)


def test_effective_date_cannot_be_earlier_than_publication(tmp_path):
    f = tmp_path / "events.csv"
    pd.DataFrame([{"asset": "A", "published_at": "2025-01-10", "effective_at": "2024-12-01", "action": "BLOCK", "source": "url"}]).to_csv(f, index=False)
    event = load_event_register(f)
    assert event.active_at.iloc[0] == pd.Timestamp("2025-01-10")
