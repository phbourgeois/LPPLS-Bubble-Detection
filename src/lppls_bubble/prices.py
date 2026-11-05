"""Price input boundary shared by the canonical LPPLS snapshot and backtest.

Supports a standard first-column date CSV or the historical three-metadata-line
Datastream export. A missing observation remains missing: no forward-fill.
"""
from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd


def read_prices(path: str | Path) -> pd.DataFrame:
    """Return dated strictly-positive prices, with preserved missing observations.

    The candidate parser is selected by the fraction of valid dates, not by the
    column name.  Duplicate dates use the latest observation.  Entirely-empty
    assets are excluded; dates are not inferred or filled.  Comparisons must be
    based on a shared weekly price frame, rather than parser-specific rows.
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    best: tuple[float, int, pd.DataFrame, pd.Series] | None = None
    for skip in (0, 3):
        for sep in (';', ',', '\t'):
            try:
                raw = pd.read_csv(path, sep=sep, skiprows=skip, dtype=str,
                                  encoding='utf-8-sig', low_memory=False)
            except (ValueError, UnicodeError, pd.errors.ParserError):
                continue
            if raw.shape[1] < 2 or raw.empty:
                continue
            # Year-first MUST be explicit also for YYYY/MM/DD (pandas with
            # dayfirst=True silently swaps ambiguous month/day, then drops
            # many weekly rows). Never infer locale from the user's machine.
            full = raw.iloc[:, 0].astype('string').str.strip()
            tokens = full.dropna().head(30)
            if len(tokens) and tokens.str.fullmatch(r'\d{4}[-/.]\d{1,2}[-/.]\d{1,2}').mean() >= 0.8:
                normalized = full.str.replace(r'[/\\.]', '-', regex=True)
                dates = pd.to_datetime(normalized, format='%Y-%m-%d', errors='coerce')
            elif len(tokens) and tokens.str.fullmatch(r'\d{1,2}[/.-]\d{1,2}[/.-]\d{4}').mean() >= 0.8:
                normalized = full.str.replace(r'[-\\.]', '/', regex=True)
                dates = pd.to_datetime(normalized, format='%d/%m/%Y', errors='coerce')
            elif len(tokens) and tokens.str.fullmatch(r'\d{8}').mean() >= 0.8:
                dates = pd.to_datetime(full, format='%Y%m%d', errors='coerce')
            else:
                dates = pd.to_datetime(full, dayfirst=True, errors='coerce')
            fraction = float(dates.notna().mean())
            # Prefer parsing the full file over skipping 3 lines when both work.
            if best is None or fraction > best[0]:
                best = (fraction, skip, raw, dates)
    if best is None or best[0] < 0.5:
        raise ValueError('CSV invalide : colonne de dates puis cours d’actifs attendus')
    _, _, raw, dates = best
    if raw.columns[1:].duplicated().any():
        raise ValueError('Des noms d’actifs sont dupliqués dans le fichier CSV')
    data = pd.DataFrame(index=pd.DatetimeIndex(dates, name='date'))
    for j in range(1, raw.shape[1]):
        name = str(raw.columns[j]).strip()
        if not name or name.lower().startswith('unnamed'):
            continue
        s = raw.iloc[:, j].astype('string').str.strip().str.replace(' ', '', regex=False)
        s = s.str.replace('\u00a0', '', regex=False)
        # Decimal comma is preferred when more commas than decimal points occur.
        euro = int(s.str.contains(',', regex=False).sum()) > int(s.str.contains('.', regex=False).sum())
        if euro:
            s = s.str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
        values = pd.to_numeric(s, errors='coerce').to_numpy(dtype=float)
        data[name] = values
    data = data.loc[data.index.notna()].sort_index()
    data = data[~data.index.duplicated(keep='last')]
    data = data.loc[:, ~data.columns.duplicated(keep='first')]
    data = data.where(data > 0).dropna(axis=1, how='all').dropna(axis=0, how='all')
    if data.empty:
        raise ValueError('Aucun cours strictement positif disponible')
    return data


def completed_weekly_prices(daily: pd.DataFrame, *, include_partial: bool = False) -> pd.DataFrame:
    """Friday-ended closes, excluding an unfinished last week by default.

    A partial latest calendar week must never be mislabeled as a completed
    Friday in LPPLS snapshots. Historical empty weeks remain present.
    Holiday-shortened Fridays may require an explicit include_partial override
    after independently checking the exchange calendar.
    """
    if daily.empty:
        raise ValueError("Aucun cours quotidien")
    weekly = daily.resample("W-FRI").last()
    last_obs = daily.index.max()
    final_friday = weekly.index.max()
    if not include_partial and last_obs.normalize() < final_friday.normalize():
        weekly = weekly.iloc[:-1]
    return weekly


def weekly_prices(path: str | Path, *, include_partial: bool = False) -> pd.DataFrame:
    """Weekly closes without filling gaps or labeling partial Fridays as complete."""
    return completed_weekly_prices(read_prices(path), include_partial=include_partial)
