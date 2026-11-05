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
    merge_previous_decisions, validate_and_apply, classify_uploaded_registry,
    backtest_audit_window, critical_in_backtest, critical_by_title,
    apply_title_decisions,
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
upload = st.file_uploader(
    "CSV de cours (standard : Date;Actif... ou Datastream : trois lignes meta puis Name;Actif...)",
    type="csv",
)
source_payload = upload.getvalue() if upload is not None else None

# Backtest dates have to be chosen BEFORE the audit. Otherwise a filter over
# the full historical data would silently introduce future/out-of-sample alerts.
run_bt = st.checkbox("Calculer également un backtest historique expérimental", value=False)
if run_bt:
    with st.expander("Période et paramètres du backtest", expanded=True):
        st.caption("Les anomalies critiques seront détectées UNIQUEMENT sur les dates réellement valorisées par ce backtest.")
        bt_start = st.date_input("Date de début", value=__import__("datetime").date(2024, 2, 1))
        bt_hold = st.number_input("Période de rééquilibrage (semaines)", min_value=1, max_value=26, value=4)
        bt_limited = st.checkbox(
            "Limiter le nombre de rééquilibrages (sinon jusqu'à la dernière semaine complète)",
            value=False,
        )
        bt_periods = (
            st.number_input("Nombre maximal de rééquilibrages", min_value=1, max_value=500, value=24)
            if bt_limited else None
        )
        bt_fees = st.number_input("Frais de transactions (points de base)", min_value=0.0, max_value=100.0, value=0.0)
        bt_quality = st.selectbox(
            "Politique de qualité des cours", ["audit", "block_documented"], index=0,
            help="audit : alertes sans exclusion automatique ; block_documented : blocage après publication documentée",
        )
else:
    st.caption("Sans backtest, aucune anomalie critique ne bloque l'analyse LPPLS.")

@st.cache_data(show_spinner="Recherche des anomalies critiques pendant le backtest...")
def calculate_critical_audit(payload: bytes, start_date: str, hold_weeks: int,
                             max_rebalances: int | None):
    with tempfile.TemporaryDirectory(prefix="lppls_critical_audit_") as folder:
        source = Path(folder) / "source.csv"
        source.write_bytes(payload)
        first, last, n_decisions = backtest_audit_window(
            source, start_date, hold_weeks, max_rebalances,
        )
        full = audit_prices(source)
        return critical_in_backtest(full, first, last), first, last, n_decisions

reviewed = None
anomalies = None
old_orphans = pd.DataFrame()
pending_critical = 0
decision_csv = b""
st.subheader("Étape 1 — Contrôle des anomalies critiques du backtest")
if source_payload is None:
    st.info("Charge un CSV de cours pour commencer.")
