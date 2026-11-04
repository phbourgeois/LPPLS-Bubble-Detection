"""Backtest exploratoire LPPLS, refactorisé du notebook with_backtest_named.

Règle anti-anticipation : l'éligibilité, le fit et les poids à t dépendent
uniquement des observations jusqu'à t. Une repondération s'effectue à la
clôture de la date t, pour des rendements à compter de t+1.
Cette implémentation n'est pas une reproduction numérique certifiée du notebook
historique (qui filtre sur les quatre semaines FUTURES).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pandas as pd

from .legacy_engine import DEFAULT_WINDOWS
from .quality import load_event_register, quality_asof


@dataclass(frozen=True)
class BacktestSettings:
    start_date: str = "2024-02-01"
    hold_weeks: int = 4
    lookback_weeks: int = 104
    windows: tuple[int, ...] = DEFAULT_WINDOWS
    max_rebalances: int = 24
    fee_bps: float = 0.0
    quality_policy: str = "audit"  # audit or block_documented; no statistical quarantine
    quality_stale_weeks: int = 8
    quality_extreme_return: float = 0.5

    def validate(self):
        if self.hold_weeks < 1 or self.max_rebalances < 1:
            raise ValueError("hold_weeks et max_rebalances doivent etre >= 1")
        if not self.windows or min(self.windows) < 5:
            raise ValueError("Au moins une fenetre d'au moins cinq semaines est requise")
        if self.lookback_weeks < max(self.windows):
            raise ValueError("lookback_weeks doit couvrir la plus grande fenetre LPPLS")
        if self.fee_bps < 0:
            raise ValueError("fee_bps doit etre positif")
        if self.quality_policy not in ("audit", "block_documented"):
            raise ValueError("quality_policy doit etre audit ou block_documented")
        if self.quality_stale_weeks < 2 or self.quality_extreme_return <= 0:
            raise ValueError("Seuils de qualite invalides")


def load_weekly(input_csv: str | Path) -> pd.DataFrame:
    """Lecture partagee avec le snapshot : CSV standard ou Datastream."""
    from .prices import weekly_prices
    return weekly_prices(input_csv)


def fit_tiny(log_prices: np.ndarray) -> dict:
    """Grille reduite exactement derivee de l'annexe du notebook named."""
    y = np.asarray(log_prices, dtype=float)
    n = len(y)
    if n < 5 or not np.isfinite(y).all():
        return {"success": False, "n": n}
    t = np.arange(n, dtype=float)
    ahead_max = min(1.5 * n, max(6, n))
    best = None
    for m in (0.2, 0.5, 0.8):
        for omega in (7.0, 9.5, 12.0):
            for ahead in np.linspace(1.0, ahead_max, 3):
                tau = ((n - 1) + ahead) - t
                x1 = tau ** m
                a = omega * np.log(tau)
                X = np.column_stack((np.ones(n), x1, x1 * np.cos(a), x1 * np.sin(a)))
                beta, *_ = np.linalg.lstsq(X, y, rcond=None)
                resid = X @ beta - y
                sse = float(np.dot(resid, resid))
                if best is None or sse < best["sse"]:
                    sst = float(np.sum((y - y.mean()) ** 2))
                    r2 = 1 - sse / sst if sst > 0 else np.nan
                    best = {"success": True, "B": float(beta[1]), "m": m, "omega": omega,
                            "tc": (n - 1) + ahead, "r2": r2, "sse": sse, "n": n}
    return best or {"success": False, "n": n}


def classify(fit: dict) -> tuple[bool, str]:
    if not fit.get("success"):
        return False, "NONE"
    n = fit["n"]
    valid = (0.1 <= fit["m"] <= 0.9 and 6 <= fit["omega"] <= 13 and
             (n - 1) < fit["tc"] <= (n - 1) + 1.5 * n and
             np.isfinite(fit["r2"]) and fit["r2"] >= 0.2)
    return bool(valid), ("UP" if fit["B"] < 0 else "DOWN") if valid else "NONE"


def _aggregated_signal(signals: dict[int, str], windows: tuple[int, ...]) -> str:
    values = [signals[w] for w in windows if w in signals and signals[w] in ("UP", "DOWN")]
    if not values:
        return "NONE"
    up = values.count("UP")
    down = values.count("DOWN")
    return "UP" if up > down else "DOWN" if down > up else "MIXED"


