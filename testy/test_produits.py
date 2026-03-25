"""Tests CRUD produits — version SQLAlchemy."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import Produit, db


def get_produit(app, id):
    with app.app_context():
        return db.session.get(Produit, id)

def count_produits(app):
    with app.app_context():
        return Produit.query.count()


class TestIndex:

    def test_index_affiche_produits(self, auth_client):
        resp = auth_client.get('/')
        assert resp.status_code == 200
        assert b'Clavier' in resp.data

    def test_index_affiche_kpis(self, auth_client):
        resp = auth_client.get('/')
        assert resp.status_code == 200
        assert b'3' in resp.data   # 3 produits


class TestAdd:

    def test_add_produit_valide(self, auth_client, app):
        nb = count_produits(app)
        resp = auth_client.post('/add', data={
            'nom': 'Webcam HD', 'quantite': '10',
            'prix': '79.00', 'seuil': '3'
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert count_produits(app) == nb + 1
        assert b'Webcam' in resp.data

    def test_add_sans_nom_erreur(self, auth_client, app):
        nb = count_produits(app)
        resp = auth_client.post('/add', data={
            'nom': '', 'quantite': '10', 'prix': '10.00', 'seuil': '5'
        }, follow_redirects=True)
        assert b'obligatoire' in resp.data
        assert count_produits(app) == nb   # rien ajouté

    def test_add_quantite_non_numerique(self, auth_client):
        resp = auth_client.post('/add', data={
            'nom': 'Test', 'quantite': 'abc', 'prix': '10.00', 'seuil': '5'
        }, follow_redirects=True)
        assert b'nombres' in resp.data

    def test_add_prix_invalide(self, auth_client):
        resp = auth_client.post('/add', data={
            'nom': 'Test', 'quantite': '5', 'prix': 'gratuit', 'seuil': '2'
        }, follow_redirects=True)
        assert b'nombres' in resp.data

    def test_add_avec_categorie(self, auth_client, app):
        with app.app_context():
            from app import Categorie
            cat = Categorie.query.first()
            cat_id = cat.id
        resp = auth_client.post('/add', data={
            'nom': 'Tapis de souris', 'quantite': '15',
            'prix': '19.99', 'seuil': '3', 'categorie_id': str(cat_id)
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'Tapis' in resp.data


class TestUpdate:

    def test_update_page_accessible(self, auth_client, app):
        with app.app_context():
            p = Produit.query.filter_by(nom='Clavier mecanique').first()
            pid = p.id
        resp = auth_client.get(f'/update/{pid}')
        assert resp.status_code == 200
        assert b'Clavier' in resp.data

    def test_update_produit_inexistant(self, auth_client):
        resp = auth_client.get('/update/9999', follow_redirects=True)
        # SQLAlchemy get_or_404 → 404
        assert resp.status_code == 404

    def test_update_succes(self, auth_client, app):
        with app.app_context():
            p = Produit.query.filter_by(nom='Clavier mecanique').first()
            pid = p.id
        resp = auth_client.post(f'/update/{pid}', data={
            'nom': 'Clavier RGB', 'quantite': '20',
            'prix': '99.99', 'seuil': '5'
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'RGB' in resp.data

    def test_update_donnees_invalides(self, auth_client, app):
        with app.app_context():
            p = Produit.query.filter_by(nom='Clavier mecanique').first()
            pid = p.id
        resp = auth_client.post(f'/update/{pid}', data={
            'nom': 'Test', 'quantite': 'xyz', 'prix': '10.00', 'seuil': '5'
        }, follow_redirects=True)
        assert b'nvalide' in resp.data or b'nombres' in resp.data


class TestDelete:

    def test_delete_produit(self, auth_client, app):
        with app.app_context():
            p = Produit.query.filter_by(nom='Clavier mecanique').first()
            pid = p.id
        resp = auth_client.post(f'/delete/{pid}', follow_redirects=True)
        assert resp.status_code == 200
        assert b'supprim' in resp.data

    def test_delete_produit_inexistant(self, auth_client):
        resp = auth_client.post('/delete/9999', follow_redirects=True)
        assert resp.status_code == 404

    def test_delete_via_get_interdit(self, auth_client, app):
        with app.app_context():
            p = Produit.query.first()
            pid = p.id
        resp = auth_client.get(f'/delete/{pid}')
        assert resp.status_code == 405
