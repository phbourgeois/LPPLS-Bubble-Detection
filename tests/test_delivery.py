"""Tests du paquet unique de livrables téléchargeable depuis Streamlit."""
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import sys
from zipfile import BadZipFile, ZipFile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from lppls_bubble.delivery import build_delivery_zip


def read_archive(data):
    with ZipFile(BytesIO(data)) as z:
        return {name: z.read(name) for name in z.namelist()}


def test_all_outputs_are_preserved_with_manifest():
    snapshot = {"details.csv": b"asset,signal\nA,UP\n", "rapport_lppls.pdf": b"%PDF-1.4"}
    backtest = {"backtest_nav_weekly.csv": b"date,nav_long_only\n", "backtest_nav_plot.png": b"\x89PNG"}
    statistical = {"lppls_significance.csv": b"asset,q\n"}
    source = b"Date;A\n2025-01-01;10\n"
    payload = build_delivery_zip(
        snapshot, backtest, statistical,
        source_csv=source,
        source_name="SBF_components.csv",
        event_register_csv=b"asset,published_at,action,source\nA,2025-01-01,BLOCK,notice\n",
        parameters={"windows": [13, 26, 104], "fees_bps": 0},
        run_status={"lppls": "success", "backtest": "success", "statistical": "success"},
    )
    items = read_archive(payload)
    for path, expected in {
        "lppls/details.csv": snapshot["details.csv"],
        "lppls/rapport_lppls.pdf": snapshot["rapport_lppls.pdf"],
        "backtest/backtest_nav_weekly.csv": backtest["backtest_nav_weekly.csv"],
        "backtest/backtest_nav_plot.png": backtest["backtest_nav_plot.png"],
        "statistique/lppls_significance.csv": statistical["lppls_significance.csv"],
        "donnees/source.csv": source,
        "donnees/quality_events.csv": b"asset,published_at,action,source\nA,2025-01-01,BLOCK,notice\n",
    }.items():
        assert items[path] == expected
    assert "README.md" in items
    metadata = json.loads(items["manifest.json"])
    assert metadata["file_count"] == 7
    assert metadata["source_filename"] == "SBF_components.csv"
    assert metadata["parameters"]["windows"] == [13, 26, 104]
    assert metadata["run_status"]["backtest"] == "success"
    for file in metadata["files"]:
        assert sha256(items[file["path"]]).hexdigest() == file["sha256"]
        assert len(items[file["path"]]) == file["size_bytes"]


def test_snapshot_alone_and_failed_backtest_are_explicit():
    payload = build_delivery_zip(
        {"portfolio.csv": b"x"}, {},
        source_csv=b"input",
        run_status={"lppls": "success", "backtest": "error: missing weekly quote"},
    )
    files = read_archive(payload)
    assert "lppls/portfolio.csv" in files
    assert not any(p.startswith("backtest/") for p in files)
    assert json.loads(files["manifest.json"])["run_status"]["backtest"].startswith("error:")


def test_zip_is_deterministic_and_not_corrupt():
    args = ({"z.csv": b"data", "a.html": b"<p>ok</p>"},)
    one = build_delivery_zip(*args, source_csv=b"csv", parameters={"periods": 24})
    two = build_delivery_zip(*args, source_csv=b"csv", parameters={"periods": 24})
    assert one == two
    assert ZipFile(BytesIO(one)).testzip() is None


@pytest.mark.parametrize("name", ["../escape.csv", "directory/file.csv", "a\\b.csv", ".", ""])
def test_rejects_unsafe_names(name):
    with pytest.raises(ValueError, match="sécurisé"):
        build_delivery_zip({name: b"bad"})


def test_rejects_non_binary_outputs_or_missing_snapshot():
    with pytest.raises(ValueError, match="au moins un"):
        build_delivery_zip({})
    with pytest.raises(TypeError, match="bytes"):
        build_delivery_zip({"a.csv": "not bytes"})


def test_review_files_are_preserved_in_unique_zip():
    audit = {
        "data_quality_anomalies.csv": b"event_id,asset,date\\n1,A,2024-01-05\\n",
        "data_quality_decisions.csv": b"event_id,asset,date,action\\n1,A,2024-01-05,KEEP\\n",
        "analyzed_prices.csv": b"Date;A\\n2024-01-05;100\\n",
    }
    data = build_delivery_zip(
        {"portfolio_construction.csv": b"asset,weight\\nA,1\\n"},
        audit_exports=audit, source_csv=b"original source bytes",
        parameters={"data_review_study_type": "RETROSPECTIVE_SENSITIVITY"},
    )
    files = read_archive(data)
    for name, value in audit.items():
        assert files["audit/" + name] == value
    assert files["donnees/source.csv"] == b"original source bytes"
    manifest = json.loads(files["manifest.json"])
    assert manifest["file_count"] == 5
    assert manifest["parameters"]["data_review_study_type"] == "RETROSPECTIVE_SENSITIVITY"
