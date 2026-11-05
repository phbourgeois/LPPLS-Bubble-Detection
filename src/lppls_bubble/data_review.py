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

ACTIONS = ("REVIEW", "KEEP", "EXCLUDE_BACKTEST_RETRO", "EXCLUDE_ASSET_RETRO", "BLOCK_ASOF")
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



def backtest_audit_window(
    source: str | Path, start_date: str, hold_weeks: int = 4,
    max_rebalances: int | None = None, lookback_weeks: int = 104,
) -> tuple[pd.Timestamp, pd.Timestamp, int]:
    """Exactly match the existing backtest decision dates WITHOUT running LPPLS.

    The final date is the last actual NAV date (possibly earlier than the
    latest quote if max_rebalances limits the run).
    """
    if hold_weeks < 1 or lookback_weeks < 1 or (
        max_rebalances is not None and max_rebalances < 1
    ):
        raise ValueError("Paramètres de calendrier de backtest invalides")
    weekly = completed_weekly_prices(read_prices(source))
    candidates = weekly.index[weekly.index >= pd.Timestamp(start_date)]
    decisions = []
    for date in candidates[::hold_weeks]:
        pos = weekly.index.get_loc(date)
        if pos >= lookback_weeks - 1 and pos < len(weekly) - 1:
            decisions.append(date)
        if max_rebalances is not None and len(decisions) >= max_rebalances:
            break
    if not decisions:
        raise ValueError(
            "Aucune date de décision admissible sur cette période de backtest "
            "(historique de 104 semaines ou durée future insuffisants)."
        )
    end_pos = min(
        len(weekly)-1,
        weekly.index.get_loc(decisions[-1]) + hold_weeks,
    )
    return decisions[0], weekly.index[end_pos], len(decisions)


def critical_in_backtest(
    audit: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp
) -> pd.DataFrame:
    """Only flag critical observations inside the *real* backtest NAV window."""
    if audit.empty:
        return audit.copy()
    dates = pd.to_datetime(audit["date"], errors="coerce")
    mask = (audit["severity"].eq("CRITICAL")
            & dates.ge(pd.Timestamp(start)) & dates.le(pd.Timestamp(end)))
    return audit.loc[mask].copy().reset_index(drop=True)


def critical_by_title(merged: pd.DataFrame) -> pd.DataFrame:
    """One selectable row per asset; all individual anomalies remain inspectable."""
    columns = ["asset", "n_critical", "first_date", "last_date",
               "max_abs_return_pct", "exclude_backtest", "reason"]
    rows = []
    for asset, group in merged.groupby("asset", sort=True):
        prior_exclusion = group.loc[group.action.isin(
            ("EXCLUDE_BACKTEST_RETRO", "EXCLUDE_ASSET_RETRO")
        )]
        selected = not prior_exclusion.empty
        reason = (str(prior_exclusion.reason.iloc[0])
                  if selected else "")
        rows.append({
            "asset": asset, "n_critical": len(group),
            "first_date": group.date.min(), "last_date": group.date.max(),
            "max_abs_return_pct": float(group.return_pct.abs().max()),
            "exclude_backtest": selected, "reason": reason,
        })
    return pd.DataFrame(rows, columns=columns)


def apply_title_decisions(
    merged: pd.DataFrame, title_choices: pd.DataFrame
) -> pd.DataFrame:
    """Checkbox excludes entire title, not any individual price observation.

    Each critical event still has its own record and fingerprint, so legacy
    decision registers can be re-imported without replacing historical quotes.
    """
    result = merged.copy()
    if result.empty:
        return result
    if title_choices.asset.duplicated().any():
        raise ValueError("Un même titre figure plusieurs fois dans le tableau")
    if set(title_choices.asset) != set(result.asset):
        raise ValueError("Le tableau des titres ne couvre pas les anomalies critiques")
    choice = title_choices.set_index("asset")
    excluded = set(choice.index[choice.exclude_backtest.astype(bool)])
    # No invisible per-event exclusions when the user unchecks a title.
    result["action"] = "REVIEW"
    result["reason"] = ""
    result["evidence"] = ""
    result["published_at"] = ""
    for asset in excluded:
        reason = str(choice.at[asset, "reason"]).strip()
        if not reason:
            reason = "Exclusion rétrospective du titre du backtest après revue des anomalies critiques"
        mask = result.asset.eq(asset)
        result.loc[mask, "action"] = "EXCLUDE_BACKTEST_RETRO"
        result.loc[mask, "reason"] = reason
        if "compatibility" in result:
            # A freshly ticked asset is an explicit new user decision on the
            # observed prices, not automatic reuse of an old changed fingerprint.
            result.loc[mask & result.compatibility.eq("CHANGED_PRICE_REVIEW"),
                       "compatibility"] = "REVALIDATED"
    return result


