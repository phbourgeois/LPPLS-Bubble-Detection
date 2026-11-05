"""Reusable two-stage price audit and explicit research decisions.

An abnormal return is a flag, not a demonstrated error. Retrospective
asset removal is a sensitivity study; point-in-time blocking requires a
documented publication date and never erases an already-realised return.
"""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd

from .prices import read_prices, completed_weekly_prices

ACTIONS = ("REVIEW", "KEEP", "EXCLUDE_ASSET_RETRO", "BLOCK_ASOF")
FIELDS = ["event_id", "asset", "date", "frequency", "kind", "previous_price",
          "observed_price", "return_pct", "gap_weeks", "severity", "price_fingerprint",
          "action", "reason", "evidence", "published_at"]


def _fingerprint(asset: str, date: str, frequency: str, kind: str,
                 previous: float, observed: float) -> tuple[str, str]:
    identity = "|".join((asset, date, frequency, kind))
    event_id = sha256(identity.encode("utf-8")).hexdigest()[:24]
    context = f"{identity}|{previous:.15g}|{observed:.15g}"
    return event_id, sha256(context.encode("utf-8")).hexdigest()


def _append(rows: list[dict], asset: str, date: pd.Timestamp, frequency: str,
            kind: str, prev: float, now: float, ret: float, severity: str, gap_weeks: int = 0) -> None:
    day = date.date().isoformat()
    event_id, fingerprint = _fingerprint(asset, day, frequency, kind, prev, now)
    rows.append({"event_id": event_id, "asset": asset, "date": day,
                 "frequency": frequency, "kind": kind,
                 "previous_price": float(prev), "observed_price": float(now),
                 "return_pct": float(100 * ret), "gap_weeks": int(gap_weeks), "severity": severity,
                 "price_fingerprint": fingerprint, "action": "REVIEW", "reason": "",
                 "evidence": "", "published_at": ""})


def audit_prices(path: str | Path, *, weekly_threshold: float = .50,
                 daily_threshold: float = .50, stale_weeks: int = 8) -> pd.DataFrame:
    """Audit the full available history without modifying a single quote."""
    if weekly_threshold <= 0 or daily_threshold <= 0 or stale_weeks < 2:
        raise ValueError("Invalid audit thresholds")
    daily = read_prices(path)
    weekly = completed_weekly_prices(daily)
    rows: list[dict] = []
    for frequency, frame, threshold in (("DAILY", daily, daily_threshold),
                                        ("WEEKLY", weekly, weekly_threshold)):
        pct = frame.pct_change(fill_method=None)
        for asset in frame:
            values, returns = frame[asset], pct[asset]
            jumps = returns.loc[returns.notna() & (returns.abs() >= threshold)]
            for date, ret in jumps.items():
                pos = frame.index.get_loc(date)
                prev, cur = values.iloc[pos - 1], values.iloc[pos]
                severity = "CRITICAL" if ret >= 3 or ret <= -.9 else "REVIEW"
                _append(rows, asset, date, frequency, "EXTREME_RETURN",
                        prev, cur, ret, severity)
            if frequency == "WEEKLY":
                streak = 1
                for i in range(1, len(values)):
                    a, b = values.iloc[i-1], values.iloc[i]
                    streak = streak+1 if pd.notna(a) and pd.notna(b) and a == b else 1
                    if streak == stale_weeks:
                        _append(rows, asset, frame.index[i], frequency, "STALE_PRICE",
                                float(a), float(b), 0.0, "REVIEW")
                # Missing quotes INSIDE a listed series, grouped by contiguous run.
                # Pre-listing missing values are not anomalies.
                active = values.dropna()
                if len(active) >= 2:
                    interior = values.loc[active.index[0]:active.index[-1]]
                    gap_start = None
                    gap_count = 0
                    for date, current in interior.items():
                        if pd.isna(current):
                            if gap_start is None:
                                gap_start = date
                            gap_count += 1
                        elif gap_start is not None:
                            previous_quote = interior.loc[:gap_start].iloc[:-1].dropna().iloc[-1]
                            _append(rows, asset, gap_start, "WEEKLY",
                                    "INTERNAL_MISSING_WEEK_RUN", float(previous_quote),
                                    float("nan"), float("nan"), "REVIEW",
                                    gap_weeks=gap_count)
                            gap_start = None
                            gap_count = 0
    audit = pd.DataFrame(rows, columns=FIELDS)
    if audit.empty:
        return audit
    return audit.sort_values(["severity", "date", "asset", "frequency"],
                             kind="stable").reset_index(drop=True)


def read_decisions(payload: bytes) -> pd.DataFrame:
    """Reject incompatible, duplicated or ambiguous previous CSV decisions."""
    df = pd.read_csv(BytesIO(payload), dtype=str, keep_default_na=False, encoding="utf-8-sig")
    required = {"event_id", "asset", "date", "frequency", "kind", "price_fingerprint", "action"}
    if not required.issubset(df.columns):
        raise ValueError("Registre incompatible : colonnes absentes : " +
                         ", ".join(sorted(required-set(df.columns))))
    if df.event_id.duplicated().any():
        raise ValueError("Registre ambigu : event_id dupliqué")
    if not df.action.isin(ACTIONS).all():
        raise ValueError("Registre : action inconnue")
    for col in FIELDS:
        if col not in df.columns:
            df[col] = ""
    return df[FIELDS]


