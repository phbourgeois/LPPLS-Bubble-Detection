"""Controlled comparison: original LPPLS, equal-weight benchmark, mixed-scale variants.

No additional LPPLS fits, no look-ahead, no change in the portfolio weighting
formulas. All targets are built from the exact same as-of states and prices.
The common replay checks the original strategy NAV to guard against changes
in accounting, dates, drift and trading fees.
"""
from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd


SCENARIOS = (
    "original_long_only", "original_long_short",
    "benchmark_equal_weight", "mixed_long_only", "mixed_long_short",
)
DESCRIPTIONS = {
    "original_long_only": "Historical original long-only, inverse 52-week volatility",
    "original_long_short": "Historical original L/S, long inverse-vol, short LPPLS score",
    "benchmark_equal_weight": "Equal weight all 104-week eligible assets; same rebalance dates",
    "mixed_long_only": "Original long sleeve, excluding only MIXED short-DOWN/long-UP",
    "mixed_long_short": "Original long sleeve minus bearish MIXED; same shorts plus bearish MIXED",
}


def _mixed_targets(states: pd.DataFrame, past: pd.DataFrame) -> dict[str, pd.Series]:
    assets = past.columns
    state = states.set_index("asset").reindex(assets)
    eligible = state.state.ne("INELIGIBLE") & state.state.notna()
    up_short_down_long = (
        eligible & state.state.eq("MIXED_SCALES")
        & state.bubble_short_term.eq("UP") & state.bubble_long_term.eq("DOWN")
    )
    down_short_up_long = (
        eligible & state.state.eq("MIXED_SCALES")
        & state.bubble_short_term.eq("DOWN") & state.bubble_long_term.eq("UP")
    )
    # Keep all original long candidates, including ambiguous MIXED states.
    # Change ONLY the short-DOWN/long-UP directional mixed category:
    # remove it from longs, and move it to shorts in the mixed L/S scenario.
    # short-UP/long-DOWN was already long in the original strategy.
    long_ok = eligible & ~state.state.eq("COHERENT_MULTI_UP") & ~down_short_up_long
    short_ok = eligible & (
        state.state.eq("COHERENT_MULTI_UP") | down_short_up_long
    )
    recent = past.pct_change(fill_method=None).tail(52)
    sd = recent.std(skipna=True).where(recent.count() >= 13).replace(0, np.nan)
    inverse_vol = (1 / sd).replace([np.inf, -np.inf], np.nan).fillna(0).clip(lower=0)
    lw = inverse_vol.where(long_ok, 0).fillna(0)
    if lw.sum() > 0:
        lw = lw / lw.sum()
    scores = state.priority_score.where(short_ok, 0).fillna(0).clip(lower=0)
    sw = scores / scores.sum() if scores.sum() > 0 else scores
    benchmark = eligible.astype(float)
    benchmark = benchmark / benchmark.sum() if benchmark.sum() > 0 else benchmark
    mixed_ls = lw * (0.5 if scores.sum() > 0 else 1.0) - 0.5 * sw
    return {
        "benchmark_equal_weight": benchmark.astype(float),
        "mixed_long_only": lw.astype(float),
        "mixed_long_short": mixed_ls.astype(float),
    }


