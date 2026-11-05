"""Interface Streamlit - snapshot historique et backtest experimental corrigé."""
import os
import sys
import tempfile
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from lppls_bubble import DEFAULT_WINDOWS, run_snapshot, BacktestSettings, run_backtest, REFERENCE_ENGINE
from lppls_bubble.reports import make_html, make_pdf
from lppls_bubble.delivery import build_delivery_zip
from lppls_bubble.lppls_fit import GRID_VERSION, GRID_SIZE
from lppls_bubble.data_review import (
    ACTIONS, FIELDS, audit_prices, read_decisions,
    merge_previous_decisions, validate_and_apply,
)
from lppls_bubble.statistical import StatisticalConfig, decide_asof
import numpy as np
import pandas as pd

st.set_page_config(page_title="LPPLS Bubble Detection", page_icon="📉", layout="wide")
st.title("LPPLS - Detection de bulles multi-echelles")
# Persist the last complete archive across Streamlit reruns (including the download click).
if "lppls_delivery_zip" not in st.session_state:
    st.session_state["lppls_delivery_zip"] = None
st.caption(f"Moteur de référence : {REFERENCE_ENGINE} ; grille LPPLS approfondie unique ({GRID_SIZE} combinaisons), commune au snapshot et au backtest.")
st.warning("Validation scientifique non acquise : sur 40 marches aleatoires simulees, les 40 fits LPPLS passaient le filtre de validite historique. Ne pas utiliser comme signal de trading autonome.")

@st.cache_data(show_spinner="Calcul LPPLS en cours...")
def calculate(payload: bytes, windows: tuple[int, ...]):
    with tempfile.TemporaryDirectory(prefix="lppls_") as folder:
        root = Path(folder)
        input_csv = root / "uploaded.csv"
        input_csv.write_bytes(payload)
        result = run_snapshot(input_csv, root / "out", windows)
        exports = {p.name: p.read_bytes() for p in sorted((root / "out").iterdir()) if p.is_file()}
        exports["rapport_lppls.html"] = make_html(result)
        exports["rapport_lppls.pdf"] = make_pdf(result)
        return result["weekly"], result["bubble_type"], result["details"], result["portfolio"], exports

@st.cache_data(show_spinner="Backtest historique exploratoire en cours (grille LPPLS)...")
def calculate_backtest(payload: bytes, windows: tuple[int, ...], start_date: str,
                       hold_weeks: int, max_rebalances: int | None, fee_bps: float,
                       quality_policy: str, event_payload: bytes | None):
    with tempfile.TemporaryDirectory(prefix="lppls_bt_") as folder:
        root = Path(folder)
        input_csv = root / "uploaded.csv"
        input_csv.write_bytes(payload)
        config = BacktestSettings(start_date=start_date, windows=windows,
                                  hold_weeks=hold_weeks, max_rebalances=max_rebalances, fee_bps=fee_bps,
                                  quality_policy=quality_policy)
        events_path = None
        if event_payload is not None:
            events_path = root / "quality_events.csv"
            events_path.write_bytes(event_payload)
        result = run_backtest(input_csv, root / "backtest", config, quality_events_csv=events_path)
        exports = {p.name: p.read_bytes() for p in sorted((root / "backtest").iterdir()) if p.is_file()}
        return (result["nav"], result["metrics"], result["states"],
                result["weights_lo"], result["weights_ls"],
                result["quality_history"], result["weighting_policy"],
                result["quality_weekly_alerts"], result["reconciliation"], exports)

@st.cache_data(show_spinner="Audit des cours quotidien et hebdomadaire...")
def calculate_price_audit(payload: bytes):
    with tempfile.TemporaryDirectory(prefix="lppls_price_audit_") as folder:
        source = Path(folder) / "source.csv"
        source.write_bytes(payload)
        return audit_prices(source)


def combine_documented_events(a: bytes | None, b: bytes | None) -> bytes | None:
    """Combine two explicit ledgers; never invent publication dates."""
    if a is None:
        return b
    if b is None:
        return a
    first = pd.read_csv(BytesIO(a), dtype=str)
    second = pd.read_csv(BytesIO(b), dtype=str)
    combined = pd.concat([first, second], ignore_index=True)
    cols = {"asset", "published_at", "action", "source"}
    if not cols.issubset(combined.columns):
        raise ValueError("Registre d'événements incomplet")
    return combined.drop_duplicates().to_csv(index=False).encode("utf-8")


