"""Interface Streamlit - snapshot historique et backtest experimental corrigé."""
import os
import sys
import tempfile
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from lppls_bubble import DEFAULT_WINDOWS, run_snapshot, BacktestSettings, run_backtest, REFERENCE_ENGINE
from lppls_bubble.reports import make_html, make_pdf
from lppls_bubble.delivery import build_delivery_zip
from lppls_bubble.statistical import StatisticalConfig, decide_asof
import numpy as np
import pandas as pd

st.set_page_config(page_title="LPPLS Bubble Detection", page_icon="📉", layout="wide")
st.title("LPPLS - Detection de bulles multi-echelles")
# Persist the last complete archive across Streamlit reruns (including the download click).
if "lppls_delivery_zip" not in st.session_state:
    st.session_state["lppls_delivery_zip"] = None
st.caption(f"Moteur de reference : {REFERENCE_ENGINE} (snapshot et backtest) ; alternative conservee en recherche.")
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
                       hold_weeks: int, max_rebalances: int, fee_bps: float,
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
                result["quality_history"], result["weighting_policy"], exports)

# Keep controls reactive: Streamlit forms defer checkbox changes until submit.
# The analysis itself runs only after the explicit button click.
upload = st.file_uploader("CSV de cours (standard : Date;Actif... ou Datastream : trois lignes meta puis Name;Actif...)",type="csv")
selected = st.multiselect("Fenetres hebdomadaires", list(DEFAULT_WINDOWS), default=list(DEFAULT_WINDOWS))
run_statistical = st.checkbox("Diagnostic statistique expérimental (bootstrap, 52 et 104 semaines)", value=False)
run_bt = st.checkbox("Calculer également un backtest historique expérimental", value=False)
if run_bt:
    st.caption("Les signaux au temps t n'utilisent aucune donnee posterieure à t. La strategie est reponderee periodiquement (pas de reproduction numerique de la version notebook).")
    bt_start = st.date_input("Date de debut", value=__import__("datetime").date(2024, 2, 1))
    bt_hold = st.number_input("Periode de rebalancement (semaines)", min_value=1, max_value=26, value=4)
    bt_periods = st.number_input("Nombre maximal de rebalancements", min_value=1, max_value=24, value=6)
    bt_fees = st.number_input("Frais de transactions (points de base)", min_value=0.0, max_value=100.0, value=0.0)
    bt_quality = st.selectbox("Politique de qualité des cours",
                              ["audit", "block_documented"], index=0,
                              help="audit: alertes sans exclusion; block_documented: blocages selon dates de publication d’un registre externe")
    bt_events = st.file_uploader("Registre d’événements CSV facultatif (asset,published_at,action,source)",
                                 type="csv", key="quality_events")
    st.caption("La volatilité extrême est signalée, mais n’entraîne aucune exclusion automatique. Pondérations originales préservées.")
submitted = st.button("Lancer l'analyse", type="primary")

if submitted:
    # Never keep a previous archive when a new submission has failed.
    st.session_state["lppls_delivery_zip"] = None
    if not upload:
        st.error("Importer un fichier CSV.")
    elif not selected:
        st.error("Selectionner au moins une fenetre.")
    else:
        try:
            weekly,bubbles,details,portfolio,exports = calculate(upload.getvalue(),tuple(sorted(selected)))
        except Exception as exc:
            st.error(f"Calcul impossible : {exc}")
        else:
            st.success(f"Analyse terminee : {len(bubbles)} actifs, {len(details)} estimations.")
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
                    bt_nav, bt_metrics, bt_states, bt_lo, bt_ls, bt_quality_history, bt_weighting_policy, bt_exports = calculate_backtest(
                        upload.getvalue(), tuple(sorted(selected)), bt_start.isoformat(),
                        int(bt_hold), int(bt_periods), float(bt_fees),
                        bt_quality, bt_events.getvalue() if bt_events is not None else None)
                except Exception as exc:
                    run_status["backtest"] = "error: " + str(exc)
                    st.error(f"Backtest impossible : {exc}")
                else:
                    backtest_exports = bt_exports
                    run_status["backtest"] = "success"
                    st.dataframe(bt_metrics, use_container_width=True, hide_index=True)
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
                "backtest_requested": bool(run_bt),
                "statistical_requested": bool(run_statistical),
            }
            if run_bt:
                params["backtest"] = {
                    "start_date": bt_start.isoformat(),
                    "hold_weeks": int(bt_hold),
                    "max_rebalances": int(bt_periods),
                    "fee_bps": float(bt_fees),
                    "quality_policy": bt_quality,
                    "event_register_supplied": bt_events is not None,
                }
            delivery_zip = build_delivery_zip(
                exports, backtest_exports, statistical_exports,
                source_csv=upload.getvalue(), source_name=upload.name,
                event_register_csv=(bt_events.getvalue() if run_bt and bt_events is not None else None),
                parameters=params, run_status=run_status,
            )
            st.session_state["lppls_delivery_zip"] = delivery_zip

# Display outside the form-submit branch so the download button remains visible
# on subsequent reruns. This also avoids recalc when a download triggers a rerun.
if st.session_state["lppls_delivery_zip"] is not None:
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