def build_targets_asof(past: pd.DataFrame, config: BacktestSettings,
                       blocked_assets: frozenset[str] = frozenset()) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Retourne les signaux et les poids à partir du passé seulement."""
    eligible = past.columns[past.tail(config.lookback_weeks).notna().all()].tolist()
    # all() seul n'est pas suffisant si la serie commence recemment.
    if len(past) < config.lookback_weeks:
        eligible = []
    if blocked_assets:
        eligible = [asset for asset in eligible if asset not in blocked_assets]
    states = pd.DataFrame({"asset": list(past.columns), "state": "INELIGIBLE", "priority_score": 0.0})
    weights = pd.DataFrame({"asset": list(past.columns), "w_lo_target": 0.0, "w_ls_target": 0.0})
    if not eligible:
        return states, weights
    rows = []
    for asset in eligible:
        s = past[asset].to_numpy(dtype=float)
        signals = {}
        valid_count = 0
        tc_valid = []
        for window in config.windows:
            fit = fit_tiny(np.log(s[-window:]))
            valid, signal = classify(fit)
            signals[window] = signal
            valid_count += int(valid)
            if valid:
                tc_valid.append(fit["tc"] - (fit["n"] - 1))
        short = _aggregated_signal(signals, (13, 26))
        long = _aggregated_signal(signals, (78, 104))
        if short in ("UP", "DOWN") and short == long:
            state = "COHERENT_MULTI_" + short
        elif short == "NONE" and long == "NONE":
            state = "NO_BUBBLE"
        else:
            state = "MIXED_SCALES"
        tc_med = float(np.median(tc_valid)) if tc_valid else np.nan
        penalty = 1.0 if np.isnan(tc_med) else 1 + max(0, tc_med) / 10
        bonus = 2.0 if state.startswith("COHERENT_MULTI_") else (0.5 if state == "MIXED_SCALES" else 0)
        priority = 100 * (bonus + valid_count / len(config.windows)) / penalty
        rows.append({"asset": asset, "state": state, "priority_score": priority})
    bt = pd.DataFrame(rows).set_index("asset")
    states = states.set_index("asset")
    states.loc[bt.index, ["state", "priority_score"]] = bt[["state", "priority_score"]]
    rets = past[eligible].pct_change(fill_method=None)
    recent_returns = rets.tail(52)
    # pandas Series.std has no min_count kwarg: mask by count separately.
    vol_52 = recent_returns.std(skipna=True).where(recent_returns.count() >= 13).replace(0, np.nan)
    inv_vol = 1 / vol_52
    inv_vol = inv_vol.replace([np.inf, -np.inf], np.nan).fillna(0).clip(lower=0)
    longs = bt.index[bt["state"] != "COHERENT_MULTI_UP"]
    shorts = bt.index[bt["state"] == "COHERENT_MULTI_UP"]
    long_raw = inv_vol.reindex(longs).fillna(0)
    short_raw = bt.loc[shorts, "priority_score"].clip(lower=0)
    has_short = short_raw.sum() > 0
    long_gross = 0.5 if has_short else 1.0
    if long_raw.sum() > 0:
        long_normal = long_raw / long_raw.sum()
        weights.loc[weights.asset.isin(longs), "w_lo_target"] = weights.loc[weights.asset.isin(longs), "asset"].map(long_normal).fillna(0).to_numpy()
        weights.loc[weights.asset.isin(longs), "w_ls_target"] = (weights.loc[weights.asset.isin(longs), "asset"].map(long_normal).fillna(0) * long_gross).to_numpy()
    if has_short:
        short_normal = short_raw / short_raw.sum()
        weights.loc[weights.asset.isin(shorts), "w_ls_target"] = (weights.loc[weights.asset.isin(shorts), "asset"].map(short_normal).fillna(0) * -0.5).to_numpy()
    return states.reset_index(), weights


def _metrics(nav: pd.DataFrame, turnover: pd.DataFrame, config: BacktestSettings, n_rebalances: int) -> pd.DataFrame:
    result = {"start_rebalance": str(turnover.date.iloc[0]), "end_week": str(nav.date.iloc[-1]),
              "num_rebalances": n_rebalances, "fees_bps": config.fee_bps}
    for key, ret, to_col in (("long_only", "ret_long_only", "turnover_long_only"),
                             ("long_short", "ret_long_short", "turnover_long_short")):
        s = nav["nav_" + key].astype(float)
        r = nav[ret].iloc[1:].astype(float)
        sd = r.std(ddof=1)
        result["total_return_" + key] = float(s.iloc[-1] / 1.0 - 1)
        result["max_drawdown_" + key] = float((1 - s / s.cummax()).max())
        result["sharpe_" + key + "_weekly"] = float(r.mean() / sd * np.sqrt(52)) if len(r) > 1 and sd > 0 else np.nan
        result["turnover_mean_" + key] = float(turnover[to_col].mean())
    return pd.DataFrame([result])


def run_backtest(input_csv: str | Path, output_dir: str | Path,
                 config: BacktestSettings | None = None,
                 quality_events_csv: str | Path | None = None) -> dict:
    """Backtest causale hebdomadaire ; le notebook historique reste une archive distincte."""
    config = config or BacktestSettings()
    config.validate()
    if config.quality_policy == "block_documented" and quality_events_csv is None:
        raise ValueError("block_documented requiert un registre CSV d'evenements dates")
    events = load_event_register(quality_events_csv)
    weekly = load_weekly(input_csv)
    outdir = Path(output_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    candidates = weekly.index[weekly.index >= pd.Timestamp(config.start_date)]
    decision_dates = []
    for t in candidates[::config.hold_weeks]:
        pos = weekly.index.get_loc(t)
        if pos >= config.lookback_weeks - 1 and pos + config.hold_weeks < len(weekly):
            decision_dates.append(t)
        if len(decision_dates) == config.max_rebalances:
            break
    if not decision_dates:
        raise ValueError("Aucune date de rebalancement avec un historique suffisant et un horizon complet")
    assets = list(weekly.columns)
    decisions = {}
    all_states = []
    lo_rows = []
    ls_rows = []
    quality_rows = []
    for t in decision_dates:
        past = weekly.loc[:t]
        quality = quality_asof(past, events, lookback_weeks=config.lookback_weeks,
                               stale_weeks=config.quality_stale_weeks,
                               extreme_return=config.quality_extreme_return)
        blocked = (frozenset(quality.loc[quality.event_block, "asset"])
                   if config.quality_policy == "block_documented" else frozenset())
        quality["block_applied"] = quality.asset.isin(blocked)
        quality["quality_policy"] = config.quality_policy
        quality_rows.append(quality)
        states, targets = build_targets_asof(past, config, blocked_assets=blocked)
        decisions[t] = targets.set_index("asset")
        all_states.append(states.assign(date=t.date().isoformat()))
        lo_rows.append(targets[["asset", "w_lo_target"]].rename(columns={"w_lo_target": "weight"}).assign(date=t.date().isoformat()))
        ls_rows.append(targets[["asset", "w_ls_target"]].rename(columns={"w_ls_target": "weight"}).assign(date=t.date().isoformat()))
    start_pos = weekly.index.get_loc(decision_dates[0])
    end_pos = weekly.index.get_loc(decision_dates[-1]) + config.hold_weeks
    dates = weekly.index[start_pos:end_pos+1]
    returns = weekly.pct_change(fill_method=None)
    nav_lo = nav_ls = 1.0
    wlo = pd.Series(0.0, index=assets)
    wls = pd.Series(0.0, index=assets)
    nav_rows = []
    turn_rows = []
    last_date = None
    for i, t in enumerate(dates):
        before_lo, before_ls = nav_lo, nav_ls
        ret_lo = ret_ls = 0.0
        if i > 0:
            r = returns.loc[t].reindex(assets)
            exposed = (wlo.abs() > 1e-12) | (wls.abs() > 1e-12)
            if r[exposed].isna().any():
                missing = r[exposed & r.isna()].index.tolist()
                raise ValueError("Cours futur manquant sur position detenue (aucune imputation) : " + ", ".join(missing[:10]))
            r = r.fillna(0.0)
            ret_lo = float((wlo * r).sum())
            ret_ls = float((wls * r).sum())
            if 1 + ret_lo <= 0 or 1 + ret_ls <= 0:
                raise ValueError("Valeur de portefeuille <= 0 : levier / rendements invalides")
            nav_lo *= 1 + ret_lo
            nav_ls *= 1 + ret_ls
            # Derive des poids a prix courant avant rebalancement.
            wlo = (wlo * (1 + r)) / (1 + ret_lo)
            wls = (wls * (1 + r)) / (1 + ret_ls)
        if t in decisions:
            target_lo = decisions[t]["w_lo_target"].reindex(assets).fillna(0)
            target_ls = decisions[t]["w_ls_target"].reindex(assets).fillna(0)
            trade_lo = float((target_lo - wlo).abs().sum())
            trade_ls = float((target_ls - wls).abs().sum())
            to_lo = 0.5 * trade_lo
            to_ls = 0.5 * trade_ls
            nav_lo *= 1 - trade_lo * config.fee_bps / 10000
            nav_ls *= 1 - trade_ls * config.fee_bps / 10000
            if nav_lo <= 0 or nav_ls <= 0:
                raise ValueError("Frais >= NAV : parametres invalides")
            turn_rows.append({"date": t.date().isoformat(), "turnover_long_only": to_lo,
                              "turnover_long_short": to_ls})
            wlo = target_lo
            wls = target_ls
            last_date = t
        # Net returns reflect trade fees at rebalance (including the initial setup fee).
        net_lo = nav_lo / before_lo - 1
        net_ls = nav_ls / before_ls - 1
        nav_rows.append({"date": t.date().isoformat(), "nav_long_only": nav_lo,
                         "nav_long_short": nav_ls, "ret_long_only": net_lo,
                         "ret_long_short": net_ls,
                         "active_rebalance_date": last_date.date().isoformat()})
    nav = pd.DataFrame(nav_rows)
    turnover = pd.DataFrame(turn_rows)
    states = pd.concat(all_states, ignore_index=True)
    quality_history = pd.concat(quality_rows, ignore_index=True)
    weighting_policy = pd.DataFrame([
        {"strategy": "long_only", "sleeve": "long", "weight_method": "inverse_weekly_volatility", "lookback_weeks": 52},
        {"strategy": "long_short", "sleeve": "long", "weight_method": "inverse_weekly_volatility", "lookback_weeks": 52},
        {"strategy": "long_short", "sleeve": "short", "weight_method": "lppls_priority_score", "lookback_weeks": np.nan},
    ])
    weights_lo = pd.concat(lo_rows, ignore_index=True)[["date", "asset", "weight"]]
    weights_ls = pd.concat(ls_rows, ignore_index=True)[["date", "asset", "weight"]]
    metrics = _metrics(nav, turnover, config, len(decision_dates))
    csv_outputs = {
        "backtest_portfolios_long_only_weights.csv": weights_lo,
        "backtest_portfolios_long_short_weights.csv": weights_ls,
        "backtest_portfolios_long_only_weights_wide.csv": weights_lo.pivot(index="date", columns="asset", values="weight"),
        "backtest_portfolios_long_short_weights_wide.csv": weights_ls.pivot(index="date", columns="asset", values="weight"),
        "backtest_states.csv": states,
        "backtest_quality_asof.csv": quality_history,
        "backtest_weighting_policy.csv": weighting_policy,
        "backtest_turnover.csv": turnover,
        "backtest_nav_weekly.csv": nav,
        "backtest_summary_metrics.csv": metrics,
    }
    for name, table in csv_outputs.items():
        table.to_csv(outdir / name, index=name.endswith("_wide.csv"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(pd.to_datetime(nav.date), nav.nav_long_only, label="Long-only")
    ax.plot(pd.to_datetime(nav.date), nav.nav_long_short, label="Long/short")
    ax.set(xlabel="Date", ylabel="NAV", title="Backtest exploratoire sans anticipation (signaux à t)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(outdir / "backtest_nav_plot.png", dpi=140)
    plt.close(fig)
    return {"weekly": weekly, "nav": nav, "metrics": metrics, "weights_lo": weights_lo,
            "weights_ls": weights_ls, "states": states, "turnover": turnover,
            "quality_history": quality_history, "weighting_policy": weighting_policy,
            "output_dir": outdir, "settings": config}
