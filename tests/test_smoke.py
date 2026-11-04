import sys
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from lppls_bubble import run_snapshot
from lppls_bubble.reports import make_html, make_pdf


def csv_fixture(path: Path, weeks=106):
    dates=pd.date_range("2024-01-05",periods=weeks,freq="W-FRI")
    rows=["Start;2024", "End;2026", "Frequency;Weekly", "Name;ActionA;ActionB"]
    for i, date in enumerate(dates):
        a=100*np.exp(0.001*i+0.00001*i*i)
        b=80*np.exp(0.001*i-0.000005*i*i)
        rows.append(f"{date:%d/%m/%Y};{a:.6f};{b:.6f}".replace(".",","))
    path.write_text("\n".join(rows)+"\n",encoding="utf-8")


def test_snapshot_and_reports(tmp_path):
    input_path=tmp_path/"input.csv"
    csv_fixture(input_path)
    data=run_snapshot(input_path,tmp_path/"out",window_weeks=(13,26,104))
    assert len(data["details"])==6
    assert set(data["bubble_type"]["asset"])=={"ActionA","ActionB"}
    assert set(data["details"].signal.unique())<={"UP","DOWN","NONE"}
    assert (tmp_path/"out/heatmap_global.png").read_bytes().startswith(b"\x89PNG")
    html=make_html(data)
    pdf=make_pdf(data)
    assert b"<!doctype html>" in html
    assert pdf.startswith(b"%PDF")
    for fn in ("details_by_scale_all_series.csv", "summary_by_scale_wide.csv", "bubble_type_by_asset.csv", "bubble_summary_by_scale_wide.csv", "portfolio_construction.csv"):
        assert (tmp_path/"out"/fn).exists()


def test_insufficient_history(tmp_path):
    p=tmp_path/"short.csv"
    csv_fixture(p,weeks=25)
    with pytest.raises(ValueError,match="Aucun actif"):
        run_snapshot(p,tmp_path/"out",window_weeks=(104,))
