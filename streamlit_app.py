"""Interface Streamlit - LPPLS (snapshot historique, sans backtest)."""
import os
import sys
import tempfile
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from lppls_bubble import DEFAULT_WINDOWS, run_snapshot
from lppls_bubble.reports import make_html, make_pdf

st.set_page_config(page_title="LPPLS Bubble Detection", page_icon="📉", layout="wide")
st.title("LPPLS - Detection de bulles multi-echelles")
st.caption("Version de demarrage : moteur historique Colab du 27 fevrier 2026. Backtest en attente de recuperation.")
st.warning("Les signaux LPPLS sont exploratoires : ils ne sont pas des probabilites fiables de retournement.")

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

with st.form("input_form"):
    upload = st.file_uploader("CSV de cours (format historique : trois lignes d'entete, colonnes Name et valeurs)",type="csv")
    selected = st.multiselect("Fenetres hebdomadaires", list(DEFAULT_WINDOWS), default=list(DEFAULT_WINDOWS))
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
