"""Point-in-time data-review registry and retrospective sensitivity safeguards."""
import hashlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from lppls_bubble.data_review import (
    ACTIONS, FIELDS, audit_prices, read_decisions,
    merge_previous_decisions, validate_and_apply, classify_uploaded_registry,
)
from lppls_bubble.prices import read_prices


def sample_csv(path: Path) -> Path:
    # Standard source format: deliberately include a real, extreme weekly jump.
    dates = pd.date_range("2024-01-05", periods=17, freq="W-FRI")
    a = np.full(len(dates), 100.0)
    a[10] = 600.0
    b = np.linspace(80.0, 96.0, len(dates))
    pd.DataFrame({"Date": dates.strftime("%Y-%m-%d"), "A": a, "B": b}).to_csv(
        path, sep=";", index=False
    )
    return path


def test_audit_prices_flag_extremes_without_replacing_quotes(tmp_path):
    original = sample_csv(tmp_path / "source.csv")
    source_before = original.read_bytes()
    rows = audit_prices(original, stale_weeks=30)
    assert (rows.asset == "A").any()
    assert "EXTREME_RETURN" in rows.kind.values
    assert (rows.return_pct > 400).any()
    assert original.read_bytes() == source_before


def test_registry_roundtrip_and_changes_are_not_automatically_reapplied(tmp_path):
    source = sample_csv(tmp_path / "source.csv")
    rows = audit_prices(source, stale_weeks=30)
    n = rows.index[0]
    rows.loc[n, "action"] = "EXCLUDE_ASSET_RETRO"
    rows.loc[n, "reason"] = "Research sensitivity only"
    register = read_decisions(rows[FIELDS].to_csv(index=False).encode())
    assert "event_id" in register
    current, orphans = merge_previous_decisions(audit_prices(source, stale_weeks=30), register)
    assert orphans.empty
    assert current.loc[n, "action"] == "EXCLUDE_ASSET_RETRO"
    first_id = rows.loc[n, "event_id"]
    # Same anomaly identity, revised numeric price.
    updated = source.read_text().replace("600.0", "700.0")
    source.write_text(updated)
    revised = audit_prices(source, stale_weeks=30)
    changed, orphan = merge_previous_decisions(revised, register)
    row = changed[changed.event_id.eq(first_id)]
    if len(row):
        assert row.iloc[0].compatibility == "CHANGED_PRICE_REVIEW"
        assert row.iloc[0].action == "REVIEW"
    else:
        assert first_id in set(orphan.event_id)


def test_retro_exclusion_does_not_modify_original(tmp_path):
    source = sample_csv(tmp_path / "source.csv")
    original = source.read_bytes()
    reviewed = audit_prices(source, stale_weeks=30)
    reviewed.loc[reviewed.index[0], ["action", "reason"]] = ["EXCLUDE_ASSET_RETRO", "Sensitivity"]
    _, filtered, filtered_bt, events, excluded, study = validate_and_apply(reviewed, source)
    assert events is None
    assert study == "RETROSPECTIVE_SENSITIVITY"
    assert excluded.asset.tolist() == ["A"]
    assert read_prices(source).shape[1] == 2
    selected_csv = tmp_path / "filtered.csv"
    selected_csv.write_bytes(filtered)
    assert read_prices(selected_csv).columns.tolist() == ["B"]
    assert filtered_bt == filtered
    assert source.read_bytes() == original


def test_unmodified_audit_preserves_original_bytes(tmp_path):
    source = sample_csv(tmp_path / "source.csv")
    rows = audit_prices(source, stale_weeks=30)
    _, analyzed, analyzed_bt, events, excluded, study = validate_and_apply(rows, source)
    assert analyzed == source.read_bytes()
    assert analyzed_bt == analyzed
    assert events is None
    assert excluded.empty
    assert study == "UNMODIFIED_PRICES_AUDIT"