def merge_previous_decisions(audit: pd.DataFrame, previous: pd.DataFrame | None
                            ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Reapply only exact observations; changed/vanished events stay inactive."""
    current = audit.copy()
    current["compatibility"] = "NEW"
    if previous is None or previous.empty:
        return current, pd.DataFrame(columns=["event_id", "asset", "date", "status"])
    prior = previous.set_index("event_id")
    matched = set()
    for i, row in current.iterrows():
        key = row.event_id
        if key not in prior.index:
            continue
        old = prior.loc[key]
        matched.add(key)
        if str(row.price_fingerprint) != str(old.price_fingerprint):
            current.at[i, "compatibility"] = "CHANGED_PRICE_REVIEW"
            continue
        current.at[i, "compatibility"] = "MATCH"
        for col in ("action", "reason", "evidence", "published_at"):
            current.at[i, col] = old[col]
    orphan = previous.loc[~previous.event_id.isin(matched),
                          ["event_id", "asset", "date"]].copy()
    orphan["status"] = "NOT_DETECTED_IN_CURRENT_SOURCE"
    return current, orphan


def validate_and_apply(audit_decisions: pd.DataFrame, source: str | Path
                       ) -> tuple[pd.DataFrame, bytes, bytes | None, pd.DataFrame, str]:
    """Produce same-history research data and optional as-of events.

    EXCLUDE_ASSET_RETRO removes a full stock from snapshot AND backtest and
    labels the run RETROSPECTIVE_SENSITIVITY. BLOCK_ASOF preserves historical
    prices but blocks future targets after its documented publication date.
    Never delete an isolated quote, forward-fill or zero an extreme return.
    """
    df = audit_decisions.copy()
    if not set(FIELDS).issubset(df.columns):
        raise ValueError("Colonnes manquantes dans les décisions")
    if df.event_id.duplicated().any() or not df.action.isin(ACTIONS).all():
        raise ValueError("Décisions invalides ou dupliquées")
    resolved = df.action.ne("REVIEW")
    if (resolved & df.reason.fillna("").astype(str).str.strip().eq("")).any():
        raise ValueError("Une justification est obligatoire pour toute décision autre que REVIEW")
    if "compatibility" in df:
        stale = df.compatibility.eq("CHANGED_PRICE_REVIEW")
        if (stale & df.action.ne("REVIEW")).any():
            raise ValueError("Une observation modifiée ne peut pas réutiliser une décision antérieure")
    asof = df.loc[df.action.eq("BLOCK_ASOF")].copy()
    if len(asof):
        if (asof.evidence.astype(str).str.strip() == "").any():
            raise ValueError("BLOCK_ASOF exige une source documentée")
        published = pd.to_datetime(asof.published_at, errors="coerce")
        if published.isna().any():
            raise ValueError("BLOCK_ASOF exige une date de publication valide")
        observation = pd.to_datetime(asof.date, errors="coerce")
        if observation.isna().any() or (published.reset_index(drop=True) < observation.reset_index(drop=True)).any():
            raise ValueError("La date de publication ne peut pas précéder la date de l\'anomalie")
        events = pd.DataFrame({"asset": asof.asset,
                               "published_at": published.dt.date.astype(str),
                               "action": "BLOCK", "source": asof.evidence})
        event_payload = events.drop_duplicates().to_csv(index=False).encode("utf-8")
    else:
        event_payload = None
    retro = sorted(set(df.loc[df.action.eq("EXCLUDE_ASSET_RETRO"), "asset"]))
    prices = read_prices(source)
    invalid = set(retro) - set(prices.columns)
    if invalid:
        raise ValueError("Titres inconnus : " + ", ".join(sorted(invalid)))
    if len(retro) >= len(prices.columns):
        raise ValueError("L'exclusion retirerait tous les titres")
    if retro:
        kept = prices.drop(columns=retro)
        csv_frame = kept.copy()
        csv_frame.insert(0, "Date", kept.index.strftime("%Y-%m-%d"))
        analysis_payload = csv_frame.to_csv(index=False, sep=";").encode("utf-8")
    else:
        # Avoid even round-trip numerical changes when no exclusion is approved.
        analysis_payload = Path(source).read_bytes()
    exclusions = pd.DataFrame({"asset": retro, "scope": "FULL_HISTORY",
                               "classification": "RETROSPECTIVE_SENSITIVITY"})
    study_type = "RETROSPECTIVE_SENSITIVITY" if retro else (
        "DOCUMENTED_ASOF_CLAIM_UNVERIFIED" if len(asof) else "UNMODIFIED_PRICES_AUDIT")
    return df, analysis_payload, event_payload, exclusions, study_type
