# ==============================================================
# 1. Ajouter cet import EN HAUT de app.py avec les autres :
#    from flask_mail import Mail, Message
#
# 2. Ajouter la config + mail = Mail(app) après app.secret_key
#
# 3. Coller les fonctions et routes ci-dessous dans app.py,
#    avant "if __name__ == '__main__'"
# ==============================================================


# ---------- Alertes email ----------

def envoyer_alerte_stock(produits_alertes):
    """
    Envoie un email HTML listant les produits en rupture ou stock faible.
    produits_alertes : liste de dicts avec clés nom, quantite, seuil, statut
    """
    if not produits_alertes:
        return

    # Récupérer tous les emails des utilisateurs enregistrés
    with get_db() as conn:
        utilisateurs = conn.execute("SELECT email FROM utilisateurs WHERE email IS NOT NULL AND email != ''").fetchall()

    destinataires = [u['email'] for u in utilisateurs]
    if not destinataires:
        return  # Aucun email configuré

    nb_ruptures = sum(1 for p in produits_alertes if p['statut'] == 'rupture')
    nb_faibles  = sum(1 for p in produits_alertes if p['statut'] == 'faible')

    # ── Corps HTML de l'email ──
    lignes_html = ""
    for p in produits_alertes:
        if p['statut'] == 'rupture':
            couleur_bg  = '#FEF0EE'
            couleur_txt = '#C0392B'
            label       = 'RUPTURE'
        else:
            couleur_bg  = '#FFF4E6'
            couleur_txt = '#B7651A'
            label       = 'Stock faible'

        lignes_html += f"""
        <tr>
          <td style="padding:10px 16px;font-size:14px;border-bottom:1px solid #DDDBD4">
            <strong>{p['nom']}</strong>
          </td>
          <td style="padding:10px 16px;font-size:14px;border-bottom:1px solid #DDDBD4;text-align:center">
            <strong>{p['quantite']}</strong>
          </td>
          <td style="padding:10px 16px;font-size:14px;border-bottom:1px solid #DDDBD4;text-align:center;color:#7A7870">
            {p['seuil']}
          </td>
          <td style="padding:10px 16px;border-bottom:1px solid #DDDBD4;text-align:center">
            <span style="background:{couleur_bg};color:{couleur_txt};
                         font-size:11px;padding:3px 8px;border-radius:4px;
                         font-weight:600">{label}</span>
          </td>
        </tr>"""

    html_body = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head><meta charset="UTF-8"></head>
    <body style="margin:0;padding:0;background:#F5F4F0;font-family:'Helvetica Neue',Arial,sans-serif">
      <div style="max-width:600px;margin:32px auto;background:#fff;
                  border-radius:12px;border:1px solid #DDDBD4;overflow:hidden">

        <!-- Header -->
        <div style="background:#1A1A18;padding:20px 28px;display:flex;align-items:center">
          <span style="color:#fff;font-size:15px;font-family:monospace;letter-spacing:.04em">
            📦 <span style="opacity:.4">stock</span>app
          </span>
        </div>

        <!-- Titre -->
        <div style="padding:24px 28px 16px">
          <h1 style="font-size:20px;font-weight:600;margin:0 0 6px;color:#1A1A18">
            Alerte stock — action requise
          </h1>
          <p style="font-size:14px;color:#7A7870;margin:0">
            {len(produits_alertes)} produit{'s' if len(produits_alertes) > 1 else ''}
            nécessite{'nt' if len(produits_alertes) > 1 else ''} votre attention.
          </p>
        </div>

        <!-- KPIs -->
        <div style="padding:0 28px 20px;display:flex;gap:12px">
          <div style="flex:1;background:#FEF0EE;border-radius:8px;padding:12px 16px">
            <div style="font-size:11px;color:#C0392B;text-transform:uppercase;
                        letter-spacing:.07em;margin-bottom:4px">Ruptures</div>
            <div style="font-size:24px;font-weight:600;color:#C0392B">{nb_ruptures}</div>
          </div>
          <div style="flex:1;background:#FFF4E6;border-radius:8px;padding:12px 16px">
            <div style="font-size:11px;color:#B7651A;text-transform:uppercase;
                        letter-spacing:.07em;margin-bottom:4px">Stock faible</div>
            <div style="font-size:24px;font-weight:600;color:#B7651A">{nb_faibles}</div>
          </div>
        </div>

        <!-- Tableau -->
        <div style="padding:0 28px 28px">
          <table style="width:100%;border-collapse:collapse;border:1px solid #DDDBD4;border-radius:8px;overflow:hidden">
            <thead>
              <tr style="background:#F5F4F0">
                <th style="padding:10px 16px;font-size:11px;text-align:left;
                            color:#7A7870;text-transform:uppercase;letter-spacing:.07em;
                            border-bottom:1px solid #DDDBD4">Produit</th>
                <th style="padding:10px 16px;font-size:11px;text-align:center;
                            color:#7A7870;text-transform:uppercase;letter-spacing:.07em;
                            border-bottom:1px solid #DDDBD4">Stock actuel</th>
                <th style="padding:10px 16px;font-size:11px;text-align:center;
                            color:#7A7870;text-transform:uppercase;letter-spacing:.07em;
                            border-bottom:1px solid #DDDBD4">Seuil</th>
                <th style="padding:10px 16px;font-size:11px;text-align:center;
                            color:#7A7870;text-transform:uppercase;letter-spacing:.07em;
                            border-bottom:1px solid #DDDBD4">Statut</th>
              </tr>
            </thead>
            <tbody>{lignes_html}</tbody>
          </table>
        </div>

        <!-- Footer -->
        <div style="padding:16px 28px;background:#F5F4F0;border-top:1px solid #DDDBD4;
                    font-size:12px;color:#7A7870">
          Email envoyé automatiquement par StockApp ·
          {datetime.now().strftime('%d/%m/%Y à %H:%M')}
        </div>
      </div>
    </body>
    </html>
    """

    sujet = f"[StockApp] ⚠️ {len(produits_alertes)} produit(s) en alerte de stock"

    try:
        msg = Message(
            subject=sujet,
            recipients=destinataires,
            html=html_body,
        )
        mail.send(msg)
    except Exception as e:
        app.logger.error(f"Erreur envoi email alerte : {e}")


def verifier_et_alerter(produit_id):
    """
    Vérifie si un produit est en alerte après un mouvement
    et envoie un email si nécessaire.
    Appelé automatiquement après chaque mouvement de stock.
    """
    with get_db() as conn:
        p = conn.execute(
            "SELECT * FROM produits WHERE id = ?", (produit_id,)
        ).fetchone()

    if not p:
        return

    alertes = []
    if p['quantite'] == 0:
        alertes.append({
            'nom': p['nom'], 'quantite': p['quantite'],
            'seuil': p['seuil'], 'statut': 'rupture'
        })
    elif p['quantite'] <= p['seuil']:
        alertes.append({
            'nom': p['nom'], 'quantite': p['quantite'],
            'seuil': p['seuil'], 'statut': 'faible'
        })

    envoyer_alerte_stock(alertes)


# ── Route manuelle : envoyer le rapport complet ──
@app.route('/alertes/envoyer', methods=['POST'])
@login_required
def envoyer_rapport_alertes():
    """
    Envoie manuellement un email avec TOUS les produits en alerte.
    Bouton dans l'interface d'administration.
    """
    with get_db() as conn:
        produits_alertes_db = conn.execute("""
            SELECT nom, quantite, seuil,
                   CASE WHEN quantite = 0 THEN 'rupture' ELSE 'faible' END as statut
            FROM produits
            WHERE quantite <= seuil
            ORDER BY quantite ASC
        """).fetchall()

    alertes = [dict(p) for p in produits_alertes_db]

    if not alertes:
        flash("Aucun produit en alerte — email non envoyé.", "success")
        return redirect(url_for('index'))

    envoyer_alerte_stock(alertes)
    flash(f"Email d'alerte envoyé pour {len(alertes)} produit(s).", "success")
    return redirect(url_for('index'))


# ── Page de configuration email ──
@app.route('/parametres/email', methods=['GET', 'POST'])
@login_required
def parametres_email():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        with get_db() as conn:
            conn.execute(
                "UPDATE utilisateurs SET email = ? WHERE id = ?",
                (email, current_user.id)
            )
            conn.commit()
        flash("Email mis à jour.", "success")
        return redirect(url_for('parametres_email'))

    with get_db() as conn:
        user = conn.execute(
            "SELECT * FROM utilisateurs WHERE id = ?", (current_user.id,)
        ).fetchone()

    return render_template('parametres_email.html', user=user)