def test_asof_requires_reason_evidence_and_valid_publication(tmp_path):
    source = sample_csv(tmp_path / "source.csv")
    rows = audit_prices(source, stale_weeks=30)
    i = rows.index[0]
    rows.loc[i, "action"] = "BLOCK_ASOF"
    with pytest.raises(ValueError, match="justification"):
        validate_and_apply(rows, source)
    rows.loc[i, "reason"] = "Official issuer notice"
    with pytest.raises(ValueError, match="source"):
        validate_and_apply(rows, source)
    rows.loc[i, "evidence"] = "https://example.org/notice"
    rows.loc[i, "published_at"] = "2023-01-01"
    with pytest.raises(ValueError, match="précéder"):
        validate_and_apply(rows, source)
    rows.loc[i, "published_at"] = "2024-04-30"
    _, data, data_bt, ledger, _, study = validate_and_apply(rows, source)
    assert data == source.read_bytes()
    assert data_bt == data
    assert ledger is not None
    assert study == "DOCUMENTED_ASOF_CLAIM_UNVERIFIED"
    records = pd.read_csv(__import__("io").BytesIO(ledger))
    assert records.action.iloc[0] == "BLOCK"
    assert records.published_at.iloc[0] == "2024-04-30"


def test_reject_duplicate_id_or_unsupported_action(tmp_path):
    source = sample_csv(tmp_path / "source.csv")
    rows = audit_prices(source, stale_weeks=30)
    duplicated = pd.concat([rows, rows.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="dupliqu"):
        validate_and_apply(duplicated, source)
    rows.loc[rows.index[0], "action"] = "DROP_SINGLE_PRICE"
    with pytest.raises(ValueError, match="invalides"):
        validate_and_apply(rows, source)


def test_missing_internal_weeks_are_reported_as_one_episode(tmp_path):
    dates = pd.date_range("2024-01-05", periods=16, freq="W-FRI")
    a = np.linspace(100.0, 115.0, len(dates))
    a[6:8] = np.nan
    source = tmp_path / "missing.csv"
    pd.DataFrame({"Date": dates.strftime("%Y-%m-%d"), "A": a,
                  "B": np.linspace(90.0, 100.0, len(dates))}).to_csv(
                      source, sep=";", index=False)
    flags = audit_prices(source, stale_weeks=30)
    gaps = flags.loc[flags.kind == "INTERNAL_MISSING_WEEK_RUN"]
    assert len(gaps) == 1
    assert gaps.gap_weeks.iloc[0] == 2
    assert gaps.date.iloc[0] == "2024-02-16"


def test_backtest_only_checkbox_preserves_snapshot_universe(tmp_path):
    source = sample_csv(tmp_path / "source.csv")
    original = source.read_bytes()
    rows = audit_prices(source, stale_weeks=30)
    rows.loc[rows.index[0], ["action", "reason"]] = [
        "EXCLUDE_BACKTEST_RETRO", "Exclude from retrospective backtest only"
    ]
    _, snapshot_csv, backtest_csv, events, exclusions, label = validate_and_apply(rows, source)
    assert snapshot_csv == original
    assert events is None
    assert exclusions.to_dict("records") == [
        {"asset": "A", "scope": "BACKTEST_ONLY",
         "classification": "RETROSPECTIVE_SENSITIVITY"}
    ]
    bt_path = tmp_path / "backtest.csv"
    bt_path.write_bytes(backtest_csv)
    assert set(read_prices(bt_path).columns) == {"B"}
    assert label == "RETROSPECTIVE_SENSITIVITY"


def test_uploaded_registry_formats_are_recognised_and_not_interchangeable():
    decisions = (
        b"event_id,asset,date,frequency,kind,price_fingerprint,action,reason\\n"
        b"1,ATOS,2024-12-06,WEEKLY,EXTREME_RETURN,abc,REVIEW,\\n"
    )
    events = (
        b"asset,published_at,action,source\\n"
        b"ATOS,2024-12-06,BLOCK,https://example.org/notice\\n"
    )
    assert classify_uploaded_registry(decisions) == "decisions"
    assert classify_uploaded_registry(events) == "events"
    with pytest.raises(ValueError, match="Format de registre non reconnu"):
        classify_uploaded_registry(b"asset,action\\nATOS,BLOCK\\n")
    with pytest.raises(ValueError, match="vide"):
        classify_uploaded_registry(b"")
