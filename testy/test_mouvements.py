"""Tests mouvements de stock — version SQLAlchemy."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import Produit, Mouvement, db


def get_stock(app, nom):
    with app.app_context():
        p = Produit.query.filter_by(nom=nom).first()
        return p.quantite if p else None

def count_mouvements(app):
    with app.app_context():
        return Mouvement.query.count()

def get_pid(app, nom):
    with app.app_context():
        p = Produit.query.filter_by(nom=nom).first()
        return p.id if p else None


class TestMouvements:

    def test_entree_stock(self, auth_client, app):
        pid = get_pid(app, 'Clavier mecanique')
        avant = get_stock(app, 'Clavier mecanique')
        auth_client.post(f'/mouvement/{pid}', data={'action': 'entree', 'qte': '5'})
        assert get_stock(app, 'Clavier mecanique') == avant + 5
        assert count_mouvements(app) == 1

    def test_sortie_stock(self, auth_client, app):
        pid = get_pid(app, 'Clavier mecanique')
        avant = get_stock(app, 'Clavier mecanique')
        auth_client.post(f'/mouvement/{pid}', data={'action': 'sortie', 'qte': '3'})
        assert get_stock(app, 'Clavier mecanique') == avant - 3

    def test_sortie_stock_insuffisant(self, auth_client, app):
        pid = get_pid(app, 'Clavier mecanique')
        avant = get_stock(app, 'Clavier mecanique')
        resp = auth_client.post(f'/mouvement/{pid}', data={
            'action': 'sortie', 'qte': '999'
        }, follow_redirects=True)
        assert b'insuffisant' in resp.data
        assert get_stock(app, 'Clavier mecanique') == avant

    def test_sortie_produit_rupture(self, auth_client, app):
        pid = get_pid(app, 'Cable HDMI')
        assert get_stock(app, 'Cable HDMI') == 0
        resp = auth_client.post(f'/mouvement/{pid}', data={
            'action': 'sortie', 'qte': '1'
        }, follow_redirects=True)
        assert b'insuffisant' in resp.data

    def test_mouvement_quantite_zero(self, auth_client, app):
        pid = get_pid(app, 'Clavier mecanique')
        avant = get_stock(app, 'Clavier mecanique')
        resp = auth_client.post(f'/mouvement/{pid}', data={
            'action': 'entree', 'qte': '0'
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert get_stock(app, 'Clavier mecanique') == avant

    def test_mouvement_quantite_invalide(self, auth_client, app):
        pid = get_pid(app, 'Clavier mecanique')
        resp = auth_client.post(f'/mouvement/{pid}', data={
            'action': 'entree', 'qte': 'abc'
        }, follow_redirects=True)
        assert resp.status_code == 200

    def test_mouvement_produit_inexistant(self, auth_client):
        resp = auth_client.post('/mouvement/9999', data={
            'action': 'entree', 'qte': '5'
        }, follow_redirects=True)
        assert resp.status_code == 404

    def test_entree_puis_sortie(self, auth_client, app):
        pid = get_pid(app, 'Clavier mecanique')
        initial = get_stock(app, 'Clavier mecanique')
        auth_client.post(f'/mouvement/{pid}', data={'action': 'entree', 'qte': '10'})
        auth_client.post(f'/mouvement/{pid}', data={'action': 'sortie', 'qte': '10'})
        assert get_stock(app, 'Clavier mecanique') == initial
        assert count_mouvements(app) == 2


class TestExports:

    def test_export_csv_produits(self, auth_client):
        resp = auth_client.get('/export/csv/produits')
        assert resp.status_code == 200
        assert 'text/csv' in resp.content_type
        assert b'Clavier' in resp.data
        assert b'Souris' in resp.data

    def test_export_csv_mouvements(self, auth_client):
        resp = auth_client.get('/export/csv/mouvements')
        assert resp.status_code == 200
        assert 'text/csv' in resp.content_type

    def test_export_pdf(self, auth_client):
        resp = auth_client.get('/export/pdf/stock')
        assert resp.status_code == 200
        assert resp.content_type == 'application/pdf'
        assert resp.data[:4] == b'%PDF'
