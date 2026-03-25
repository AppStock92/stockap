"""
conftest.py — corrigé pour app.py SQLAlchemy (version PostgreSQL migrée).
Utilise une base SQLite en mémoire via SQLAlchemy, pas de monkey-patch.
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Forcer SQLite en mémoire AVANT d'importer app
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

from app import app as flask_app, db
from app import Produit, Utilisateur, Categorie, Fournisseur, Mouvement
from werkzeug.security import generate_password_hash


# ── Fixture app ────────────────────────────────────────────────
@pytest.fixture(scope='session')
def app():
    flask_app.config.update({
        'TESTING':                    True,
        'SQLALCHEMY_DATABASE_URI':    'sqlite:///:memory:',
        'MAIL_SUPPRESS_SEND':         True,
        'WTF_CSRF_ENABLED':           False,
        'SECRET_KEY':                 'test-secret-key',
        'SQLALCHEMY_TRACK_MODIFICATIONS': False,
    })
    with flask_app.app_context():
        db.create_all()
    yield flask_app


# ── Fixture client ─────────────────────────────────────────────
@pytest.fixture(scope='session')
def client(app):
    return app.test_client()


# ── Reset DB avant chaque test ─────────────────────────────────
@pytest.fixture(autouse=True)
def reset_db(app):
    """Vide et repeuple toutes les tables avant chaque test."""
    with app.app_context():
        # Vider dans l'ordre inverse des dépendances FK
        Mouvement.query.delete()
        Produit.query.delete()
        Categorie.query.delete()
        Fournisseur.query.delete()
        Utilisateur.query.delete()
        db.session.commit()

        # Données de base
        admin = Utilisateur(
            username='admin',
            password=generate_password_hash('admin123'),
            email='admin@test.com'
        )
        db.session.add(admin)

        cat = Categorie(nom='Electronique')
        db.session.add(cat)

        four = Fournisseur(
            nom='TechDistrib',
            contact='Jean Dupont',
            email='contact@techdistrib.com',
            telephone=''
        )
        db.session.add(four)
        db.session.flush()   # obtenir les IDs avant commit

        p1 = Produit(nom='Clavier mecanique', quantite=20, prix=89.99, seuil=5)
        p2 = Produit(nom='Souris sans fil',   quantite=3,  prix=45.00, seuil=5)
        p3 = Produit(nom='Cable HDMI',        quantite=0,  prix=12.50, seuil=3)
        db.session.add_all([p1, p2, p3])
        db.session.commit()

    yield


# ── Client authentifié ─────────────────────────────────────────
@pytest.fixture
def auth_client(client):
    """Client déjà connecté avec le compte admin."""
    with client.session_transaction() as sess:
        sess.clear()
    client.post('/login', data={
        'username': 'admin',
        'password': 'admin123'
    }, follow_redirects=True)
    yield client
    client.get('/logout', follow_redirects=True)