# Keep controls reactive: Streamlit forms defer checkbox changes until submit.
# The analysis itself runs only after the explicit button click.
upload = st.file_uploader("CSV de cours (standard : Date;Actif... ou Datastream : trois lignes meta puis Name;Actif...)",type="csv")
# Stage one: audit immediately on CSV upload, before running any LPPLS fit.
reviewed = None
anomalies = None
old_orphans = pd.DataFrame()
review_ready = False
decision_csv = b""
source_payload = upload.getvalue() if upload is not None else None
st.subheader("Étape 1 — Contrôle et validation des données")
if source_payload is None:
    st.info("Charge un CSV de cours : les anomalies seront identifiées avant les calculs.")
else:
    previous_file = st.file_uploader(
        "Registre data_quality_decisions.csv d'une analyse précédente (facultatif)",
        type="csv", key="data_review_prior",
    )
    prior_payload = previous_file.getvalue() if previous_file is not None else None
    audit_key = sha256(source_payload + (prior_payload or b"")).hexdigest()[:16]
    try:
        anomalies = calculate_price_audit(source_payload)
        old_decisions = read_decisions(prior_payload) if prior_payload is not None else None
        merged, old_orphans = merge_previous_decisions(anomalies, old_decisions)
        n_critical = int((merged.severity == "CRITICAL").sum())
        st.caption(
            f"{len(merged)} alertes sur {merged.asset.nunique()} titres, "
            f"dont {n_critical} critiques. Les alertes ne prouvent pas une erreur."
        )
        if old_decisions is not None:
            st.success(
                f"{int((merged.compatibility == 'MATCH').sum())} décisions compatibles réutilisées. "
                f"{int((merged.compatibility == 'CHANGED_PRICE_REVIEW').sum())} observations modifiées, "
                f"{len(old_orphans)} événements absents du nouveau fichier."
            )
        if len(old_orphans):
            with st.expander("Anciennes décisions non retrouvées (non réappliquées)"):
                st.dataframe(old_orphans, use_container_width=True, hide_index=True)
        if merged.empty:
            st.success("Aucune anomalie détectée selon les seuils retenus. L'analyse peut être lancée.")
            reviewed = merged
        else:
            editor_data = merged.copy()
            editor_data["exclude_asset_retro"] = editor_data.action.eq("EXCLUDE_ASSET_RETRO")
            editor_data.loc[editor_data.exclude_asset_retro, "action"] = "REVIEW"
            show_columns = [
                "event_id", "asset", "date", "frequency", "kind", "return_pct",
                "gap_weeks", "severity", "action", "exclude_asset_retro", "reason",
                "evidence", "published_at", "compatibility",
            ]
            st.caption(
                "Coche « Exclure titre (rétro) » pour retirer entièrement un actif des "
                "estimations ET du backtest : le résultat devient une analyse de sensibilité. "
                "BLOCK_ASOF bloque uniquement les nouvelles positions après une publication documentée."
            )
            edited = st.data_editor(
                editor_data[show_columns], hide_index=True, use_container_width=True,
                height=480, num_rows="fixed", key="review_" + audit_key,
                disabled=["event_id","asset","date","frequency","kind",
                          "return_pct","gap_weeks","severity","compatibility"],
                column_config={
                    "action": st.column_config.SelectboxColumn(
                        "Décision", options=["REVIEW", "KEEP", "BLOCK_ASOF"], required=True),
                    "exclude_asset_retro": st.column_config.CheckboxColumn(
                        "Exclure titre (rétro)", default=False),
                    "return_pct": st.column_config.NumberColumn("Variation (%)", format="%.2f"),
                    "gap_weeks": st.column_config.NumberColumn("Semaines manquantes", format="%d"),
                },
            )
            reviewed = merged.copy()
            for field in ("action", "reason", "evidence", "published_at"):
                reviewed[field] = edited[field].to_numpy()
            reviewed.loc[edited.exclude_asset_retro.to_numpy(dtype=bool), "action"] = "EXCLUDE_ASSET_RETRO"
            changed = reviewed.compatibility.eq("CHANGED_PRICE_REVIEW")
            if changed.any():
                reconfirm = st.checkbox(
                    "J'ai réexaminé les observations dont les prix ont changé et je confirme mes nouvelles décisions.",
                    value=False, key="reconfirm_" + audit_key,
                )
                if reconfirm:
                    reviewed.loc[changed, "compatibility"] = "REVALIDATED"
            unresolved = reviewed.action.eq("REVIEW") & reviewed.severity.eq("CRITICAL")
            if unresolved.any():
                st.warning(
                    f"{int(unresolved.sum())} anomalies critiques restent non résolues. "
                    "Leurs rendements demeureront inchangés dans le backtest."
                )
                acknowledge = st.checkbox(
                    "Je souhaite poursuivre en conservant les anomalies critiques non résolues.",
                    value=False, key="accept_unresolved_" + audit_key,
                )
            else:
                acknowledge = True
        if merged.empty:
            acknowledge = True
        review_ready = bool(acknowledge)
        decision_csv = reviewed[FIELDS].to_csv(index=False).encode("utf-8")
        st.download_button(
            "Télécharger le registre CSV des décisions",
            decision_csv, file_name="data_quality_decisions.csv", mime="text/csv",
            key="decision_download_" + audit_key,
        )
    except Exception as exc:
        reviewed = None
        st.error(f"Audit des données impossible : {exc}")