def _replay(weekly: pd.DataFrame, dates: pd.DatetimeIndex,
            target_by_date: dict[pd.Timestamp, dict[str, pd.Series]],
            fee_bps: float) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    assets = weekly.columns
    returns = weekly.pct_change(fill_method=None)
    nav = {s: 1.0 for s in SCENARIOS}
    weights = {s: pd.Series(0.0, index=assets, dtype=float) for s in SCENARIOS}
    nav_rows, exposure_rows, trades = [], [], []
    for i, date in enumerate(dates):
        line = {"date": date.date().isoformat()}
        for strategy in SCENARIOS:
            prev = nav[strategy]
            old = weights[strategy]
            r = returns.loc[date].reindex(assets) if i else pd.Series(0.0, index=assets)
            exposed = old.abs() > 1e-12
            if r[exposed].isna().any():
                bad = r[exposed & r.isna()].index.tolist()
                raise ValueError(f"Missing held security return for {strategy} at {date}: {bad[:4]}")
            r = r.fillna(0.0)
            gross = float((old * r).sum()) if i else 0.0
            if 1 + gross <= 0:
                raise ValueError(f"Portfolio value nonpositive for {strategy} on {date}")
            nav[strategy] *= 1 + gross
            drift = old * (1 + r) / (1 + gross) if i else old.copy()
            absolute_turnover = 0.0
            if date in target_by_date:
                target = target_by_date[date][strategy].reindex(assets).fillna(0)
                absolute_turnover = float((target - drift).abs().sum())
                nav[strategy] *= (1 - absolute_turnover * fee_bps / 10000)
                if nav[strategy] <= 0:
                    raise ValueError(f"Trading fees exhausted NAV for {strategy}")
                weights[strategy] = target
                trades.append({
                    "date": date.date().isoformat(), "strategy": strategy,
                    "turnover_half_sum": absolute_turnover / 2,
                    "absolute_traded_weight": absolute_turnover,
                })
            else:
                weights[strategy] = drift
            line["nav_" + strategy] = nav[strategy]
            line["ret_" + strategy] = nav[strategy] / prev - 1
            exposure_rows.append({
                "date": date.date().isoformat(), "strategy": strategy,
                "long_exposure": float(old.clip(lower=0).sum()),
                "short_exposure": float((-old.clip(upper=0)).sum()),
                "net_exposure": float(old.sum()),
                "max_abs_asset_weight": float(old.abs().max()),
                "gross_asset_return": gross,
                "trading_cost_return": float(nav[strategy] / prev - 1 - gross),
                "turnover_absolute": absolute_turnover,
            })
        nav_rows.append(line)
    return pd.DataFrame(nav_rows), pd.DataFrame(exposure_rows), pd.DataFrame(trades)


def _performance(nav: pd.DataFrame, exposures: pd.DataFrame,
                 trades: pd.DataFrame) -> pd.DataFrame:
    rows = []
    n = len(nav) - 1
    for strategy in SCENARIOS:
        values = nav["nav_" + strategy].astype(float)
        weekly = nav["ret_" + strategy].iloc[1:].astype(float)
        sd = weekly.std(ddof=1)
        trade = trades.loc[trades.strategy == strategy, "turnover_half_sum"]
        e = exposures.loc[exposures.strategy == strategy]
        bench_ret = nav["ret_benchmark_equal_weight"].iloc[1:].astype(float)
        active_ret = weekly - bench_ret
        active_sd = active_ret.std(ddof=1)
        annual_excess = (
            float(values.iloc[-1]**(52/n) - nav["nav_benchmark_equal_weight"].iloc[-1]**(52/n))
            if n and values.iloc[-1] > 0 else np.nan
        )
        rows.append({
            "annualized_return_gap_vs_equal_weight": annual_excess,
            "annualized_tracking_error_vs_equal_weight":
                float(active_sd*np.sqrt(52)) if n > 1 else np.nan,
            "information_ratio_vs_equal_weight":
                float(active_ret.mean()/active_sd*np.sqrt(52))
                if n > 1 and active_sd > 0 else np.nan,
            "strategy": strategy, "description": DESCRIPTIONS[strategy],
            "total_return": float(values.iloc[-1] - 1),
            "annualized_return": float(values.iloc[-1] ** (52/n) - 1) if n and values.iloc[-1] > 0 else np.nan,
            "annualized_volatility": float(sd * np.sqrt(52)) if n > 1 else np.nan,
            "sharpe_rf_zero": float(weekly.mean()/sd*np.sqrt(52)) if n > 1 and sd > 0 else np.nan,
            "max_drawdown": float((1 - values / values.cummax()).max()),
            "turnover_mean_half_sum": float(trade.mean()) if len(trade) else np.nan,
            "max_abs_asset_weight": float(e.max_abs_asset_weight.max()),
            "final_nav": float(values.iloc[-1]),
        })
    return pd.DataFrame(rows)


