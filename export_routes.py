# ============================================================
# Ajouter ces imports EN HAUT de app.py (avec les autres)
# ============================================================
import csv
import io
from datetime import datetime
from flask import make_response
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.enums import TA_CENTER, TA_LEFT


# ============================================================
# EXPORT CSV — produits
# GET /export/csv/produits
# ============================================================
@app.route('/export/csv/produits')
@login_required
def export_csv_produits():
    with get_db() as conn:
        produits = conn.execute(
            "SELECT id, nom, quantite, prix, seuil FROM produits ORDER BY nom"
        ).fetchall()

    # Construire le CSV en mémoire
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')

    # En-têtes
    writer.writerow(['ID', 'Nom', 'Quantité', 'Prix (€)', 'Seuil alerte', 'Statut'])

    # Lignes
    for p in produits:
        if p['quantite'] == 0:
            statut = 'Rupture'
        elif p['quantite'] <= p['seuil']:
            statut = 'Stock faible'
        else:
            statut = 'OK'

        writer.writerow([
            p['id'],
            p['nom'],
            p['quantite'],
            f"{p['prix']:.2f}",
            p['seuil'],
            statut,
        ])

    # Préparer la réponse HTTP
    date_str = datetime.now().strftime('%Y%m%d_%H%M')
    filename = f"stock_produits_{date_str}.csv"

    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8-sig'  # utf-8-sig = BOM pour Excel
    response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


# ============================================================
# EXPORT CSV — historique des mouvements
# GET /export/csv/mouvements
# ============================================================
@app.route('/export/csv/mouvements')
@login_required
def export_csv_mouvements():
    with get_db() as conn:
        mouvements = conn.execute(
            "SELECT date, produit_nom, type, quantite, note FROM mouvements ORDER BY date DESC, id DESC"
        ).fetchall()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['Date', 'Produit', 'Type', 'Quantité', 'Note'])

    for m in mouvements:
        writer.writerow([
            m['date'],
            m['produit_nom'],
            'Entrée' if m['type'] == 'entree' else 'Sortie',
            m['quantite'],
            m['note'] or '',
        ])

    date_str = datetime.now().strftime('%Y%m%d_%H%M')
    filename = f"stock_mouvements_{date_str}.csv"

    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8-sig'
    response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


