"""Shared CSV reader for the canonical LPPLS engine.

Supports a standard date-first CSV and historical Datastream exports with three
metadata lines. Missing prices must not be silently forward-filled.
"""
from __future__ import annotations

from pathlib import Path
import pandas as pd


def read_prices(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    best = None
    for skip in (0, 3):
        for sep in (";", ",", "\t"):
            try:
                raw = pd.read_csv(path, sep=sep, skiprows=skip, dtype=str,
                                  encoding="utf-8-sig", low_memory=False)
            except (ValueError, UnicodeError, pd.errors.ParserError):
                continue
            if raw.shape[1] < 2 or raw.empty:
                continue
            dates = pd.to_datetime(raw.iloc[:, 0], dayfirst=True, errors="coerce")
            fraction = float(dates.notna().mean())
            if best is None or fraction > best[0]:
                best = (fraction, raw, dates)
    if best is None or best[0] < 0.5:
        raise ValueError("CSV invalide : premiere colonne dates, suivantes cours.")
    _, raw, dates = best
    if raw.columns[1:].duplicated().any():
        raise ValueError("Noms d'actifs dupliques dans le CSV")
    data = pd.DataFrame(index=pd.DatetimeIndex(dates, name="date"))
    for j in range(1, raw.shape[1]):
        name = str(raw.columns[j]).strip()
        if not name or name.lower().startswith("unnamed"):
            continue
        s = raw.iloc[:, j].astype("string").str.strip().str.replace(" ", "", regex=False)
        s = s.str.replace("\u00a0", "", regex=False)
        euro = int(s.str.contains(",", regex=False).sum()) > int(s.str.contains(".", regex=False).sum())
        if euro:
            s = s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
        data[name] = pd.to_numeric(s, errors="coerce").to_numpy(dtype=float)
    data = data.loc[data.index.notna()].sort_index()
    data = data[~data.index.duplicated(keep="last")]
    data = data.loc[:, ~data.columns.duplicated(keep="first")]
    data = data.where(data > 0).dropna(axis=1, how="all").dropna(axis=0, how="all")
    if data.empty:
        raise ValueError("Aucun cours positif disponible")
    return data


def weekly_prices(path: str | Path) -> pd.DataFrame:
    # Preserve fully empty calendar weeks to avoid shrinking LPPLS lookbacks.
    return read_prices(path).resample("W-FRI").last()