else:
    previous_file = st.file_uploader(
        "Registre data_quality_decisions.csv d'une analyse précédente (facultatif)",
        type="csv", key="data_review_prior",
    )
    with st.expander("Option avancée — événements de blocage datés (facultatif)"):
        bt_events = st.file_uploader(
            "Registre d'événements (asset,published_at,action,source)",
            type="csv", key="quality_events",
        )
    prior_payload = previous_file.getvalue() if previous_file is not None else None
    legacy_event_payload = bt_events.getvalue() if bt_events is not None else None
    registry_message = None
    registry_error = None
    if legacy_event_payload is not None:
        try:
            if classify_uploaded_registry(legacy_event_payload) == "decisions":
                if prior_payload is not None:
                    registry_error = "Deux registres de décisions sont fournis : n'en conserve qu'un."
                else:
                    prior_payload = legacy_event_payload
                    legacy_event_payload = None
                    registry_message = "Le registre de décisions a été reconnu et appliqué à l'étape 1."
        except ValueError as exc:
            registry_error = str(exc)
    date_options = (
        (bt_start.isoformat(), int(bt_hold), bt_periods) if run_bt else ("NO_BACKTEST",)
    )
    audit_key = sha256(
        source_payload + (prior_payload or b"") + repr(date_options).encode("utf-8")
    ).hexdigest()[:16]
    try:
        if registry_error:
            raise ValueError(registry_error)
        if registry_message:
            st.info(registry_message)
        if run_bt:
            anomalies, first_audit, last_audit, n_audit_decisions = calculate_critical_audit(
                source_payload, bt_start.isoformat(), int(bt_hold),
                int(bt_periods) if bt_periods is not None else None,
            )
            st.caption(
                f"Période effective : {first_audit.date()} au {last_audit.date()} "
                f"({n_audit_decisions} décisions). Les 104 semaines précédentes "
                "servent au calcul LPPLS, mais pas à l'alerte critique."
            )
        else:
            anomalies = pd.DataFrame(columns=FIELDS)
        old_decisions = read_decisions(prior_payload) if prior_payload is not None else None
        merged, old_orphans = merge_previous_decisions(anomalies, old_decisions)
        n_critical = len(merged)
        st.caption(
            f"{n_critical} anomalie(s) critique(s) sur "
            f"{merged.asset.nunique()} titre(s) pendant le backtest."
            if run_bt else "Analyse LPPLS seule : aucune exclusion de backtest nécessaire."
        )
        if old_decisions is not None:
            st.info(
                f"{int((merged.compatibility == 'MATCH').sum())} décision(s) réutilisée(s) ; "
                f"{int((merged.compatibility == 'CHANGED_PRICE_REVIEW').sum())} prix révisé(s) "
                f"et {len(old_orphans)} ancien(s) événement(s) non réappliqué(s)."
            )
        if len(old_orphans):
            with st.expander("Décisions anciennes hors période ou devenues incompatibles"):
                st.dataframe(old_orphans, use_container_width=True, hide_index=True)
        if merged.empty:
            st.success("Aucun titre à exclure sur la période sélectionnée.")
            reviewed = merged
        else:
            by_title = critical_by_title(merged)
            st.caption(
                "Une seule case par titre : cocher exclut le titre de TOUT le backtest "
                "(et non une observation particulière). Les anomalies restent consultables ci-dessous."
            )
            edited_titles = st.data_editor(
                by_title, hide_index=True, use_container_width=True,
                num_rows="fixed", key="review_titles_" + audit_key,
                disabled=["asset", "n_critical", "first_date", "last_date",
                          "max_abs_return_pct"],
                column_config={
                    "asset": st.column_config.TextColumn("Titre"),
                    "n_critical": st.column_config.NumberColumn("Alertes critiques"),
                    "first_date": st.column_config.TextColumn("Première alerte"),
                    "last_date": st.column_config.TextColumn("Dernière alerte"),
                    "max_abs_return_pct": st.column_config.NumberColumn(
                        "Amplitude maximale (%)", format="%.2f"
                    ),
                    "exclude_backtest": st.column_config.CheckboxColumn(
                        "Exclure le titre du backtest", default=False
                    ),
                    "reason": st.column_config.TextColumn("Justification (facultative)"),
                },
            )
            with st.expander("Détail des anomalies critiques par titre"):
                st.dataframe(
                    merged[["asset", "date", "frequency", "kind",
                            "previous_price", "observed_price", "return_pct",
                            "severity"]],
                    use_container_width=True, hide_index=True,
                )
            reviewed = apply_title_decisions(merged, edited_titles)
        pending_critical = int(
            (reviewed.action.eq("REVIEW") & reviewed.severity.eq("CRITICAL")).sum()
        )
        decision_csv = reviewed[FIELDS].to_csv(index=False).encode("utf-8")
        st.download_button(
            "Télécharger les exclusions et anomalies (CSV)",
            data=decision_csv, file_name="data_quality_decisions.csv",
            mime="text/csv", key="decision_download_" + audit_key,
        )
    except Exception as exc:
        reviewed = None
        st.error(f"Audit des données impossible : {exc}")

