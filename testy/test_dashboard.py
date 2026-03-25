"""Tests dashboard, graphiques, scanner — version SQLAlchemy."""
import json
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import Produit, Utilisateur, db


def get_pid(app, nom):
    with app.app_context():
        p = Produit.query.filter_by(nom=nom).first()
        return p.id if p else None


class TestDashboard:

    def test_dashboard_accessible(self, auth_client):
        resp = auth_client.get('/dashboard')
        assert resp.status_code == 200

    def test_dashboard_contient_produits(self, auth_client):
        resp = auth_client.get('/dashboard')
        assert resp.status_code == 200
        # Les données JSON sont injectées dans le template
        assert b'produits_json' in resp.data or b'Clavier' in resp.data

    def test_graphiques_accessible(self, auth_client):
        resp = auth_client.get('/graphiques')
        assert resp.status_code == 200

    def test_graphiques_json_valide(self, auth_client):
        resp = auth_client.get('/graphiques')
        assert resp.status_code == 200
        assert b'produits' in resp.data
        assert b'entrees' in resp.data


class TestScanner:

    def test_scanner_accessible(self, auth_client):
        resp = auth_client.get('/scanner')
        assert resp.status_code == 200

    def test_scanner_mouvement_entree(self, auth_client, app):
        pid = get_pid(app, 'Clavier mecanique')
        with app.app_context():
            avant = Produit.query.get(pid).quantite

        resp = auth_client.post('/scanner/mouvement', data={
            'produit_id': str(pid), 'action': 'entree', 'qte': '5'
        })
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['ok'] is True
        assert data['nouveau_stock'] == avant + 5

    def test_scanner_mouvement_stock_insuffisant(self, auth_client, app):
        pid = get_pid(app, 'Clavier mecanique')
        resp = auth_client.post('/scanner/mouvement', data={
            'produit_id': str(pid), 'action': 'sortie', 'qte': '9999'
        })
        assert resp.status_code == 400
        data = json.loads(resp.data)
        assert data['ok'] is False

    def test_scanner_produit_inexistant(self, auth_client):
        resp = auth_client.post('/scanner/mouvement', data={
            'produit_id': '9999', 'action': 'entree', 'qte': '1'
        })
        assert resp.status_code == 404


class TestParametresEmail:

    def test_page_parametres_email(self, auth_client):
        resp = auth_client.get('/parametres/email')
        assert resp.status_code == 200

    def test_mise_a_jour_email(self, auth_client, app):
        auth_client.post('/parametres/email', data={
            'email': 'nouveau@test.com'
        }, follow_redirects=True)
        with app.app_context():
            u = Utilisateur.query.filter_by(username='admin').first()
            assert u.email == 'nouveau@test.com'