def run_strategy_comparison(
    weekly: pd.DataFrame, original_nav: pd.DataFrame,
    states: pd.DataFrame, original_long_weights: pd.DataFrame,
    original_ls_weights: pd.DataFrame, fee_bps: float, output_dir: str | Path,
) -> dict:
    """Compute apples-to-apples scenarios and assert exact original NAV reproduction."""
    outdir = Path(output_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    dates = pd.DatetimeIndex(pd.to_datetime(original_nav.date))
    all_dates = pd.DatetimeIndex(sorted(pd.to_datetime(states.date.unique())))
    original_lo = original_long_weights.copy()
    original_ls = original_ls_weights.copy()
    by_date: dict[pd.Timestamp, dict[str, pd.Series]] = {}
    target_records = []
    signal_records = []
    for date in all_dates:
        date_text = date.date().isoformat()
        decision = states.loc[states.date == date_text]
        past = weekly.loc[:date]
        mixed = _mixed_targets(decision, past)
        lo = original_lo.loc[original_lo.date == date_text].set_index("asset").weight
        ls = original_ls.loc[original_ls.date == date_text].set_index("asset").weight
        all_targets = {"original_long_only": lo, "original_long_short": ls, **mixed}
        by_date[date] = all_targets
        for scenario, target in all_targets.items():
            for asset, weight in target.items():
                target_records.append({
                    "date": date_text, "strategy": scenario, "asset": asset,
                    "target_weight": float(weight),
                })
        counts = decision.groupby(
            ["state", "bubble_short_term", "bubble_long_term"],
            dropna=False,
        ).size()
        for (state, short, long), count in counts.items():
            signal_records.append({
                "date": date_text, "state": state, "short_signal": short,
                "long_signal": long, "n_assets": int(count),
            })
    replay, exposures, trades = _replay(weekly, dates, by_date, fee_bps)
    # Crucial safeguard: unchanged originals must give the exact reference NAV,
    # including the first transaction and 4-week between-decision drift.
    for old, new in (("nav_long_only", "nav_original_long_only"),
                     ("nav_long_short", "nav_original_long_short")):
        maximum = float(np.max(np.abs(replay[new].to_numpy() - original_nav[old].to_numpy())))
        if maximum > 1e-10:
            raise AssertionError(f"Original NAV replay mismatch for {old}: {maximum}")
    performance = _performance(replay, exposures, trades)
    benchmark = replay["nav_benchmark_equal_weight"]
    delta = pd.DataFrame({"date": replay.date})
    for scenario in ("original_long_only", "original_long_short",
                     "mixed_long_only", "mixed_long_short"):
        delta["nav_gap_vs_equal_weight_" + scenario] = replay["nav_" + scenario] - benchmark
        delta["weekly_return_gap_vs_equal_weight_" + scenario] = (
            replay["ret_" + scenario] - replay["ret_benchmark_equal_weight"]
        )
    target_frame = pd.DataFrame(target_records)
    calendar_years = pd.to_datetime(replay.date).dt.year
    annual_records = []
    for strategy in SCENARIOS:
        for year in sorted(calendar_years.unique()):
            mask = calendar_years.eq(year)
            # First NAV row is a rebalance with no preceding weekly holding.
            y_rets = replay.loc[mask, "ret_" + strategy].astype(float)
            if len(y_rets):
                annual_records.append({
                    "year": int(year), "strategy": strategy,
                    "weeks": len(y_rets),
                    "compounded_return": float(np.prod(1 + y_rets) - 1),
                })
    annual = pd.DataFrame(annual_records)
    outputs = {
        "backtest_comparison_nav.csv": replay,
        "backtest_comparison_metrics.csv": performance,
        "backtest_comparison_targets.csv": target_frame,
        "backtest_comparison_exposures.csv": exposures,
        "backtest_comparison_turnover.csv": trades,
        "backtest_comparison_gaps.csv": delta,
        "backtest_comparison_signal_counts.csv": pd.DataFrame(signal_records),
        "backtest_comparison_annual.csv": annual,
    }
    for name, frame in outputs.items():
        frame.to_csv(outdir / name, index=False)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(10.5, 5.5))
    for strategy in SCENARIOS:
        ax.plot(pd.to_datetime(replay.date), replay["nav_" + strategy],
                label=strategy.replace("_", " "), linewidth=1.5)
    ax.set(title="LPPLS: same dates, universe, fees and weighting formulas",
           xlabel="Date", ylabel="NAV (initial = 1)")
    ax.legend(fontsize=8)
    ax.grid(alpha=.25)
    fig.tight_layout()
    fig.savefig(outdir / "backtest_comparison_nav.png", dpi=150)
    plt.close(fig)
    return {
        "nav": replay, "metrics": performance, "targets": target_frame,
        "exposures": exposures, "turnover": trades, "gaps": delta,
        "annual": annual,
        "output_dir": outdir,
    }