st.subheader("Étape 2 — Estimations LPPLS et backtest")
selected = st.multiselect(
    "Fenêtres hebdomadaires", list(DEFAULT_WINDOWS), default=list(DEFAULT_WINDOWS)
)
run_statistical = st.checkbox(
    "Diagnostic statistique expérimental (bootstrap, 52 et 104 semaines)", value=False
)
if run_bt:
    st.caption("Période et paramètres du backtest définis au-dessus de l'étape 1.")
# The ZIP is valid only for the dataset, decisions and parameters that created it.
form_parameters = {
    "windows": tuple(sorted(selected)), "statistical": bool(run_statistical),
    "backtest": bool(run_bt),
}
if run_bt:
    form_parameters["backtest_settings"] = (
        bt_start.isoformat(), int(bt_hold), bt_periods, float(bt_fees),
        bt_quality, legacy_event_payload if source_payload is not None else None,
    )
current_run_signature = sha256(
    (source_payload or b"") + decision_csv +
    repr(form_parameters).encode("utf-8")
).hexdigest()
if pending_critical:
    st.warning(
        f"{pending_critical} anomalie(s) critique(s) restent à examiner. "
        "Leurs rendements ne sont ni supprimés ni corrigés automatiquement."
    )
    accept_unresolved = st.checkbox(
        "Je confirme poursuivre l'analyse avec ces anomalies critiques non résolues",
        value=False,
        key="accept_unresolved_stage2",
    )
else:
    accept_unresolved = True
can_launch = source_payload is not None and reviewed is not None and bool(selected)
if not accept_unresolved:
    st.caption("Coche la confirmation juste au-dessus pour activer le lancement.")
submitted = st.button(
    "Lancer l'analyse", type="primary",
    disabled=(not can_launch or not accept_unresolved),
)

if submitted:
    # Never keep a previous archive when a new submission has failed.
    st.session_state["lppls_delivery_zip"] = None
    if not upload:
        st.error("Importer un fichier CSV.")
    elif not selected:
        st.error("Selectionner au moins une fenetre.")
    elif reviewed is None:
        st.error("L'audit doit être réalisé avant l'analyse.")
    else:
        try:
            with tempfile.TemporaryDirectory(prefix="lppls_reviewed_") as folder:
                source_path = Path(folder) / "source.csv"
                source_path.write_bytes(source_payload)
                (_, snapshot_payload, backtest_payload, reviewed_events,
                 retro_exclusions, study_type) = validate_and_apply(reviewed, source_path)
            existing_events = legacy_event_payload if run_bt else None
            event_payload = combine_documented_events(reviewed_events, existing_events)
            effective_quality_policy = (
                "block_documented" if run_bt and event_payload is not None
                else bt_quality if run_bt else "audit"
            )
            weekly,bubbles,details,portfolio,exports = calculate(
                snapshot_payload, tuple(sorted(selected))
            )
        except Exception as exc:
            st.error(f"Calcul impossible : {exc}")
        else:
            st.success(f"Analyse terminée : {len(bubbles)} actifs, {len(details)} estimations.")
            if study_type == "RETROSPECTIVE_SENSITIVITY":
                st.warning(
                    f"Analyse de sensibilité rétrospective : {len(retro_exclusions)} titre(s) "
                    "exclu(s) sur tout l'historique, selon le périmètre retenu "
                    "(backtest seul ou ensemble des estimations). Ce n'est pas un backtest causal."
                )
            audit_exports = {
                "data_quality_anomalies.csv": anomalies[FIELDS].to_csv(index=False).encode("utf-8"),
                "data_quality_decisions.csv": reviewed[FIELDS].to_csv(index=False).encode("utf-8"),
                "snapshot_prices.csv": snapshot_payload,
                "backtest_prices.csv": backtest_payload,
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
                        backtest_payload, tuple(sorted(selected)), bt_start.isoformat(),
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
                "snapshot_excluded_assets": retro_exclusions.loc[
                    retro_exclusions.scope == "SNAPSHOT_AND_BACKTEST", "asset"
                ].tolist(),
                "backtest_only_excluded_assets": retro_exclusions.loc[
                    retro_exclusions.scope == "BACKTEST_ONLY", "asset"
                ].tolist(),
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