# ============================================================
# EXPORT PDF — rapport complet du stock
# GET /export/pdf/stock
# ============================================================
@app.route('/export/pdf/stock')
@login_required
def export_pdf_stock():
    with get_db() as conn:
        produits = conn.execute(
            "SELECT * FROM produits ORDER BY nom"
        ).fetchall()

    # Buffer en mémoire
    buffer = io.BytesIO()

    # Document A4
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=15*mm,
        leftMargin=15*mm,
        topMargin=20*mm,
        bottomMargin=15*mm,
    )

    styles = getSampleStyleSheet()
    story  = []

    # ── Titre ──
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Title'],
        fontSize=20,
        spaceAfter=4,
        textColor=colors.HexColor('#1A1A18'),
        alignment=TA_LEFT,
    )
    sub_style = ParagraphStyle(
        'Sub',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#7A7870'),
        spaceAfter=14,
    )
    story.append(Paragraph("Rapport de stock", title_style))
    story.append(Paragraph(
        f"Généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')} · par {current_user.username}",
        sub_style
    ))

    # ── Métriques résumées ──
    total     = len(produits)
    valeur    = sum(p['quantite'] * p['prix'] for p in produits)
    nb_alerte = sum(1 for p in produits if 0 < p['quantite'] <= p['seuil'])
    nb_rupture= sum(1 for p in produits if p['quantite'] == 0)

    kpi_data = [
        ['Références', 'Valeur totale', 'Alertes stock', 'Ruptures'],
        [
            str(total),
            f"{valeur:,.0f} €".replace(',', ' '),
            str(nb_alerte),
            str(nb_rupture),
        ]
    ]
    kpi_table = Table(kpi_data, colWidths=[42*mm, 52*mm, 42*mm, 42*mm])
    kpi_table.setStyle(TableStyle([
        ('BACKGROUND',  (0,0), (-1,0), colors.HexColor('#F5F4F0')),
        ('BACKGROUND',  (0,1), (-1,1), colors.white),
        ('TEXTCOLOR',   (0,0), (-1,0), colors.HexColor('#7A7870')),
        ('TEXTCOLOR',   (0,1), (-1,1), colors.HexColor('#1A1A18')),
        ('FONTNAME',    (0,0), (-1,0), 'Helvetica'),
        ('FONTNAME',    (0,1), (-1,1), 'Helvetica-Bold'),
        ('FONTSIZE',    (0,0), (-1,0), 8),
        ('FONTSIZE',    (0,1), (-1,1), 18),
        ('ALIGN',       (0,0), (-1,-1), 'CENTER'),
        ('VALIGN',      (0,0), (-1,-1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0,0), (-1,-1), [colors.HexColor('#F5F4F0'), colors.white]),
        ('BOX',         (0,0), (-1,-1), 0.5, colors.HexColor('#DDDBD4')),
        ('INNERGRID',   (0,0), (-1,-1), 0.5, colors.HexColor('#DDDBD4')),
        ('TOPPADDING',  (0,0), (-1,-1), 6),
        ('BOTTOMPADDING',(0,0),(-1,-1), 6),
    ]))
    story.append(kpi_table)
    story.append(Spacer(1, 10*mm))

    # ── Tableau des produits ──
    section_style = ParagraphStyle(
        'Section',
        parent=styles['Heading2'],
        fontSize=12,
        textColor=colors.HexColor('#1A1A18'),
        spaceBefore=6,
        spaceAfter=6,
    )
    story.append(Paragraph("Liste des produits", section_style))

    # En-têtes + données
    header = ['Nom', 'Quantité', 'Seuil', 'Prix unitaire', 'Valeur stock', 'Statut']
    rows   = [header]

    for p in produits:
        if p['quantite'] == 0:
            statut = 'Rupture'
        elif p['quantite'] <= p['seuil']:
            statut = 'Faible'
        else:
            statut = 'OK'

        rows.append([
            p['nom'],
            str(p['quantite']),
            str(p['seuil']),
            f"{p['prix']:.2f} €",
            f"{p['quantite'] * p['prix']:,.2f} €".replace(',', ' '),
            statut,
        ])

    col_widths = [65*mm, 22*mm, 22*mm, 30*mm, 30*mm, 20*mm]
    prod_table = Table(rows, colWidths=col_widths, repeatRows=1)

    # Couleurs statut par ligne
    style_cmds = [
        ('BACKGROUND',   (0,0), (-1,0),  colors.HexColor('#1A1A18')),
        ('TEXTCOLOR',    (0,0), (-1,0),  colors.white),
        ('FONTNAME',     (0,0), (-1,0),  'Helvetica-Bold'),
        ('FONTSIZE',     (0,0), (-1,-1), 9),
        ('ALIGN',        (1,0), (-1,-1), 'CENTER'),
        ('ALIGN',        (0,0), (0,-1),  'LEFT'),
        ('VALIGN',       (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING',   (0,0), (-1,-1), 5),
        ('BOTTOMPADDING',(0,0), (-1,-1), 5),
        ('ROWBACKGROUNDS',(0,1),(-1,-1), [colors.white, colors.HexColor('#FAFAF8')]),
        ('BOX',          (0,0), (-1,-1), 0.5, colors.HexColor('#DDDBD4')),
        ('INNERGRID',    (0,0), (-1,-1), 0.5, colors.HexColor('#DDDBD4')),
    ]

    # Coloration conditionnelle de la colonne Statut
    for i, p in enumerate(produits, start=1):
        if p['quantite'] == 0:
            style_cmds.append(('TEXTCOLOR', (5,i), (5,i), colors.HexColor('#C0392B')))
            style_cmds.append(('FONTNAME',  (5,i), (5,i), 'Helvetica-Bold'))
        elif p['quantite'] <= p['seuil']:
            style_cmds.append(('TEXTCOLOR', (5,i), (5,i), colors.HexColor('#B7651A')))

    prod_table.setStyle(TableStyle(style_cmds))
    story.append(prod_table)

    # ── Build ──
    doc.build(story)
    buffer.seek(0)

    date_str = datetime.now().strftime('%Y%m%d_%H%M')
    filename = f"rapport_stock_{date_str}.pdf"

    response = make_response(buffer.read())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
