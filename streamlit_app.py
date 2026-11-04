"""Interface Streamlit - snapshot historique et backtest experimental corrigé."""
import os
import sys
import tempfile
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from lppls_bubble import DEFAULT_WINDOWS, run_snapshot, BacktestSettings, run_backtest, REFERENCE_ENGINE
from lppls_bubble.reports import make_html, make_pdf

st.set_page_config(page_title="LPPLS Bubble Detection", page_icon="📉", layout="wide")
st.title("LPPLS - Detection de bulles multi-echelles")
st.caption(f"Moteur de reference : {REFERENCE_ENGINE} (snapshot et backtest) ; variante de recherche conservee.")
st.warning("Filtre exploratoire non valide : sur 40 marches aleatoires simulees, 40 fits ont passe les filtres heuristiques. Ne pas utiliser comme signal de trading autonome.")

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
                       hold_weeks: int, max_rebalances: int, fee_bps: float):
    with tempfile.TemporaryDirectory(prefix="lppls_bt_") as folder:
        root = Path(folder)
        input_csv = root / "uploaded.csv"
        input_csv.write_bytes(payload)
        config = BacktestSettings(start_date=start_date, windows=windows,
                                  hold_weeks=hold_weeks, max_rebalances=max_rebalances, fee_bps=fee_bps)
        result = run_backtest(input_csv, root / "backtest", config)
        exports = {p.name: p.read_bytes() for p in sorted((root / "backtest").iterdir()) if p.is_file()}
        return result["nav"], result["metrics"], result["states"], result["weights_lo"], result["weights_ls"], exports

with st.form("input_form"):
    upload = st.file_uploader("CSV de cours (format historique : trois lignes d'entete, colonnes Name et valeurs)",type="csv")
    selected = st.multiselect("Fenetres hebdomadaires", list(DEFAULT_WINDOWS), default=list(DEFAULT_WINDOWS))
    run_bt = st.checkbox("Calculer également un backtest historique expérimental", value=False)
    if run_bt:
        st.caption("Les signaux au temps t n'utilisent aucune donnee posterieure à t. La strategie est reponderee periodiquement (pas de reproduction numerique de la version notebook).")
        bt_start = st.date_input("Date de debut", value=__import__("datetime").date(2024, 2, 1))
        bt_hold = st.number_input("Periode de rebalancement (semaines)", min_value=1, max_value=26, value=4)
        bt_periods = st.number_input("Nombre maximal de rebalancements", min_value=1, max_value=24, value=6)
        bt_fees = st.number_input("Frais de transactions (points de base)", min_value=0.0, max_value=100.0, value=0.0)
    submitted = st.form_submit_button("Lancer l'analyse", type="primary")

if submitted:
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
            tab1,tab2,tab3,tab4=st.tabs(["Classement","Heatmap","Cours","Portefeuilles et exports"])
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
                for name,content in exports.items():
                    mime="text/csv" if name.endswith(".csv") else ("application/pdf" if name.endswith(".pdf") else ("text/html" if name.endswith(".html") else "image/png"))
                    st.download_button(f"Telecharger {name}",content,file_name=name,mime=mime,key=name)

            if run_bt:
                st.subheader("Backtest exploratoire : validation scientifique en cours")
                st.info("Les notebooks d'origine sont archives dans le depot. Le nouveau backtest exclut la selection avec cours futurs et suit les poids qui derivent entre rebalancements ; il est donc DIFFERENT de l'ancien backtest.")
                try:
                    bt_nav, bt_metrics, bt_states, bt_lo, bt_ls, bt_exports = calculate_backtest(
                        upload.getvalue(), tuple(sorted(selected)), bt_start.isoformat(),
                        int(bt_hold), int(bt_periods), float(bt_fees))
                except Exception as exc:
                    st.error(f"Backtest impossible : {exc}")
                else:
                    st.dataframe(bt_metrics, use_container_width=True, hide_index=True)
                    st.line_chart(bt_nav.set_index("date")[["nav_long_only", "nav_long_short"]], use_container_width=True)
                    with st.expander("Signaux, positions et historique"):
                        st.dataframe(bt_states, use_container_width=True, hide_index=True)
                        st.dataframe(bt_lo, use_container_width=True, hide_index=True)
                        st.dataframe(bt_ls, use_container_width=True, hide_index=True)
                    for name, content in bt_exports.items():
                        mime = "text/csv" if name.endswith(".csv") else "image/png"
                        st.download_button(f"Telecharger {name}", content, file_name=name, mime=mime, key="bt_" + name)
