"""Tests catégories et fournisseurs — version SQLAlchemy."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import Categorie, Fournisseur, Produit, db


def count_cats(app):
    with app.app_context():
        return Categorie.query.count()

def count_fours(app):
    with app.app_context():
        return Fournisseur.query.count()

def get_cat_id(app):
    with app.app_context():
        return Categorie.query.first().id

def get_four_id(app):
    with app.app_context():
        return Fournisseur.query.first().id


class TestCategories:

    def test_page_categories(self, auth_client):
        resp = auth_client.get('/categories')
        assert resp.status_code == 200
        assert b'lectronique' in resp.data

    def test_add_categorie(self, auth_client, app):
        nb = count_cats(app)
        auth_client.post('/categories/add', data={'nom': 'Mobilier'},
                         follow_redirects=True)
        assert count_cats(app) == nb + 1

    def test_add_categorie_doublon(self, auth_client):
        resp = auth_client.post('/categories/add', data={'nom': 'Electronique'},
                                follow_redirects=True)
        assert b'existe' in resp.data

    def test_add_categorie_sans_nom(self, auth_client):
        resp = auth_client.post('/categories/add', data={'nom': ''},
                                follow_redirects=True)
        assert b'obligatoire' in resp.data

    def test_edit_categorie(self, auth_client, app):
        cid = get_cat_id(app)
        auth_client.post(f'/categories/edit/{cid}', data={'nom': 'High-Tech'},
                         follow_redirects=True)
        with app.app_context():
            c = db.session.get(Categorie, cid)
            assert c.nom == 'High-Tech'

    def test_delete_categorie(self, auth_client, app):
        nb = count_cats(app)
        cid = get_cat_id(app)
        auth_client.post(f'/categories/delete/{cid}', follow_redirects=True)
        assert count_cats(app) == nb - 1

    def test_delete_categorie_detache_produits(self, auth_client, app):
        cid = get_cat_id(app)
        # Lier le produit 'Clavier' à cette catégorie
        with app.app_context():
            p = Produit.query.filter_by(nom='Clavier mecanique').first()
            p.categorie_id = cid
            db.session.commit()
            pid = p.id

        auth_client.post(f'/categories/delete/{cid}', follow_redirects=True)

        with app.app_context():
            p = db.session.get(Produit, pid)
            assert p.categorie_id is None


class TestFournisseurs:

    def test_page_fournisseurs(self, auth_client):
        resp = auth_client.get('/fournisseurs')
        assert resp.status_code == 200
        assert b'TechDistrib' in resp.data

    def test_add_fournisseur(self, auth_client, app):
        nb = count_fours(app)
        auth_client.post('/fournisseurs/add', data={
            'nom': 'ElectroPlus', 'contact': 'Marie Martin',
            'email': 'marie@electroplus.com', 'telephone': '0612345678'
        }, follow_redirects=True)
        assert count_fours(app) == nb + 1

    def test_add_fournisseur_sans_nom(self, auth_client):
        resp = auth_client.post('/fournisseurs/add', data={
            'nom': '', 'contact': 'Test'
        }, follow_redirects=True)
        assert b'obligatoire' in resp.data

    def test_edit_fournisseur_page(self, auth_client, app):
        fid = get_four_id(app)
        resp = auth_client.get(f'/fournisseurs/edit/{fid}')
        assert resp.status_code == 200
        assert b'TechDistrib' in resp.data

    def test_edit_fournisseur(self, auth_client, app):
        fid = get_four_id(app)
        auth_client.post(f'/fournisseurs/edit/{fid}', data={
            'nom': 'TechDistrib Pro', 'contact': 'Jean Dupont',
            'email': 'contact@techdistrib.com', 'telephone': '0612345678'
        }, follow_redirects=True)
        with app.app_context():
            f = db.session.get(Fournisseur, fid)
            assert f.nom == 'TechDistrib Pro'

    def test_delete_fournisseur(self, auth_client, app):
        nb = count_fours(app)
        fid = get_four_id(app)
        auth_client.post(f'/fournisseurs/delete/{fid}', follow_redirects=True)
        assert count_fours(app) == nb - 1

    def test_edit_fournisseur_inexistant(self, auth_client):
        resp = auth_client.get('/fournisseurs/edit/9999')
        assert resp.status_code == 404
