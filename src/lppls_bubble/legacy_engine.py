"""Migration V0 du notebook Colab du 27-02-2026.

Le coeur du calcul est issu *verbatim* des cellules [4,6,8,10,12,14,16,18,20].
La fonction ci-dessous encapsule leur execution dans un contexte portable.
Il ne s'agit PAS du notebook historique de backtest (qui reste a retrouver).
"""
from pathlib import Path

DEFAULT_WINDOWS = (13, 26, 39, 52, 65, 78, 104)


def run_snapshot(input_csv: str | Path, output_dir: str | Path, window_weeks=DEFAULT_WINDOWS) -> dict:
    INPUT_CSV = Path(input_csv)
    OUTPUT_DIR = Path(output_dir)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    WINDOW_WEEKS = sorted(set(int(w) for w in window_weeks))
    if not WINDOW_WEEKS or min(WINDOW_WEEKS) < 5:
        raise ValueError("Selectionner une fenetre d'au moins 5 semaines")
    if not INPUT_CSV.exists():
        raise FileNotFoundError(INPUT_CSV)
    DETAILS_OUT = OUTPUT_DIR / "details_by_scale_all_series.csv"
    SUMMARY_OUT = OUTPUT_DIR / "summary_by_scale_wide.csv"
    BUBBLETYPE_OUT = OUTPUT_DIR / "bubble_type_by_asset.csv"
    BUBBLE_WIDE_OUT = OUTPUT_DIR / "bubble_summary_by_scale_wide.csv"
    PORTFOLIO_OUT = OUTPUT_DIR / "portfolio_construction.csv"
    HEATMAP_OUT = OUTPUT_DIR / "heatmap_global.png"
    # Cellules historiques 4–6 : parser commun avec le backtest.
    # Aucune interpolation ou suppression des semaines calendaires manquantes.
    import numpy as np
    import pandas as pd
    from .prices import read_prices
    df = read_prices(INPUT_CSV)
    weekly = df.resample("W-FRI").last()
    if weekly.empty:
        raise ValueError("Aucune observation hebdomadaire exploitable")

    # Cellule historique 8

    import numpy as np

    def fast_lppls_fit(logp: np.ndarray):
        """
        Ajustement LPPLS rapide :
        - grille sur m, omega (ω), tc
        - estimation linéaire de A, B, C1, C2
        Retourne le meilleur fit (SSE minimum).
        """
        y = np.asarray(logp, float)
        n = len(y)
        t = np.arange(n, dtype=float)

        # Grilles (compactes pour rester rapides)
        m_grid = np.linspace(0.1, 0.9, 7)
        omega_grid = np.linspace(6.0, 13.0, 7)
        ahead_max = min(1.5*n, max(6, n))
        tc_ahead_grid = np.linspace(1.0, ahead_max, 7)

        best = None
        for m in m_grid:
            for omega in omega_grid:
                for ahead in tc_ahead_grid:
                    tc = (n - 1) + ahead
                    tau = tc - t
                    if np.any(tau <= 0):
                        continue

                    x1 = tau**m
                    ang = omega*np.log(tau)
                    x2 = x1*np.cos(ang)
                    x3 = x1*np.sin(ang)
                    X = np.column_stack([np.ones(n), x1, x2, x3])

                    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
                    yhat = X @ beta
                    resid = yhat - y
                    sse = float(np.sum(resid**2))

                    if (best is None) or (sse < best["sse"]):
                        A, B, C1, C2 = beta
                        sst = float(np.sum((y - y.mean())**2))
                        r2 = 1 - sse/sst if sst > 0 else np.nan
                        rmse = float(np.sqrt(np.mean(resid**2)))
                        C = float(np.sqrt(C1*C1 + C2*C2))
                        phi = float(np.arctan2(C2, C1) % (2*np.pi))
                        best = dict(success=True, A=float(A), B=float(B), C=C, m=float(m),
                                    omega=float(omega), phi=phi, tc=float(tc),
                                    r2=r2, rmse=rmse, sse=sse, n=n)
        return best if best is not None else {"success": False, "n": len(y)}

    def classify_fit(fit: dict):
        """Filtrage minimal + signal UP/DOWN."""
        if not fit.get("success", False):
            return False, "NONE"
        n = fit["n"]
        m, omega, tc, r2 = fit["m"], fit["omega"], fit["tc"], fit["r2"]

        valid = True
        if not (0.1 <= m <= 0.9): valid = False
        if not (6.0 <= omega <= 13.0): valid = False
        if not ((n-1) < tc <= (n-1) + 1.5*n): valid = False
        if np.isnan(r2) or r2 < 0.2: valid = False

        if not valid:
            return False, "NONE"

        # Convention : B < 0 => bulle haussière (accélération super‑exponentielle)
        signal = "UP" if fit["B"] < 0 else "DOWN"
        return True, signal

    # Cellule historique 10

    details_rows = []
    for asset in weekly.columns:
        if len(weekly) < min(WINDOW_WEEKS):
            continue
        for w in WINDOW_WEEKS:
            window = weekly[asset].iloc[-w:]
            # Une fenetre doit contenir exactement w semaines successives valides.
            if len(window) != w or window.isna().any():
                continue

            y = np.log(window.values.astype(float))
            fit = fast_lppls_fit(y)
            is_valid, signal = classify_fit(fit)
            tc_weeks_ahead = (fit["tc"] - (fit["n"]-1)) if fit.get("success", False) else np.nan

            details_rows.append({
                "asset": asset,
                "window_weeks": w,
                "start_date": window.index.min().date().isoformat(),
                "end_date": window.index.max().date().isoformat(),
                "n_obs": fit.get("n", len(y)),
                "A": fit.get("A", np.nan),
                "B": fit.get("B", np.nan),
                "C": fit.get("C", np.nan),
                "m": fit.get("m", np.nan),
                "omega": fit.get("omega", np.nan),
                "phi": fit.get("phi", np.nan),
                "tc_weeks_ahead": tc_weeks_ahead,
                "r2": fit.get("r2", np.nan),
                "rmse": fit.get("rmse", np.nan),
                "is_valid": bool(is_valid),
                "signal": signal
            })

    if not details_rows:
        raise ValueError("Aucun actif ne possede un historique hebdomadaire suffisant")

    details = pd.DataFrame(details_rows)
    details.to_csv(DETAILS_OUT, index=False)
    print("Saved:", DETAILS_OUT, "| rows:", len(details), "| assets:", details["asset"].nunique())
    details.head(3)

    # Cellule historique 12

    def make_wide(metric: str) -> pd.DataFrame:
        tmp = details.pivot(index="asset", columns="window_weeks", values=metric)
        tmp.columns = [f"{metric}_{c}w" for c in tmp.columns]
        return tmp

    wide = pd.concat([
        make_wide("signal"),
        make_wide("is_valid"),
        make_wide("tc_weeks_ahead"),
        make_wide("r2"),
    ], axis=1).reset_index()

    valid_cols = [c for c in wide.columns if c.startswith("is_valid_")]
    # Denominateur = toutes les fenetres choisies, y compris les lacunes.
    validity = pd.DataFrame(index=wide.index)
    for w in WINDOW_WEEKS:
        col = f"is_valid_{w}w"
        validity[w] = (wide[col].map(lambda v: bool(v) if pd.notna(v) else False)
                       if col in wide.columns else False)
    validity = validity.astype(float)
    wide["valid_frac"] = validity.sum(axis=1) / len(WINDOW_WEEKS)

    # Médiane de tc sur fenêtres valides
    tc_cols = {int(c.split("_")[2].replace("w","")): c for c in valid_cols}
    tc_value_cols = {int(c.split("_")[3].replace("w","")): c for c in wide.columns if c.startswith("tc_weeks_ahead_")}
    tc_medians = []
    for _, row in wide.iterrows():
        tcs = []
        for w, vcol in tc_cols.items():
            if bool(row[vcol]):
                tcs.append(row[tc_value_cols[w]])
        tc_medians.append(float(np.nanmedian(tcs)) if len(tcs) else np.nan)

    wide["tc_weeks_ahead_median"] = tc_medians

    wide.to_csv(SUMMARY_OUT, index=False)
    print("Saved:", SUMMARY_OUT, "| rows:", len(wide))
    wide.head(3)

    # Cellule historique 14

    short_ws = [13, 26]
    long_ws = [78, 104]

    def agg_signal(row, ws):
        sigs = []
        for w in ws:
            s = row.get(f"signal_{w}w", None)
            v = row.get(f"is_valid_{w}w", False)
            if bool(v) and isinstance(s, str) and s in ("UP", "DOWN"):
                sigs.append(s)
        if len(sigs) == 0:
            return "NONE"
        up = sum(1 for x in sigs if x == "UP")
        down = sum(1 for x in sigs if x == "DOWN")
        if up > down: return "UP"
        if down > up: return "DOWN"
        return "MIXED"

    bubble_rows = []
    for _, row in wide.iterrows():
        st = agg_signal(row, short_ws)
        lt = agg_signal(row, long_ws)

        if st in ("UP", "DOWN") and lt == st:
            mult = f"COHERENT_MULTI_{st}"
        elif st == "NONE" and lt == "NONE":
            mult = "NO_BUBBLE"
        else:
            mult = "MIXED_SCALES"

        tc_med = row["tc_weeks_ahead_median"]
        horizon_penalty = 1.0 if np.isnan(tc_med) else (1.0 + max(tc_med, 0)/10.0)
        coh_bonus = 2.0 if mult.startswith("COHERENT_MULTI_") else (0.5 if mult == "MIXED_SCALES" else 0.0)
        priority = 100.0 * (coh_bonus + row["valid_frac"]) / horizon_penalty

        bubble_rows.append({
            "asset": row["asset"],
            "bubble_short_term": st,
            "bubble_long_term": lt,
            "bubble_multiscale_state": mult,
            "valid_frac": row["valid_frac"],
            "tc_weeks_ahead_median": tc_med,
            "priority_score": priority
        })

    bubble_type = pd.DataFrame(bubble_rows).sort_values("priority_score", ascending=False)
    bubble_type.to_csv(BUBBLETYPE_OUT, index=False)
    print("Saved:", BUBBLETYPE_OUT, "| rows:", len(bubble_type))
    bubble_type.head(10)

    # Cellule historique 16

    bubble_cols = ["bubble_short_term","bubble_long_term","bubble_multiscale_state","valid_frac","tc_weeks_ahead_median","priority_score"]
    bubble_wide = wide.merge(bubble_type[["asset"] + bubble_cols], on="asset", how="left", suffixes=("", "_bubble"))

    # wide contient déjà valid_frac et tc_weeks_ahead_median : on remplace par ceux du livrable bulles
    for col in ["valid_frac", "tc_weeks_ahead_median"]:
        if col in wide.columns and col+"_bubble" in bubble_wide.columns:
            bubble_wide = bubble_wide.drop(columns=[col]).rename(columns={col+"_bubble": col})

    bubble_wide.to_csv(BUBBLE_WIDE_OUT, index=False)
    print("Saved:", BUBBLE_WIDE_OUT, "| rows:", len(bubble_wide))
    bubble_wide.head(3)

    # Cellule historique 18

    import matplotlib.pyplot as plt

    sig_map = {"UP": 1, "DOWN": -1, "NONE": 0, "MIXED": 0}
    heat = details.copy()
    heat["signal_num"] = heat["signal"].map(sig_map).fillna(0) * heat["is_valid"].astype(int)

    heat_pivot = heat.pivot(index="asset", columns="window_weeks", values="signal_num")
    # tri par priority_score (optionnel) si présent
    order = bubble_type["asset"].tolist()
    heat_pivot = heat_pivot.reindex(order)

    plt.figure(figsize=(10, max(6, len(heat_pivot)/8)))
    plt.imshow(heat_pivot.values, aspect="auto", interpolation="nearest")
    plt.yticks(range(len(heat_pivot.index)), heat_pivot.index, fontsize=6)
    plt.xticks(range(len(heat_pivot.columns)), [f"{c}w" for c in heat_pivot.columns])
    plt.title("Heatmap globale — signal LPPLS (UP=1, DOWN=-1, invalide=0)")
    plt.colorbar()
    plt.tight_layout()
    plt.savefig(HEATMAP_OUT, dpi=200)
    plt.close()

    print("Saved:", HEATMAP_OUT)

    # Cellule historique 20

    # Volatilité hebdo (52 semaines) et inverse-vol pour pondération simple
    rets = weekly.pct_change(fill_method=None)
    vol_52 = rets.tail(52).std(skipna=True)
    inv_vol = (1 / vol_52.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)

    bt = bubble_type.set_index("asset")
    # Un actif dont les 104 dernieres semaines sont incompletes ne peut etre detenu.
    complete = weekly.columns[
        weekly.tail(max(WINDOW_WEEKS)).notna().all() & (weekly.iloc[-1] > 0)
    ]
    eligible_long = bt.index[bt["bubble_multiscale_state"] != "COHERENT_MULTI_UP"].intersection(complete, sort=False)
    w_long = inv_vol.reindex(eligible_long).fillna(0).clip(lower=0)
    w_long = w_long / w_long.sum() if w_long.sum() > 0 else w_long

    short_assets = bt.index[bt["bubble_multiscale_state"] == "COHERENT_MULTI_UP"].intersection(complete, sort=False)
    w_short = bt.loc[short_assets, "priority_score"].clip(lower=0)
    w_short = (w_short / w_short.sum()) if (len(w_short) > 0 and w_short.sum() > 0) else pd.Series(dtype=float)

    w_long_ls = inv_vol.reindex(eligible_long).fillna(0).clip(lower=0)
    w_long_ls = (w_long_ls / w_long_ls.sum()) if w_long_ls.sum() > 0 else w_long_ls

    gross_long = 1.0 if w_short.empty else 0.5
    gross_short = 0.0 if w_short.empty else 0.5

    def rationale(state):
        if state == "COHERENT_MULTI_UP":
            return "Sous-pondération / short (bulle haussière cohérente)"
        if state == "COHERENT_MULTI_DOWN":
            return "Surveillance (bulle baissière cohérente)"
        if state == "MIXED_SCALES":
            return "Signal mixte (prudence)"
        return "Pas de bulle multi-échelles cohérente"

    portfolio = pd.DataFrame({"asset": bt.index})
    portfolio["bubble_multiscale_state"] = bt["bubble_multiscale_state"].values
    portfolio["priority_score"] = bt["priority_score"].values
    portfolio["weight_long_only"] = portfolio["asset"].map(w_long).fillna(0.0).values
    portfolio["weight_long_short"] = (
        portfolio["asset"].map(w_long_ls).fillna(0.0) * gross_long
        - portfolio["asset"].map(w_short).fillna(0.0) * gross_short
    ).values
    portfolio["rationale"] = portfolio["bubble_multiscale_state"].map(rationale).values

    portfolio.to_csv(PORTFOLIO_OUT, index=False)
    print("Saved:", PORTFOLIO_OUT, "| rows:", len(portfolio))
    portfolio.head(10)

    return {"daily": df, "weekly": weekly, "details": details, "summary": wide,
            "bubble_type": bubble_type, "bubble_summary": bubble_wide,
            "portfolio": portfolio, "heatmap_path": HEATMAP_OUT, "output_dir": OUTPUT_DIR}
