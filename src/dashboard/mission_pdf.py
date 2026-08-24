"""
Génération PDF : ORDRE DE MISSION (portrait) + FEUILLE DE ROUTE
(paysage, une par personne à bord), fidèles au modèle World Vision.
Logo : déposez logo_wv.png dans src/dashboard/assets/
"""
import io
from datetime import timedelta
from pathlib import Path

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (BaseDocTemplate, Frame, Image as RLImage,
                                NextPageTemplate, PageBreak, PageTemplate,
                                Paragraph, Spacer, Table, TableStyle)

ORANGE_WV = colors.HexColor("#F58220")
GRIS = colors.HexColor("#666666")
GRIS_CLAIR = colors.HexColor("#F0F0F0")

_styles = getSampleStyleSheet()
S_TITRE = ParagraphStyle("t", parent=_styles["Title"], fontSize=17, spaceAfter=6)
S_TITRE_FR = ParagraphStyle("tf", parent=_styles["Title"], fontSize=15,
                            textColor=ORANGE_WV, spaceAfter=4)
S_WV = ParagraphStyle("wv", parent=_styles["Normal"], fontSize=16,
                      alignment=2, textColor=colors.black,
                      fontName="Helvetica-Bold")
S_NORM = ParagraphStyle("n", parent=_styles["Normal"], fontSize=9)
S_PIED = ParagraphStyle("p", parent=_styles["Normal"], fontSize=7,
                        textColor=GRIS, alignment=2)

ASSETS = Path(__file__).resolve().parent / "assets"
LOGO_CANDIDATS = [ASSETS / "logo_wv.png", ASSETS / "logo_wv.jpg",
                  ASSETS / "logo.png", ASSETS / "logo.jpg"]


def _logo(hauteur_mm=11):
    """Logo World Vision si un fichier existe dans assets/, sinon texte."""
    for p in LOGO_CANDIDATS:
        if p.exists():
            iw, ih = ImageReader(str(p)).getSize()
            h = hauteur_mm * mm
            img = RLImage(str(p), width=h * iw / ih, height=h)
            img.hAlign = "RIGHT"
            return img
    return Paragraph("World Vision", S_WV)


def _tbl_champs(paires, largeurs):
    t = Table(paires, colWidths=largeurs)
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def _fmt_dt(x, avec_heure=True):
    d = pd.to_datetime(x, errors="coerce")
    if pd.isna(d):
        return "—"
    return d.strftime("%d/%m/%Y %H:%M") if avec_heure else d.strftime("%d/%m/%Y")