def classify_uploaded_registry(payload: bytes) -> str:
    """Distinguish reusable review decisions from dated BLOCK/RELEASE ledgers.

    The two CSV formats are not interchangeable. A legacy-uploaded review
    decision file can be routed back to stage one instead of failing in the
    historical backtest.
    """
    if not payload or not payload.strip():
        raise ValueError("Le registre CSV est vide")
    try:
        header = set(pd.read_csv(BytesIO(payload), nrows=0, encoding="utf-8-sig").columns)
    except (pd.errors.ParserError, UnicodeError, ValueError) as exc:
        raise ValueError("Impossible de lire les colonnes du registre CSV") from exc
    decision_columns = {"event_id", "asset", "date", "frequency",
                        "kind", "price_fingerprint", "action"}
    event_columns = {"asset", "published_at", "action", "source"}
    if decision_columns.issubset(header):
        return "decisions"
    if event_columns.issubset(header):
        return "events"
    raise ValueError(
        "Format de registre non reconnu : utiliser data_quality_decisions.csv "
        "pour les décisions de l'étape 1, ou asset,published_at,action,source "
        "pour les événements de blocage."
    )


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
                       ) -> tuple[pd.DataFrame, bytes, bytes, bytes | None, pd.DataFrame, str]:
    """Produce same-history research data and optional as-of events.

    EXCLUDE_BACKTEST_RETRO removes the stock from the backtest universe only,
    keeping it available to LPPLS snapshot diagnostics. EXCLUDE_ASSET_RETRO
    removes it from both snapshot and backtest; both label the run RETROSPECTIVE_SENSITIVITY.
    BLOCK_ASOF preserves historical
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
        if asof.evidence.fillna("").astype(str).str.strip().isin(("", "nan", "None", "<NA>")).any():
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
    global_excluded = sorted(set(df.loc[df.action.eq("EXCLUDE_ASSET_RETRO"), "asset"]))
    backtest_only = sorted(set(df.loc[df.action.eq("EXCLUDE_BACKTEST_RETRO"), "asset"])
                           - set(global_excluded))
    all_backtest_excluded = sorted(set(global_excluded) | set(backtest_only))
    prices = read_prices(source)
    unknown = set(all_backtest_excluded) - set(prices.columns)
    if unknown:
        raise ValueError("Titres inconnus : " + ", ".join(sorted(unknown)))
    if len(global_excluded) >= len(prices.columns) or len(all_backtest_excluded) >= len(prices.columns):
        raise ValueError("L'exclusion retirerait tous les titres de l'une des analyses")

    def without_assets(excluded: list[str]) -> bytes:
        if not excluded:
            return Path(source).read_bytes()
        kept = prices.drop(columns=excluded)
        csv_frame = kept.copy()
        csv_frame.insert(0, "Date", kept.index.strftime("%Y-%m-%d"))
        return csv_frame.to_csv(index=False, sep=";").encode("utf-8")

    snapshot_payload = without_assets(global_excluded)
    backtest_payload = without_assets(all_backtest_excluded)
    exclusions = pd.DataFrame(
        [{"asset": asset, "scope": "SNAPSHOT_AND_BACKTEST",
          "classification": "RETROSPECTIVE_SENSITIVITY"} for asset in global_excluded]
        + [{"asset": asset, "scope": "BACKTEST_ONLY",
            "classification": "RETROSPECTIVE_SENSITIVITY"} for asset in backtest_only],
        columns=["asset", "scope", "classification"],
    )
    study_type = "RETROSPECTIVE_SENSITIVITY" if len(all_backtest_excluded) else (
        "DOCUMENTED_ASOF_CLAIM_UNVERIFIED" if len(asof) else "UNMODIFIED_PRICES_AUDIT")
    return df, snapshot_payload, backtest_payload, event_payload, exclusions, study_type
