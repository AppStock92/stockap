"""
config.py — Configuration par environnement.
Placer ce fichier à la racine du projet, au même niveau que app.py.
"""
import os
from datetime import timedelta


class Config:
    """Base commune à tous les environnements."""

    # ── Secrets ────────────────────────────────────────────────
    SECRET_KEY = os.environ.get('SECRET_KEY') or _missing('SECRET_KEY')

    # ── Base de données ─────────────────────────────────────────
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///stock.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,      # vérifie la connexion avant utilisation
        'pool_recycle':  300,       # recycle les connexions toutes les 5 min
    }

    # ── Session ─────────────────────────────────────────────────
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    SESSION_COOKIE_HTTPONLY  = True    # inaccessible depuis JavaScript
    SESSION_COOKIE_SAMESITE  = 'Lax'  # protection CSRF de base

    # ── Email ───────────────────────────────────────────────────
    MAIL_SERVER         = os.environ.get('MAIL_SERVER',   'smtp.gmail.com')
    MAIL_PORT           = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS        = True
    MAIL_USERNAME       = os.environ.get('MAIL_USERNAME', '')
    MAIL_PASSWORD       = os.environ.get('MAIL_PASSWORD', '')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_USERNAME', '')

    # ── CSRF (Flask-WTF) ────────────────────────────────────────
    WTF_CSRF_ENABLED      = True
    WTF_CSRF_TIME_LIMIT   = 3600   # token valide 1 heure


class DevelopmentConfig(Config):
    """Développement local — debug activé, cookies non-HTTPS."""
    DEBUG                  = True
    SESSION_COOKIE_SECURE  = False   # HTTP accepté en local
    SQLALCHEMY_ECHO        = False   # True pour voir les requêtes SQL


class ProductionConfig(Config):
    """Production — sécurité maximale."""
    DEBUG                  = False
    SESSION_COOKIE_SECURE  = True    # cookie uniquement sur HTTPS
    SESSION_COOKIE_HTTPONLY = True
    PREFERRED_URL_SCHEME   = 'https'


class TestingConfig(Config):
    """Tests automatisés."""
    TESTING               = True
    WTF_CSRF_ENABLED      = False
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    MAIL_SUPPRESS_SEND    = True
    SECRET_KEY            = 'test-secret-key'


# ── Sélection automatique selon la variable d'environnement ────
config = {
    'development': DevelopmentConfig,
    'production':  ProductionConfig,
    'testing':     TestingConfig,
    'default':     DevelopmentConfig,
}


def _missing(name):
    """Lève une erreur claire si une variable obligatoire manque."""
    raise RuntimeError(
        f"Variable d'environnement manquante : {name}\n"
        f"Ajoute-la dans ton fichier .env ou dans les variables système."
    )