def generer_pdf_mission(m: dict, contenu: str = "tout") -> bytes:
    """m : dictionnaire de la mission (champs manquants tolérés).
    contenu : "tout" (ordre + feuilles), "ordre" seul, "feuille" seule(s)."""
    buf = io.BytesIO()
    premiere_paysage = (contenu == "feuille")
    doc = BaseDocTemplate(buf,
                          pagesize=landscape(A4) if premiere_paysage else A4,
                          leftMargin=18 * mm, rightMargin=18 * mm,
                          topMargin=14 * mm, bottomMargin=12 * mm)
    l_w, l_h = landscape(A4)
    f_port = Frame(18 * mm, 12 * mm, A4[0] - 36 * mm, A4[1] - 26 * mm, id="fp")
    f_land = Frame(14 * mm, 10 * mm, l_w - 28 * mm, l_h - 22 * mm, id="fl")
    tpl_port = PageTemplate(id="portrait", frames=[f_port], pagesize=A4)
    tpl_land = PageTemplate(id="paysage", frames=[f_land],
                            pagesize=landscape(A4))
    doc.addPageTemplates([tpl_land, tpl_port] if premiere_paysage
                         else [tpl_port, tpl_land])

    def g(k, defaut="—"):
        v = m.get(k)
        if v is None or v == "":
            return defaut
        if isinstance(v, float) and pd.isna(v):
            return defaut
        return str(v)

    numero = g("numero_mission", g("mission_id"))
    trajet = f"{g('origine')} → {g('destination')}"
    periode = f"{_fmt_dt(m.get('date_depart'))} → {_fmt_dt(m.get('date_fin'))}"
    vehicule = g("vehicule_label", g("vehicule_id"))
    personnes = [p.strip() for p in str(m.get("personnes_a_bord") or
                                        g("agent_principal", "")).split(",")
                 if p.strip()] or ["—"]

    story = []
    largeur_port = A4[0] - 36 * mm

    # ══ ORDRE DE MISSION (si demandé) ═════════════════════════════════
    if contenu in ("tout", "ordre"):
        story.append(_logo())
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph("ORDRE DE MISSION", S_TITRE))
        story.append(Spacer(1, 3 * mm))

        largeurs = [45 * mm, largeur_port - 45 * mm]
        story.append(_tbl_champs([
            ["N° de mission", numero],
            ["Statut", g("statut", "Pending")],
            ["Objet", g("objet")],
            ["Département", g("departement")],
            ["Imputation", g("imputation")],
        ], largeurs))
        story.append(Spacer(1, 4 * mm))
        story.append(_tbl_champs([
            ["Agent principal", g("agent_principal")],
            ["Fonction / Tél.", f"{g('fonction_agent')} / {g('telephone_agent')}"],
            ["Trajet", trajet],
            ["Période", periode],
            ["Véhicule", vehicule],
            ["Chauffeur", g("chauffeur_label", g("chauffeur_id"))],
        ], largeurs))
        story.append(Spacer(1, 4 * mm))
        story.append(_tbl_champs([["Personnes à bord", ", ".join(personnes)]],
                                 largeurs))
        story.append(Spacer(1, 3 * mm))
        story.append(_tbl_champs([["Observations", g("observations", "")]],
                                 largeurs))
        story.append(Spacer(1, 6 * mm))

        story.append(Paragraph("<b>Approbateur</b>", ParagraphStyle(
            "ap", parent=_styles["Normal"], alignment=1, fontSize=11)))
        story.append(Spacer(1, 2 * mm))
        boite = Table([
            [Paragraph(f"Nom : {g('approbateur')}", S_NORM)],
            [Paragraph(f"Date d'approbation : "
                       f"{_fmt_dt(m.get('date_approbation'))}", S_NORM)],
            [Paragraph("Signature :", S_NORM)],
            [Spacer(1, 10 * mm)],
        ], colWidths=[largeur_port])
        boite.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.8, GRIS),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(boite)
        story.append(Spacer(1, 8 * mm))
        story.append(Paragraph(
            f"Généré le {pd.Timestamp.now():%d/%m/%Y %H:%M} — {numero}", S_PIED))

    # ══ FEUILLES DE ROUTE ═════════════════════════════════════════════
    d1 = pd.to_datetime(m.get("date_depart"), errors="coerce")
    d2 = pd.to_datetime(m.get("date_fin"), errors="coerce")
    if pd.isna(d1):
        d1 = pd.Timestamp.today().normalize()
    if pd.isna(d2) or d2 < d1:
        d2 = d1 + timedelta(days=int(m.get("duree_jours", 1) or 1) - 1)
    jours = pd.date_range(d1.normalize(), d2.normalize(), freq="D")[:10]

    mois_fr = ["", "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
               "Juillet", "Août", "Septembre", "Octobre", "Novembre",
               "Décembre"]

    personnes_feuilles = [] if contenu == "ordre" else personnes

    for i_pers, pers in enumerate(personnes_feuilles):
        if not (contenu == "feuille" and i_pers == 0):
            story.append(NextPageTemplate("paysage"))
            story.append(PageBreak())
        larg = l_w - 28 * mm

        entete = Table([[Paragraph("FEUILLE DE ROUTE", S_TITRE_FR), _logo(9)]],
                       colWidths=[larg * 0.6, larg * 0.4])
        story.append(entete)
        story.append(Spacer(1, 2 * mm))

        infos = Table([
            [Paragraph(f"<b>Numéro :</b> <font color='#F58220'><b>{numero}"
                       f"</b></font>", S_NORM),
             Paragraph(f"<b>Fonction :</b> {g('fonction_agent')}", S_NORM)],
            [Paragraph(f"<b>Prénoms et noms :</b> {pers}", S_NORM),
             Paragraph(f"<b>Mois :</b> {mois_fr[d1.month]} {d1.year}", S_NORM)],
            [Paragraph(f"<b>Trajet :</b> {trajet}", S_NORM),
             Paragraph(f"<b>FY :</b> {d1.year + (1 if d1.month >= 10 else 0)}",
                       S_NORM)],
        ], colWidths=[larg * 0.55, larg * 0.45])
        story.append(infos)
        story.append(Spacer(1, 3 * mm))

        entetes = [["", "Départ", "", "Visa /\nSignature",
                    "Arrivée", "", "Visa /\nSignature", "Observations"],
                   ["Date", "Lieu", "Heure", "", "Lieu", "Heure", "", ""]]
        lignes = [[j.strftime("%d/%m/%Y"), "", "", "", "", "", "", ""]
                  for j in jours]
        lignes += [["", "", "", "", "", "", "", ""]] * (10 - len(lignes))
        cw = [larg * x for x in (0.11, 0.14, 0.07, 0.10, 0.14, 0.07, 0.10, 0.27)]
        t = Table(entetes + lignes, colWidths=cw,
                  rowHeights=[7 * mm, 6 * mm] + [7.4 * mm] * 10)
        t.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#AAAAAA")),
            ("BACKGROUND", (0, 0), (-1, 1), GRIS_CLAIR),
            ("FONTNAME", (0, 0), (-1, 1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ALIGN", (0, 0), (-1, 1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("SPAN", (1, 0), (2, 0)), ("SPAN", (4, 0), (5, 0)),
            ("SPAN", (3, 0), (3, 1)), ("SPAN", (6, 0), (6, 1)),
            ("SPAN", (7, 0), (7, 1)), ("SPAN", (0, 0), (0, 1)),
        ]))
        story.append(t)
        story.append(Spacer(1, 5 * mm))

        perd = Table([["Perdiem", "Taux", "Nombre", "Montant"],
                      ["Petit déjeuner", "0", "0", "0"],
                      ["Déjeuner", "0", "0", "0"],
                      ["Dîner", "0", "0", "0"],
                      ["Nuitée", "0", "0", "0"],
                      ["Férié", "0", "0", "0"],
                      ["Total", "", "", "0"]],
                     colWidths=[34 * mm, 20 * mm, 20 * mm, 22 * mm])
        perd.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#AAAAAA")),
            ("BACKGROUND", (0, 0), (-1, 0), GRIS_CLAIR),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ]))
        sign = Table([["Prepared by :", ""],
                      ["Approved by :", ""],
                      ["Received by :", ""]],
                     colWidths=[30 * mm, 60 * mm], rowHeights=[8 * mm] * 3)
        sign.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#AAAAAA")),
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        cote = Table([[perd, sign]], colWidths=[100 * mm, larg - 100 * mm])
        cote.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(cote)
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph(
            f"Généré le {pd.Timestamp.now():%d/%m/%Y %H:%M} — {numero} — {pers}",
            S_PIED))

    doc.build(story)
    return buf.getvalue()