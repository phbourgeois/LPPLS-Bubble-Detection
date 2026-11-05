"""Autonomous HTML/PDF backtest reports built from the same calculation run."""
from __future__ import annotations

import base64
from html import escape
from pathlib import Path
from io import BytesIO
import pandas as pd


def _performance_table(metrics: pd.DataFrame) -> pd.DataFrame:
    m = metrics.iloc[0]
    keys = [
        ("total_return", "Performance cumulée"),
        ("annualized_return", "Rendement annualisé"),
        ("annualized_volatility", "Volatilité annualisée"),
        ("sharpe", "Sharpe annualisé (rf=0)"),
        ("max_drawdown", "Drawdown maximal (valeur positive)"),
        ("turnover_mean", "Turnover moyen par décision"),
        ("max_single_asset_weight", "Plus forte position individuelle observée"),
    ]
    rows = []
    for key, label in keys:
        def fmt(sleeve: str) -> str:
            value = m.get(key + "_" + sleeve, float("nan"))
            if pd.isna(value):
                return "n.d."
            return f"{value:.3f}" if key == "sharpe" else f"{value*100:.2f} %"
        rows.append({"Mesure": label, "Long-only": fmt("long_only"), "Long/Short": fmt("long_short")})
    return pd.DataFrame(rows)


def _largest_contributions(attribution: pd.DataFrame, limit: int = 15) -> pd.DataFrame:
    if attribution.empty:
        return attribution
    frame = attribution.copy()
    frame["_abs"] = frame.return_contribution.abs()
    return frame.nlargest(limit, "_abs")[[
        "date", "strategy", "asset", "weight_before_return", "asset_return", "return_contribution"
    ]]


def write_backtest_reports(result: dict) -> None:
    """Write backtest_report.html and backtest_report.pdf to the ZIP backtest folder."""
    output = Path(result["output_dir"])
    metrics, nav = result["metrics"], result["nav"]
    attribution, reconciliation = result["attribution"], result["reconciliation"]
    alerts = result["quality_weekly_alerts"]
    performance = _performance_table(metrics)
    top = _largest_contributions(attribution)
    concentrations = (
        attribution.assign(abs_weight=attribution.weight_before_return.abs())
        .groupby(["date", "strategy"], as_index=False)["abs_weight"].max()
        .nlargest(14, "abs_weight")
        if not attribution.empty
        else pd.DataFrame(columns=["date", "strategy", "abs_weight"])
    )
    exposures = (
        reconciliation[["date", "strategy", "gross_long_before_return",
                        "gross_short_before_return", "net_exposure_before_return"]]
        .tail(18)
    )
    start, end = str(nav.date.iloc[0]), str(nav.date.iloc[-1])
    n_decisions = int(metrics.num_rebalances.iloc[0])
    max_error = float(reconciliation.reconciliation_error.abs().max())
    warning = (
        f"{len(alerts)} alertes sur l'historique : vérifier les cours ajustés et événements sur titres."
        if len(alerts) else "Aucune alerte au seuil programmé ne garantit pas que les cours soient ajustés."
    )
    graph = base64.b64encode((output / "backtest_nav_plot.png").read_bytes()).decode("ascii")
    def html_table(frame: pd.DataFrame) -> str:
        return frame.to_html(index=False, border=0, escape=True) if not frame.empty else "<p>Aucun événement.</p>"
    style = """
body{font:14px system-ui,Arial,sans-serif;color:#202a38;max-width:1120px;margin:32px auto;padding:0 24px}
h1,h2{color:#143a60}h2{border-bottom:1px solid #d9e2eb;padding-bottom:7px;margin-top:30px}
table{border-collapse:collapse;width:100%;font-size:12px;margin:16px 0 28px}
td,th{border:1px solid #c9d5df;padding:7px;text-align:left}th{background:#e8eff6}
tr:nth-child(even){background:#f6f9fc}img{max-width:100%;height:auto}
.note{background:#edf2f7;padding:12px;border-left:4px solid #829ab0}p{line-height:1.5}
"""
    html = f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<title>LPPLS - Rapport du backtest</title><style>{style}</style></head><body>
