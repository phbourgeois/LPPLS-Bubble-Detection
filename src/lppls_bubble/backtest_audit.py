"""Weekly point-in-time discontinuity monitoring. Never change price returns.

Alerts are investigation flags, not proof of missing corporate-action adjustments.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def weekly_price_alerts(
    weekly: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp,
    extreme_return: float = 0.5, stale_weeks: int = 8,
) -> pd.DataFrame:
    """Flag jumps and unchanged quotes on every observed week, not only rebalance dates."""
    if extreme_return <= 0 or stale_weeks < 2:
        raise ValueError("Seuils de controle qualite invalides")
    if weekly.empty:
        raise ValueError("Aucune donnee hebdomadaire")
    rets = weekly.pct_change(fill_method=None)
    rows = []
    for asset in weekly.columns:
        streak = 0
        previous = np.nan
        for date, price in weekly[asset].items():
            if pd.notna(price) and pd.notna(previous) and price == previous:
                streak += 1
            else:
                streak = 0
            previous = price
            if date < start or date > end:
                continue
            r = rets.at[date, asset]
            extreme = bool(pd.notna(r) and abs(r) >= extreme_return)
            stale = streak >= stale_weeks - 1
            if not (extreme or stale):
                continue
            severe = bool(extreme and (r >= 3.0 or r <= -0.9))
            rows.append({
                "date": date.date().isoformat(), "asset": asset,
                "observed_weekly_return": float(r) if pd.notna(r) else np.nan,
                "unchanged_consecutive_weeks": int(streak + 1),
                "extreme_return_alert": extreme, "stale_price_alert": stale,
                "severity": "CRITICAL_REVIEW" if severe else "REVIEW",
                "qualification": "UNVERIFIED_MARKET_OR_CORPORATE_EVENT",
                "action": "MANUAL_ADJUSTED_PRICE_CHECK",
            })
    columns = ["date", "asset", "observed_weekly_return", "unchanged_consecutive_weeks",
               "extreme_return_alert", "stale_price_alert", "severity", "qualification", "action"]
    return pd.DataFrame(rows, columns=columns).sort_values(["date", "asset"]).reset_index(drop=True)


def check_weekly_contributions(nav: pd.DataFrame, recon: pd.DataFrame, tolerance: float = 1e-10) -> None:
    """Audit whether gross asset contributions and costs reproduce net NAV returns."""
    for strategy, ret in (("long_only", "ret_long_only"), ("long_short", "ret_long_short")):
        subset = recon.loc[recon.strategy == strategy].set_index("date")
        actual = nav.set_index("date")[ret]
        if set(actual.index) != set(subset.index):
            raise AssertionError(f"Dates de rapprochement manquantes : {strategy}")
        diff = (actual - subset["net_return"]).abs()
        if (diff > tolerance).any():
            raise AssertionError(f"Rapprochement NAV incorrect : {strategy}, max={diff.max()}")
