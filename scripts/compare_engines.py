"""Deterministic engine comparison; run locally, no CI credits.

python scripts/compare_engines.py
"""
from __future__ import annotations
import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "research/reproducible_2026_11_04")]
from lppls_bubble.legacy_engine import run_snapshot
from lppls_bubble.backtest import BacktestSettings, run_backtest, load_weekly
import lppls_core as research

OUT = ROOT / "docs/engine_comparison_data"


def datastream(frame, target):
    frame.rename(columns={frame.columns[0]: "Name"}).to_csv(
        target, sep=";", index=False, float_format="%.12f")
    content = target.read_text(encoding="utf-8")
    target.write_text("Start;2022\nEnd;2025\nFrequency;weekly\n" + content, encoding="utf-8")


def synthetic_six():
    n = 156
    rng = np.random.default_rng(20261104)
    t = np.arange(n)
    tau = n + 12 - t
    up = np.exp(5 - .11*tau**.55 + .012*tau**.55*np.cos(8*np.log(tau)+1)
                + rng.normal(0,.005,n))
    down = np.exp(3.8 + .085*tau**.55 + .012*tau**.55*np.cos(9*np.log(tau)+.8)
                  + rng.normal(0,.005,n))
    rw1 = np.exp(4 + np.cumsum(rng.normal(.001,.016,n)))
    rw2 = np.exp(4 + np.cumsum(rng.normal(-.001,.020,n)))
    trend = np.exp(4 + .002*t + rng.normal(0,.008,n))
    flat = np.exp(4 + rng.normal(0,.005,n))
    return pd.DataFrame({"date": pd.date_range("2022-01-07",periods=n,freq="W-FRI").strftime("%d/%m/%Y"),
                         "BUBBLE_UP":up,"BUBBLE_DOWN":down,"RW_UP":rw1,
                         "RW_DOWN":rw2,"TREND":trend,"FLAT":flat})


def compare_frame(frame, folder, label):
    plain = folder / (label + ".csv")
    datastream_path = folder / (label + "_datastream.csv")
    frame.to_csv(plain, sep=";", index=False, float_format="%.12f")
    datastream(frame, datastream_path)
    weekly = load_weekly(plain)
    pd.testing.assert_frame_equal(weekly,
        research.to_weekly(research.load_prices(plain)), check_exact=True)
    with contextlib.redirect_stdout(io.StringIO()):
        a = run_snapshot(datastream_path, folder/(label+"_current"))
        b = research.write_snapshot_outputs(weekly, folder/(label+"_research"), grid="full")
    k = ["asset","window_weeks"]
    x = a["details"].merge(b["details_by_scale_all_series.csv"], on=k, suffixes=("_current","_research"))
    ca = a["bubble_type"].set_index("asset").bubble_multiscale_state
    cb = b["bubble_type_by_asset.csv"].set_index("asset").bubble_multiscale_state
    assert len(x) == len(a["details"]) == len(b["details_by_scale_all_series.csv"])
    return {
        "assets": len(weekly.columns), "weeks": len(weekly),
        "fits": len(x),
        "same_B": int(np.isclose(x.B_current,x.B_research,atol=1e-10).sum()),
        "same_r2": int(np.isclose(x.r2_current,x.r2_research,atol=1e-10).sum()),
        "same_signals": int((x.signal_current==x.signal_research).sum()),
        "same_states": int((ca==cb).sum())
    }, weekly, datastream_path


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    source = ROOT/"research/reproducible_2026_11_04/examples/synthetic_example.csv"
    with tempfile.TemporaryDirectory() as work:
        folder = Path(work)
        example, _, _ = compare_frame(pd.read_csv(source,sep=";"),folder,"example")
        controlled, weekly, ds = compare_frame(synthetic_six(),folder,"controlled")
        config = BacktestSettings(start_date="2024-02-02",max_rebalances=4,hold_weeks=4,fee_bps=15)
        with contextlib.redirect_stdout(io.StringIO()):
            a = run_backtest(ds,folder/"bt_current",config)
            research.run_backtest(weekly,folder/"bt_research",
                start_date="2024-02-02",rebalance_weeks=4,costs_bps=15,grid="tiny",max_rebalances=4)
        nav0 = a["nav"]
        nav1 = pd.read_csv(folder/"bt_research/backtest_nav_weekly.csv")
        assert nav0.date.tolist() == nav1.date.tolist()
        ncomp = pd.DataFrame({"date":nav0.date,"current_long_only":nav0.nav_long_only,
            "research_long_only":nav1.nav_long_only,
            "current_long_short":nav0.nav_long_short,
            "research_long_short":nav1.nav_long_short})
        ncomp.to_csv(OUT/"nav_comparison.csv",index=False)
        rng=np.random.default_rng(23111)
        randoms=[]
        for i in range(40):
            ret=rng.normal(0,.018,104)
            if i%2==0: ret+=.0005
            fit=research.fit_lppls(4+np.cumsum(ret),grid="full")
            valid,signal=research.classify_fit(fit)
            randoms.append({"series":i,"valid":bool(valid),"signal":signal,"r2":float(fit["r2"])})
        pd.DataFrame(randoms).to_csv(OUT/"random_walks.csv",index=False)
        summary={"example":example,"controlled":controlled,
            "nav_current_long_only":float(nav0.nav_long_only.iloc[-1]),
            "nav_research_long_only":float(nav1.nav_long_only.iloc[-1]),
            "nav_current_long_short":float(nav0.nav_long_short.iloc[-1]),
            "nav_research_long_short":float(nav1.nav_long_short.iloc[-1]),
            "random_walk_valid_count":sum(r["valid"] for r in randoms),
            "note":"Engineering audit on synthetic prices, not a predictive LPPLS validation"}
        (OUT/"summary.json").write_text(json.dumps(summary,indent=2)+"\n")
    print(json.dumps(summary,indent=2))


if __name__ == "__main__":
    main()