<h1>LPPLS - Rapport autonome du backtest</h1>
<p class="note"><b>Résultats exploratoires, non validés scientifiquement.</b> Les cours ne sont pas certifiés ajustés de toutes les opérations sur titres ; les alertes ne prouvent pas une erreur.</p>
<h2>1. Chronologie effective et hypothèses</h2>
<p><b>Du {escape(start)} au {escape(end)}</b> ; {len(nav)-1} rendements hebdomadaires et {n_decisions} décisions.
Les décisions à t utilisent seulement les prix jusqu'à t ; les positions influencent les rendements à partir de t+1.
Les titres sont détenus et les poids dérivent entre rééquilibrages.</p>
<p>Pondération acheteuse inverse de la volatilité hebdomadaire des 52 dernières semaines ; ventes à découvert pondérées par score LPPLS.
Frais de transaction paramétrés : {float(metrics.fees_bps.iloc[0]):.3f} points de base. Financement/emprunt des titres shorts non modélisés.</p>
<h2>2. Rendement et risque</h2>{html_table(performance)}
<h2>3. Évolution des deux NAV</h2><img alt="NAV Long-only et Long/Short" src="data:image/png;base64,{graph}">
<h2>4. Attribution des rendements</h2>
<p>Contribution hebdomadaire de chaque titre = poids avant rendement × rendement du titre.
Les frais sont comptabilisés séparément, y compris l'effet de leur application après rendement.
Écart maximal de rapprochement aux NAV : <b>{max_error:.3g}</b>.</p>
<h3>Principales contributions absolues</h3>{html_table(top)}
<h2>5. Qualité des données : observations hebdomadaires</h2>
<p class="note">{escape(warning)} Les alertes sont enregistrées même entre les dates de rééquilibrage.
Aucune observation extrême n'est exclue ou corrigée automatiquement.</p>
{html_table(alerts.head(50))}
<h2>6. Expositions et concentration</h2>
<p>Les expositions acheteuses et vendeuses sont mesurées avant les rendements de chaque semaine ;
les poids peuvent dériver même sans transaction. Le tableau de concentration retient la plus grande
position individuelle en valeur absolue.</p>
<h3>Concentrations les plus élevées</h3>{html_table(concentrations)}
<h3>Dernières expositions hebdomadaires</h3>{html_table(exposures)}
<h2>7. Risques et limites</h2>
<p>Les hausses exceptionnelles peuvent créer une forte concentration entre deux décisions malgré une pondération initiale inverse-volatilité.
La performance ne représente pas nécessairement un portefeuille investissable : prix ajustés, composition historique de l'univers, coût d'emprunt et traitement des radiations restent à certifier.</p>
<p>Les règles non tranchées (plafonds, quarantaine, pondération des shorts harmonisée et stratégie MIXED_SCALES) ne sont pas appliquées.</p>
<h2>8. Fichiers pour audit</h2>
<p>backtest_nav_weekly.csv ; backtest_attribution_weekly.csv ; backtest_reconciliation.csv ;
backtest_quality_weekly_alerts.csv ; backtest_summary_metrics.csv ; backtest_portfolios_*_weights.csv.</p>
</body></html>"""
    (output / "backtest_report.html").write_text(html, encoding="utf-8")

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak
    from xml.sax.saxutils import escape as xml_escape

    doc_bytes = BytesIO()
    doc = SimpleDocTemplate(doc_bytes, pagesize=A4, topMargin=35, bottomMargin=35,
                            leftMargin=35, rightMargin=35)
    styles = getSampleStyleSheet()
    elements = []
    def paragraph(message: str, style: str = "Normal"):
        # Paragraph formatting is intentionally plain for PDF reader portability.
        elements.extend([Paragraph(xml_escape(str(message)), styles[style]), Spacer(1, 9)])
    def pdf_table(frame: pd.DataFrame, columns: list[str] | None = None, n: int = 20):
        f = frame.head(n)
        if columns:
            f = f[columns]
        if f.empty:
            paragraph("Aucune observation.")
            return
        data = [[str(x) for x in f.columns]]
        data.extend([[str(x)[:32] for x in record] for record in f.itertuples(index=False, name=None)])
        widths = [520.0 / len(data[0])] * len(data[0])
        t = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
        t.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#244766")),
            ("TEXTCOLOR",(0,0),(-1,0),colors.white),
            ("GRID",(0,0),(-1,-1),.3,colors.HexColor("#bfccd9")),
            ("FONTSIZE",(0,0),(-1,-1),6.2),
            ("VALIGN",(0,0),(-1,-1),"TOP"),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#f4f7fa")]),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 12))
    paragraph("LPPLS - Rapport autonome du backtest", "Title")
    paragraph("Résultats exploratoires ; données non certifiées ajustées. Aucun signal de trading validé.")
    paragraph(f"Période réelle : {start} - {end} ; {n_decisions} décisions.", "Heading2")
    paragraph("1. Hypothèses", "Heading2")
    paragraph("Décision à la clôture et application à compter de la semaine suivante ; conservation des titres entre les décisions ; achats inverse-volatilité, shorts score LPPLS.")
    paragraph(f"Frais paramétrés : {float(metrics.fees_bps.iloc[0]):.3f} points de base ; pas de coût d'emprunt short.")
    paragraph("2. Performances", "Heading2")
    pdf_table(performance, n=len(performance))
    paragraph("3. Comparaison des NAV", "Heading2")
    elements.append(Image(str(output / "backtest_nav_plot.png"), width=500, height=250, kind="proportional"))
    elements.append(PageBreak())
    paragraph("4. Contrôle qualité des séries", "Heading2")
    paragraph(warning)
    paragraph("Aucune correction ou exclusion automatique n'est appliquée aux observations extrêmes.")
    pdf_table(alerts, columns=["date","asset","observed_weekly_return","severity"], n=28)
    elements.append(PageBreak())
    paragraph("5. Contributions et rapprochement", "Heading2")
    paragraph(f"Écart maximal entre attribution et rendement net : {max_error:.3g}. Les contributions individuelles et les frais se réconcilient avec les NAV.")
    pdf_table(top, columns=["date","strategy","asset","return_contribution"], n=20)
    elements.append(PageBreak())
    paragraph("6. Expositions et concentration", "Heading2")
    paragraph("Les poids dérivent entre décisions ; expositions calculées avant les rendements hebdomadaires.")
    pdf_table(concentrations, columns=["date", "strategy", "abs_weight"], n=14)
    paragraph("7. Limites et questions ouvertes", "Heading2")
    for notice in [
        "Prix ajustés, distributions et éventuelles radiations : non certifiés.",
        "Les alertes sur variations extrêmes ne prouvent pas une erreur de données.",
        "La concentration peut augmenter entre deux rééquilibrages.",
        "Les coûts de financement et d'emprunt des titres vendus à découvert ne sont pas modélisés.",
        "Plafonds, quarantaine, poids des shorts harmonisés et variantes MIXED_SCALES : en suspens.",
        "Les principaux CSV permettent de reproduire les performances et le contrôle qualité.",
    ]:
        paragraph("- " + notice)
    doc.build(elements)
    (output / "backtest_report.pdf").write_bytes(doc_bytes.getvalue())