st.subheader("Étape 2 — Estimations LPPLS et backtest")
selected = st.multiselect("Fenetres hebdomadaires", list(DEFAULT_WINDOWS), default=list(DEFAULT_WINDOWS))
run_statistical = st.checkbox("Diagnostic statistique expérimental (bootstrap, 52 et 104 semaines)", value=False)
run_bt = st.checkbox("Calculer également un backtest historique expérimental", value=False)
if run_bt:
    st.caption("Les signaux au temps t n'utilisent aucune donnee posterieure à t. La strategie est reponderee periodiquement (pas de reproduction numerique de la version notebook).")
    bt_start = st.date_input("Date de debut", value=__import__("datetime").date(2024, 2, 1))
    bt_hold = st.number_input("Periode de rebalancement (semaines)", min_value=1, max_value=26, value=4)
    bt_limited = st.checkbox(
        "Limiter le nombre de rééquilibrages (sinon jusqu'à la dernière semaine complète)",
        value=False,
        help="Désactivé : étudier tout l'historique admissible, même si la dernière période contient moins de 4 semaines."
    )
    bt_periods = (st.number_input("Nombre maximal de rééquilibrages",
                                   min_value=1, max_value=500, value=24)
                  if bt_limited else None)
    bt_fees = st.number_input("Frais de transactions (points de base)", min_value=0.0, max_value=100.0, value=0.0)
    bt_quality = st.selectbox("Politique de qualité des cours",
                              ["audit", "block_documented"], index=0,
                              help="audit: alertes sans exclusion; block_documented: blocages selon dates de publication d’un registre externe")
    bt_events = st.file_uploader("Registre d’événements CSV facultatif (asset,published_at,action,source)",
                                 type="csv", key="quality_events")
    st.caption("La volatilité extrême est signalée, mais n’entraîne aucune exclusion automatique. Pondérations originales préservées.")
# The ZIP is valid only for the dataset, decisions and parameters that created it.
form_parameters = {
    "windows": tuple(sorted(selected)), "statistical": bool(run_statistical),
    "backtest": bool(run_bt),
}
if run_bt:
    form_parameters["backtest_settings"] = (
        bt_start.isoformat(), int(bt_hold), bt_periods, float(bt_fees),
        bt_quality, bt_events.getvalue() if bt_events is not None else None,
    )
current_run_signature = sha256(
    (source_payload or b"") + decision_csv +
    repr(form_parameters).encode("utf-8")
).hexdigest()
submitted = st.button("Lancer l'analyse", type="primary")

