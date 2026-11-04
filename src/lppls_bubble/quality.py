"""Point-in-time price-quality diagnostics for exploratory LPPLS backtests.

Alerts never silently rewrite historical prices or remove legitimate market jumps.
Corporate-action blocks require a user-supplied, dated evidence register.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

EVENT_COLUMNS = ("asset", "published_at", "action", "source")
ACTIONS = ("BLOCK", "RELEASE")


def load_event_register(source: str | Path | None) -> pd.DataFrame:
    """Load an explicit publication-time ledger; no built-in hindsight exclusions."""
    if source is None:
        return pd.DataFrame(columns=[*EVENT_COLUMNS, "effective_at", "active_at"])
    df = pd.read_csv(source, dtype={"asset": str, "action": str, "source": str})
    missing = set(EVENT_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError("Event register missing required columns: " + ", ".join(sorted(missing)))
    df = df.copy()
    for col in ("asset", "action", "source"):
        df[col] = df[col].fillna("").astype(str).str.strip()
    df["action"] = df["action"].str.upper()
    if (df["asset"] == "").any() or (df["source"] == "").any():
        raise ValueError("Event register requires non-empty asset and source")
    if not df["action"].isin(ACTIONS).all():
        raise ValueError("Event register action must be BLOCK or RELEASE")
    df["published_at"] = pd.to_datetime(df["published_at"], errors="coerce", utc=True).dt.tz_localize(None).dt.normalize()
    if df["published_at"].isna().any():
        raise ValueError("Event register contains invalid published_at dates")
    if "effective_at" not in df:
        df["effective_at"] = df["published_at"]
    else:
        effective = pd.to_datetime(df["effective_at"], errors="coerce", utc=True).dt.tz_localize(None).dt.normalize()
        df["effective_at"] = effective.fillna(df["published_at"])
    df["active_at"] = df[["published_at", "effective_at"]].max(axis=1)
    return df.sort_values(["active_at", "published_at"], kind="stable").reset_index(drop=True)


def quality_asof(past: pd.DataFrame, events: pd.DataFrame | None = None,
                 lookback_weeks: int = 104, stale_weeks: int = 8,
                 extreme_return: float = 0.5) -> pd.DataFrame:
    """Assess only historical prices and events actually published by the as-of date.

    The alert is advisory, while event_block is separately enforceable.
    """
    if past.empty:
        raise ValueError("quality_asof requires at least one historical row")
    if stale_weeks < 2 or lookback_weeks < 2 or extreme_return <= 0:
        raise ValueError("Invalid quality thresholds")
    today = pd.Timestamp(past.index[-1]).normalize()
    known = (events if events is not None else pd.DataFrame(columns=EVENT_COLUMNS)).copy()
    if not known.empty:
        required = {"asset", "published_at", "active_at", "action", "source"}
        if not required.issubset(known.columns):
            raise ValueError("Pass an event register from load_event_register")
        known = known.loc[(known.published_at <= today) & (known.active_at <= today)]
    rows = []
    for asset in past.columns:
        s = past[asset]
        complete = len(s) >= lookback_weeks and s.tail(lookback_weeks).notna().all() and (s.tail(lookback_weeks) > 0).all()
        last = s.iloc[-1]
        streak = 0
        if pd.notna(last):
            for x in s.iloc[::-1]:
                if pd.notna(x) and x == last:
                    streak += 1
                else:
                    break
        r = float(s.iloc[-1] / s.iloc[-2] - 1) if len(s) > 1 and pd.notna(s.iloc[-2]) and pd.notna(last) and s.iloc[-2] > 0 else np.nan
        jump = np.isfinite(r) and abs(r) >= extreme_return
        stale = streak >= stale_weeks
        asset_events = known.loc[known.asset == asset].sort_values(["active_at", "published_at"], kind="stable") if not known.empty else known
        blocked = bool(len(asset_events) and asset_events.iloc[-1]["action"] == "BLOCK")
        evidence = str(asset_events.iloc[-1]["source"]) if blocked else ""
        reasons = []
        if not complete:
            reasons.append("INCOMPLETE_HISTORY")
        if stale:
            reasons.append("STALE_PRICE")
        if jump:
            reasons.append("EXTREME_RETURN")
        if blocked:
            reasons.append("DOCUMENTED_EVENT")
        rows.append({
            "date": today.date().isoformat(), "asset": asset,
            "history_complete": bool(complete),
            "stale_weeks": int(streak), "last_return": r,
            "stale_alert": bool(stale), "extreme_return_alert": bool(jump),
            "event_block": blocked, "event_source": evidence,
            "quality_alert": ";".join(reasons) if reasons else "OK",
        })
    return pd.DataFrame(rows)
