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
    context = result.get("report_context") or {}
    comparison = result.get("comparison")
    excluded = pd.DataFrame(context.get("excluded_assets", []))
    if excluded.empty:
        excluded = pd.DataFrame(columns=["asset", "scope", "classification"])
    study_type = str(context.get("study_type", "UNDECLARED_SOURCE_SCOPE"))
    asset_summary = (
        f"Source : {context.get('source_asset_count', 'n.d.')} actifs ; "
        f"snapshot : {context.get('snapshot_assets', 'n.d.')} ; "
        f"backtest : {context.get('backtest_assets', 'n.d.')}."
    )
    comparison_table = pd.DataFrame()
    comparison_plot = ""
    if comparison is not None:
        comparison_table = comparison["metrics"][[
            "strategy", "total_return", "annualized_return",
            "annualized_volatility", "sharpe_rf_zero", "max_drawdown",
        ]].copy()
        for col in ("total_return", "annualized_return",
                    "annualized_volatility", "max_drawdown"):
            comparison_table[col] = comparison_table[col].map(
                lambda x: f"{100*x:+.2f} %" if pd.notna(x) else "n.d."
            )
        comparison_table["sharpe_rf_zero"] = comparison_table["sharpe_rf_zero"].map(
            lambda x: f"{x:.3f}" if pd.notna(x) else "n.d."
        )
        comparison_plot = base64.b64encode(
            (output / "backtest_comparison_nav.png").read_bytes()
        ).decode("ascii")
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
<h2>2. Univers, exclusions et nature de l'étude</h2>
<p class="note"><b>Statut : {escape(study_type)}.</b> {escape(asset_summary)}
Les exclusions rétrospectives reposent sur des événements observés sur la période entière :
elles ne sont PAS une règle investissable en temps réel et ne doivent pas être confondues
avec un filtrage causal aux dates de décision.</p>
<h3>Titres exclus</h3>{html_table(excluded)}
<p>Le snapshot LPPLS peut conserver des titres retirés uniquement du backtest ;
ses portefeuilles instantanés ne représentent alors pas l'univers effectivement testé.</p>
<h2>3. Rendement et risque des stratégies historiques</h2>{html_table(performance)}
<h2>4. Évolution des deux NAV historiques</h2><img alt="NAV Long-only et Long/Short" src="data:image/png;base64,{graph}">
<h2>5. Benchmark et variantes MIXED_SCALES</h2>
<p>Benchmark équipondéré sur les mêmes titres éligibles avec au moins 104 semaines
de cours, aux mêmes décisions que les stratégies originales, avec les mêmes frais.
Il ne s'agit pas du SBF 120 total-return ni d'un indice de marché officiel.</p>
<p>Variantes mixtes : achat en cas de COHERENT_DOWN ou court UP / long DOWN ;
vente en cas de COHERENT_UP ou court DOWN / long UP.
Les autres MIXED ne participent pas aux nouvelles stratégies.
Achats pondérés par inverse-volatilité 52 semaines ; shorts pondérés selon
priority_score LPPLS. Poche acheteuse et vendeuse 50/50 lorsque des shorts
sont présents, comme le modèle original. Aucune limite de poids nouvelle.</p>
<p>Cette comparaison est exploratoire et ne prouve pas la capacité prédictive des signaux.</p>
{html_table(comparison_table)}
{f'<img alt="Comparaison cinq NAV" src="data:image/png;base64,{comparison_plot}">' if comparison_plot else ''}
<h2>6. Attribution des rendements</h2>
<p>Contribution hebdomadaire de chaque titre = poids avant rendement × rendement du titre.
Les frais sont comptabilisés séparément, y compris l'effet de leur application après rendement.
Écart maximal de rapprochement aux NAV : <b>{max_error:.3g}</b>.</p>
<h3>Principales contributions absolues</h3>{html_table(top)}
<h2>7. Qualité des données : observations hebdomadaires</h2>
<p class="note">{escape(warning)} Les alertes sont enregistrées même entre les dates de rééquilibrage.
Aucune observation extrême n'est exclue ou corrigée automatiquement.</p>
{html_table(alerts.head(50))}
<h2>8. Expositions et concentration</h2>
<p>Les expositions acheteuses et vendeuses sont mesurées avant les rendements de chaque semaine ;
les poids peuvent dériver même sans transaction. Le tableau de concentration retient la plus grande
position individuelle en valeur absolue.</p>
<h3>Concentrations les plus élevées</h3>{html_table(concentrations)}
<h3>Dernières expositions hebdomadaires</h3>{html_table(exposures)}
<h2>9. Risques et limites</h2>
<p>Les hausses exceptionnelles peuvent créer une forte concentration entre deux décisions malgré une pondération initiale inverse-volatilité.
La performance ne représente pas nécessairement un portefeuille investissable : prix ajustés, composition historique de l'univers, coût d'emprunt et traitement des radiations restent à certifier.</p>
<p>Les plafonds, quarantaines et pondérations harmonisées des shorts ne sont pas appliqués. Les variantes MIXED_SCALES sont comparées à titre expérimental, sans remplacer les stratégies historiques.</p>
<h2>10. Fichiers pour audit</h2>
<p>backtest_nav_weekly.csv ; backtest_attribution_weekly.csv ; backtest_reconciliation.csv ;
backtest_quality_weekly_alerts.csv ; backtest_summary_metrics.csv ; backtest_portfolios_*_weights.csv ; backtest_comparison_*.csv ; backtest_comparison_nav.png.</p>
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
    paragraph("2. Univers et exclusions", "Heading2")
    paragraph(f"Statut: {study_type}. {asset_summary}")
    paragraph("Les exclusions retrospectivement decidees ne constituent PAS une regle sans anticipation. Les portefeuilles instantanes LPPLS peuvent conserver des titres exclus du backtest.")
    pdf_table(excluded, columns=["asset", "scope", "classification"], n=30)
    paragraph("3. Performances historiques", "Heading2")
    pdf_table(performance, n=len(performance))
    paragraph("4. Benchmark et signaux MIXED_SCALES", "Heading2")
    paragraph("Benchmark: equipondere sur les titres eligibles du MEME univers, avec les MEMES dates et frais. Ce n'est pas un indice officiel.")
    paragraph("Signaux mixtes: achat court UP/long DOWN ; vente court DOWN/long UP. Les autres MIXED sont exclus des nouvelles poches. Ponderations d'origine preservees.")
    if not comparison_table.empty:
        pdf_metrics = comparison_table[[
            "strategy", "total_return", "annualized_volatility",
            "sharpe_rf_zero", "max_drawdown",
        ]].rename(columns={
            "strategy": "Scenario", "total_return": "Rend. total",
            "annualized_volatility": "Vol. ann.",
            "sharpe_rf_zero": "Sharpe", "max_drawdown": "Drawdown",
        })
        pdf_table(pdf_metrics, n=10)
    if comparison_plot:
        elements.append(Image(str(output / "backtest_comparison_nav.png"),
                              width=500, height=250, kind="proportional"))
    elements.append(PageBreak())
    paragraph("5. Comparaison des NAV historiques", "Heading2")
    elements.append(Image(str(output / "backtest_nav_plot.png"), width=500, height=250, kind="proportional"))
    elements.append(PageBreak())
    paragraph("6. Contrôle qualité des séries", "Heading2")
    paragraph(warning)
    paragraph("Aucune correction ou exclusion automatique n'est appliquée aux observations extrêmes.")
    pdf_table(alerts, columns=["date","asset","observed_weekly_return","severity"], n=28)
    elements.append(PageBreak())
    paragraph("7. Contributions et rapprochement", "Heading2")
    paragraph(f"Écart maximal entre attribution et rendement net : {max_error:.3g}. Les contributions individuelles et les frais se réconcilient avec les NAV.")
    pdf_table(top, columns=["date","strategy","asset","return_contribution"], n=20)
    elements.append(PageBreak())
    paragraph("8. Expositions et concentration", "Heading2")
    paragraph("Les poids dérivent entre décisions ; expositions calculées avant les rendements hebdomadaires.")
    pdf_table(concentrations, columns=["date", "strategy", "abs_weight"], n=14)
    paragraph("9. Limites et questions ouvertes", "Heading2")
    for notice in [
        "Prix ajustés, distributions et éventuelles radiations : non certifiés.",
        "Les alertes sur variations extrêmes ne prouvent pas une erreur de données.",
        "La concentration peut augmenter entre deux rééquilibrages.",
        "Les coûts de financement et d'emprunt des titres vendus à découvert ne sont pas modélisés.",
        "Plafonds, quarantaine et poids des shorts harmonises : en suspens ; MIXED_SCALES comparees seulement comme variantes experimentales.",
        "Les principaux CSV permettent de reproduire les performances et le contrôle qualité.",
    ]:
        paragraph("- " + notice)
    doc.build(elements)
    (output / "backtest_report.pdf").write_bytes(doc_bytes.getvalue())
