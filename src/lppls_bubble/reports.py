"""Rapports autonomes produits a partir des sorties de la meme execution."""
from __future__ import annotations

import base64
from html import escape
from io import BytesIO
from datetime import datetime, timezone


def make_html(result: dict) -> bytes:
    import pandas as pd
    bubble = result["bubble_type"].copy()
    portfolio = result["portfolio"].copy()
    heatmap = base64.b64encode(result["heatmap_path"].read_bytes()).decode("ascii")
    tables = [("Classification des bulles", bubble), ("Construction de portefeuille", portfolio),
              ("Details par fenetre", result["details"]), ("Synthese multi-echelles", result["summary"])]
    items = []
    for heading, frame in tables:
        items.append(f'<h2>{escape(heading)}</h2>')
        items.append(frame.to_html(index=False, border=0, classes="data", escape=True))
    html = f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<title>LPPLS - Rapport d'analyse</title><style>
body{{font:14px system-ui, sans-serif;max-width:1200px;margin:32px auto;padding:0 22px;color:#182538}}
h1,h2{{color:#173c65}}.notice{{background:#f2f5f8;padding:14px;border-left:4px solid #7592af}}
img{{max-width:100%;height:auto}}table{{border-collapse:collapse;display:block;overflow:auto;margin:18px 0 34px}}
.data th,.data td{{border:1px solid #cbd5df;padding:7px 10px;text-align:right;white-space:nowrap}}
.data th:first-child,.data td:first-child{{text-align:left}}.data tr:nth-child(even){{background:#f6f9fc}}
</style></head><body><h1>LPPLS - Analyse multi-echelles</h1>
<p class="notice">Grille approfondie LPPLS commune au snapshot et au backtest (343 combinaisons).
Les signaux ne constituent ni des probabilites de crise ni des recommandations d'investissement.
Backtesting historique non inclus dans cette version.</p>
<p>Actifs analyses : {len(bubble)} | Fenetres : {result['details']['window_weeks'].nunique()}</p>
<h2>Heatmap globale</h2><img alt="Heatmap LPPLS" src="data:image/png;base64,{heatmap}">
{''.join(items)}</body></html>"""
    return html.encode("utf-8")


def make_pdf(result: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
    from reportlab.lib.utils import ImageReader
    from xml.sax.saxutils import escape as xml_escape

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=34,leftMargin=34,topMargin=36,bottomMargin=36)
    styles = getSampleStyleSheet()
    elements=[Paragraph("LPPLS - Analyse multi-echelles", styles["Title"]),Spacer(1,10),
       Paragraph("Grille LPPLS approfondie commune au snapshot et au backtest (343 combinaisons). Les classifications ne sont pas des probabilites de retournement. Backtest non inclus dans ce rapport.",styles["Normal"]),Spacer(1,14)]
    bubble=result["bubble_type"]
    elements.append(Paragraph(f"Actifs analyses : {len(bubble)}",styles["Heading2"]))
    cols=["asset","bubble_multiscale_state","priority_score"]
    rows=[cols]+[[str(row.get(k,""))[:34] for k in cols] for _,row in bubble.head(25).iterrows()]
    table=Table(rows,colWidths=[145,245,105],repeatRows=1,hAlign="LEFT")
    table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#234567")),("TEXTCOLOR",(0,0),(-1,0),colors.white),
       ("FONTSIZE",(0,0),(-1,-1),7),("BOTTOMPADDING",(0,0),(-1,-1),5),
       ("GRID",(0,0),(-1,-1),0.25,colors.HexColor("#ccd5df")),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#f2f6fa")])]))
    elements.extend([table,Spacer(1,14),Paragraph("Heatmap globale",styles["Heading2"])])
    from PIL import Image as PILImage
    im=PILImage.open(result["heatmap_path"])
    width,height=im.size
    max_w,max_h=500,580
    ratio=min(max_w/width,max_h/height)
    elements.append(Image(str(result["heatmap_path"]),width=width*ratio,height=height*ratio))
    doc.build(elements)
    return buf.getvalue()
