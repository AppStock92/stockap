"""Tests d'authentification."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import Utilisateur, db
from werkzeug.security import check_password_hash


class TestLogin:

    def test_page_login_accessible(self, client):
        resp = client.get('/login')
        assert resp.status_code == 200

    def test_login_succes(self, client):
        resp = client.post('/login', data={
            'username': 'admin', 'password': 'admin123'
        }, follow_redirects=True)
        assert resp.status_code == 200
        # Après login réussi on est sur la page produits
        assert b'Clavier' in resp.data or b'produit' in resp.data.lower()

    def test_login_mauvais_mot_de_passe(self, client, app):
        # Déconnecter d'abord
        client.get('/logout', follow_redirects=True)
        resp = client.post('/login', data={
            'username': 'admin', 'password': 'mauvais'
        }, follow_redirects=True)
        assert resp.status_code == 200
        # Le message flash est dans la réponse (page login re-affichée)
        assert b'login' in resp.data.lower() or b'onnexion' in resp.data

    def test_login_utilisateur_inconnu(self, client):
        client.get('/logout', follow_redirects=True)
        resp = client.post('/login', data={
            'username': 'inconnu', 'password': 'n_importe_quoi'
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'login' in resp.data.lower() or b'onnexion' in resp.data

    def test_logout(self, auth_client):
        resp = auth_client.get('/logout', follow_redirects=True)
        assert resp.status_code == 200
        assert b'onnexion' in resp.data   # page login

    def test_acces_protege_sans_login(self, client):
        client.get('/logout', follow_redirects=True)
        resp = client.get('/', follow_redirects=False)
        assert resp.status_code == 302
        assert 'login' in resp.headers['Location'].lower()

    def test_dashboard_protege(self, client):
        client.get('/logout', follow_redirects=True)
        resp = client.get('/dashboard', follow_redirects=False)
        assert resp.status_code == 302

    def test_changer_mdp_mauvais_ancien(self, auth_client):
        resp = auth_client.post('/changer-mot-de-passe', data={
            'ancien': 'mauvais', 'nouveau': 'nouveau123', 'confirm': 'nouveau123'
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'ncorrect' in resp.data

    def test_changer_mdp_confirmation_differente(self, auth_client):
        resp = auth_client.post('/changer-mot-de-passe', data={
            'ancien': 'admin123', 'nouveau': 'nouveau123', 'confirm': 'different456'
        }, follow_redirects=True)
        assert b'correspondent' in resp.data

    def test_changer_mdp_trop_court(self, auth_client):
        resp = auth_client.post('/changer-mot-de-passe', data={
            'ancien': 'admin123', 'nouveau': 'abc', 'confirm': 'abc'
        }, follow_redirects=True)
        assert b'6' in resp.data
