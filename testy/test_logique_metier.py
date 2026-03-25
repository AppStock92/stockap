"""Tests logique métier — version SQLAlchemy."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import Produit, Mouvement, db
from datetime import date


def get_pid(app, nom):
    with app.app_context():
        p = Produit.query.filter_by(nom=nom).first()
        return p.id if p else None


class TestStatutsProduits:

    def test_statut_ok(self, auth_client):
        """Produit avec stock > seuil → affiché."""
        resp = auth_client.get('/')
        assert b'Clavier' in resp.data   # quantite=20, seuil=5

    def test_statut_faible(self, auth_client):
        """Produit avec 0 < stock <= seuil → affiché."""
        resp = auth_client.get('/')
        assert b'Souris' in resp.data   # quantite=3, seuil=5

    def test_statut_rupture(self, auth_client):
        """Produit avec stock = 0 → affiché."""
        resp = auth_client.get('/')
        assert b'Cable' in resp.data   # quantite=0

    def test_statuts_via_sqlalchemy(self, app):
        """Vérifie les propriétés statut directement sur les modèles."""
        with app.app_context():
            clavier = Produit.query.filter_by(nom='Clavier mecanique').first()
            souris  = Produit.query.filter_by(nom='Souris sans fil').first()
            cable   = Produit.query.filter_by(nom='Cable HDMI').first()
            assert clavier.statut == 'ok'
            assert souris.statut  == 'faible'
            assert cable.statut   == 'rupture'


class TestCalculsValeur:

    def test_valeur_produit_sqlalchemy(self, app):
        """La propriété valeur est calculée correctement."""
        with app.app_context():
            p = Produit.query.filter_by(nom='Clavier mecanique').first()
            assert p.valeur == 20 * 89.99

    def test_export_csv_contient_produits(self, auth_client):
        resp = auth_client.get('/export/csv/produits')
        csv_text = resp.data.decode('utf-8-sig')
        assert 'Clavier' in csv_text
        assert 'Souris' in csv_text

    def test_export_csv_statuts(self, auth_client):
        resp = auth_client.get('/export/csv/produits')
        csv_text = resp.data.decode('utf-8-sig')
        assert 'OK' in csv_text        # Clavier mecanique : quantite=20 > seuil=5
        assert 'Faible' in csv_text    # Souris sans fil : quantite=3 <= seuil=5
        assert 'Rupture' in csv_text   # Cable HDMI : quantite=0

    def test_export_pdf_genere(self, auth_client):
        resp = auth_client.get('/export/pdf/stock')
        assert resp.status_code == 200
        assert resp.content_type == 'application/pdf'
        assert resp.data[:4] == b'%PDF'


class TestHistoriqueMovements:

    def test_mouvement_enregistre_en_base(self, auth_client, app):
        pid = get_pid(app, 'Clavier mecanique')
        auth_client.post(f'/mouvement/{pid}', data={'action': 'entree', 'qte': '5'})
        with app.app_context():
            count = Mouvement.query.count()
            mvt   = Mouvement.query.order_by(Mouvement.id.desc()).first()
        assert count == 1
        assert mvt.type     == 'entree'
        assert mvt.quantite == 5

    def test_mouvement_date_aujourdhui(self, auth_client, app):
        pid = get_pid(app, 'Clavier mecanique')
        auth_client.post(f'/mouvement/{pid}', data={'action': 'sortie', 'qte': '2'})
        with app.app_context():
            mvt = Mouvement.query.order_by(Mouvement.id.desc()).first()
        assert mvt.date == date.today()

    def test_export_csv_mouvements_apres_mvt(self, auth_client, app):
        pid = get_pid(app, 'Clavier mecanique')
        auth_client.post(f'/mouvement/{pid}', data={
            'action': 'entree', 'qte': '7', 'note': 'Reappro test'
        })
        resp = auth_client.get('/export/csv/mouvements')
        csv_text = resp.data.decode('utf-8-sig')
        assert 'Entree' in csv_text
        assert 'Clavier' in csv_text