if submitted:
    # Never keep a previous archive when a new submission has failed.
    st.session_state["lppls_delivery_zip"] = None
    if not upload:
        st.error("Importer un fichier CSV.")
    elif not selected:
        st.error("Selectionner au moins une fenetre.")
    elif reviewed is None:
        st.error("L'audit doit être réalisé avant l'analyse.")
    elif not review_ready:
        st.error("Valide les anomalies critiques non résolues avant de poursuivre.")
    else:
        try:
            with tempfile.TemporaryDirectory(prefix="lppls_reviewed_") as folder:
                source_path = Path(folder) / "source.csv"
                source_path.write_bytes(source_payload)
                _, analysed_payload, reviewed_events, retro_exclusions, study_type = (
                    validate_and_apply(reviewed, source_path)
                )
            existing_events = (bt_events.getvalue() if run_bt and bt_events is not None else None)
            event_payload = combine_documented_events(reviewed_events, existing_events)
            effective_quality_policy = (
                "block_documented" if reviewed_events is not None else
                bt_quality if run_bt else "audit"
            )
            weekly,bubbles,details,portfolio,exports = calculate(
                analysed_payload, tuple(sorted(selected))
            )
        except Exception as exc:
            st.error(f"Calcul impossible : {exc}")
        else:
            st.success(f"Analyse terminée : {len(bubbles)} actifs, {len(details)} estimations.")
            if study_type == "RETROSPECTIVE_SENSITIVITY":
                st.warning(
                    f"Analyse de sensibilité rétrospective : {len(retro_exclusions)} titre(s) "
                    "exclu(s) sur tout l'historique. Cela ne constitue pas un backtest causal."
                )
            audit_exports = {
                "data_quality_anomalies.csv": anomalies[FIELDS].to_csv(index=False).encode("utf-8"),
                "data_quality_decisions.csv": reviewed[FIELDS].to_csv(index=False).encode("utf-8"),
                "analyzed_prices.csv": analysed_payload,
                "excluded_assets.csv": retro_exclusions.to_csv(index=False).encode("utf-8"),
                "previous_rules_not_reapplied.csv": old_orphans.to_csv(index=False).encode("utf-8"),
            }
            a,b,c=st.columns(3)
            a.metric("Actifs",len(bubbles))
            b.metric("Ajustements LPPLS",len(details))
            c.metric("Bulles coherentes UP",int((bubbles.bubble_multiscale_state=="COHERENT_MULTI_UP").sum()))
            statistical_exports = {}
            backtest_exports = {}
            run_status = {
                "lppls": "success",
                "backtest": "not_requested" if not run_bt else "pending",
                "statistical": "not_requested" if not run_statistical else "pending",
            }
            tab1,tab2,tab3,tab4=st.tabs(["Classement","Heatmap","Cours","Portefeuilles"])
            with tab1:
                st.dataframe(bubbles,use_container_width=True,hide_index=True)
                st.dataframe(details,use_container_width=True,hide_index=True)
            with tab2:
                st.image(exports["heatmap_global.png"],caption="UP=1 ; DOWN=-1 ; invalide=0")
            with tab3:
                asset=st.selectbox("Actif",list(weekly.columns))
                st.line_chart(weekly[asset].dropna(),use_container_width=True)
            with tab4:
                st.dataframe(portfolio,use_container_width=True,hide_index=True)

            if run_statistical:
                st.subheader("Diagnostic statistique : non validé économiquement")
                st.caption("Test d'amélioration oscillatoire par rapport à une tendance lisse. "
                           "Bootstrap de blocs et marche aléatoire gaussienne, 199 réplications par famille. "
                           "Correction FDR BH à chaque date sur tous les actifs et horizons disponibles.")
                try:
                    cfg = StatisticalConfig()
                    asof = weekly.index[-1].date().isoformat()
                    eligible = {}
                    for asset in weekly.columns:
                        for w in cfg.windows:
                            segment = weekly[asset].iloc[-w:]
                            if len(segment) == w and segment.notna().all() and (segment > 0).all():
                                eligible.setdefault(asset, {})[w] = np.log(segment.to_numpy(float))
                    rows = decide_asof(eligible, cfg, asof)
                    if not rows:
                        st.info("Aucune fenêtre complète 52/104 semaines pour ce diagnostic.")
                        run_status["statistical"] = "no_eligible_windows"
                    else:
                        diag = pd.DataFrame(rows)
                        st.metric("Signaux statistiquement acceptés", int(diag.significant.sum()))
                        st.dataframe(diag.sort_values(["q_bh", "asset"]), use_container_width=True, hide_index=True)
                        statistical_exports[f"lppls_significance_{asof}.csv"] = diag.to_csv(index=False).encode("utf-8")
                        run_status["statistical"] = "success"
                        st.warning("Le test n'est pas une probabilité de bulle. "
                                   "Une absence d'alerte ne garantit pas l'absence de retournement.")
                except Exception as exc:
                    run_status["statistical"] = "error: " + str(exc)
                    st.error(f"Diagnostic statistique impossible : {exc}")

            if run_bt:
                st.subheader("Backtest exploratoire : validation scientifique en cours")
                st.info("Les notebooks d'origine sont archives dans le depot. Le nouveau backtest exclut la selection avec cours futurs et suit les poids qui derivent entre rebalancements ; il est donc DIFFERENT de l'ancien backtest.")
                try:
                    bt_nav, bt_metrics, bt_states, bt_lo, bt_ls, bt_quality_history, bt_weighting_policy, bt_weekly_alerts, bt_reconciliation, bt_exports = calculate_backtest(
                        analysed_payload, tuple(sorted(selected)), bt_start.isoformat(),
                        int(bt_hold), int(bt_periods) if bt_periods is not None else None, float(bt_fees),
                        effective_quality_policy, event_payload)
                except Exception as exc:
                    run_status["backtest"] = "error: " + str(exc)
                    st.error(f"Backtest impossible : {exc}")
                else:
                    backtest_exports = bt_exports
                    run_status["backtest"] = "success"
                    st.caption(
                        f"Période réelle : {bt_nav.date.iloc[0]} → {bt_nav.date.iloc[-1]} "
                        f"— {int(bt_metrics.num_rebalances.iloc[0])} décisions."
                    )
                    st.dataframe(bt_metrics, use_container_width=True, hide_index=True)
                    critical_count = int((bt_weekly_alerts["severity"] == "CRITICAL_REVIEW").sum())
                    if critical_count:
                        st.warning(
                            f"{critical_count} mouvements de prix critiques à vérifier sur des "
                            "séries ajustées avant d'interpréter les performances. "
                            "Ces mouvements n'ont pas été supprimés du backtest."
                        )
                    with st.expander("Qualité hebdomadaire et rapprochement des NAV"):
                        st.dataframe(bt_weekly_alerts, use_container_width=True, hide_index=True)
                        st.dataframe(bt_reconciliation, use_container_width=True, hide_index=True)
                        st.caption("Les alertes de prix n'excluent aucun actif en mode audit et ne constituent pas une preuve d'erreur.")
                    with st.expander("Audit qualité causal et conventions de pondération"):
                        st.dataframe(bt_quality_history, use_container_width=True, hide_index=True)
                        st.dataframe(bt_weighting_policy, use_container_width=True, hide_index=True)
                    st.line_chart(bt_nav.set_index("date")[["nav_long_only", "nav_long_short"]], use_container_width=True)
                    with st.expander("Signaux, positions et historique"):
                        st.dataframe(bt_states, use_container_width=True, hide_index=True)
                        st.dataframe(bt_lo, use_container_width=True, hide_index=True)
                        st.dataframe(bt_ls, use_container_width=True, hide_index=True)
            # One archive per analysis: snapshot, backtest and optional
            # experimental diagnostics are preserved under separate folders.
            # The manifest captures parameters and partial failures.
            params = {
                "windows_weeks": tuple(sorted(selected)),
                "reference_engine": REFERENCE_ENGINE,
                "lppls_grid_version": GRID_VERSION,
                "lppls_grid_candidates_per_fit": GRID_SIZE,
                "data_review_study_type": study_type,
                "retrospectively_excluded_assets": retro_exclusions.asset.tolist(),
                "data_review_anomaly_count": int(len(anomalies)),
                "data_review_unresolved_count": int((reviewed.action == "REVIEW").sum()),
                "backtest_requested": bool(run_bt),
                "statistical_requested": bool(run_statistical),
            }
            if run_bt:
                params["backtest"] = {
                    "start_date": bt_start.isoformat(),
                    "hold_weeks": int(bt_hold),
                    "max_rebalances": int(bt_periods) if bt_periods is not None else None,
                    "fee_bps": float(bt_fees),
                    "quality_policy": effective_quality_policy,
                    "event_register_supplied": event_payload is not None,
                }
            delivery_zip = build_delivery_zip(
                exports, backtest_exports, statistical_exports,
                audit_exports=audit_exports,
                source_csv=source_payload, source_name=upload.name,
                event_register_csv=event_payload if run_bt else None,
                parameters=params, run_status=run_status,
            )
            st.session_state["lppls_delivery_zip"] = delivery_zip
            st.session_state["lppls_delivery_signature"] = current_run_signature

# Display outside the form-submit branch so the download button remains visible
# on subsequent reruns. This also avoids recalc when a download triggers a rerun.
if (
    st.session_state["lppls_delivery_zip"] is not None
    and st.session_state.get("lppls_delivery_signature") == current_run_signature
):
    st.subheader("Télécharger tous les livrables")
    st.caption(
        "Une seule archive ZIP contenant les résultats LPPLS, "
        "le backtest et le diagnostic statistique lorsqu'ils sont calculés, "
        "plus le CSV source et un manifeste d'audit."
    )
    st.download_button(
        "Télécharger les livrables LPPLS (ZIP)",
        data=st.session_state["lppls_delivery_zip"],
        file_name="lppls_livrables_complets.zip",
        mime="application/zip",
        type="primary",
        key="lppls_livrables_zip",
    )
