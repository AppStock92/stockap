"""
app.py — version sécurisée pour la production.

Changements par rapport à la version précédente :
  1. Chargement .env via python-dotenv
  2. Config par classe (Development / Production)
  3. CSRF via Flask-WTF sur tous les formulaires POST
  4. Headers de sécurité HTTP via Flask-Talisman
  5. Limitation des tentatives de login (Flask-Limiter)
  6. SECRET_KEY obligatoire depuis l'environnement
"""

# pip install python-dotenv flask-wtf flask-talisman flask-limiter

from dotenv import load_dotenv
load_dotenv()   # charge .env AVANT tout import de config

from flask import Flask, render_template, request, redirect, url_for, flash, make_response
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_mail import Mail, Message
from flask_wtf.csrf import CSRFProtect
from flask_talisman import Talisman
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import generate_password_hash, check_password_hash
import json, csv, io, os
from datetime import datetime, date
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

# ── Créer l'app ─────────────────────────────────────────────────
app = Flask(__name__)

# ── Charger la config selon FLASK_ENV ───────────────────────────
from config import config as app_configs
env_name = os.environ.get('FLASK_ENV', 'development')
app.config.from_object(app_configs[env_name])

# Corriger l'URL postgres:// → postgresql:// (Heroku/Railway)
db_url = app.config.get('SQLALCHEMY_DATABASE_URI', '')
if db_url.startswith('postgres://'):
    app.config['SQLALCHEMY_DATABASE_URI'] = db_url.replace('postgres://', 'postgresql://', 1)

# ── Extensions ──────────────────────────────────────────────────
db      = SQLAlchemy(app)
migrate = Migrate(app, db)
mail    = Mail(app)
csrf    = CSRFProtect(app)   # protection CSRF globale

# Headers de sécurité HTTP (désactivé en dev pour éviter les erreurs CDN)
if not app.config.get('DEBUG'):
    Talisman(app,
        force_https=True,
        strict_transport_security=True,
        strict_transport_security_max_age=31536000,   # 1 an
        content_security_policy={
            'default-src': "'self'",
            'script-src':  ["'self'", 'cdnjs.cloudflare.com'],
            'style-src':   ["'self'", "'unsafe-inline'",
                            'cdnjs.cloudflare.com',
                            'fonts.googleapis.com'],
            'font-src':    ['fonts.gstatic.com'],
            'img-src':     ["'self'", 'data:'],
        }
    )

# Limitation du nombre de requêtes (anti brute-force)
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=['200 per day', '50 per hour'],
    storage_uri='memory://',
)

login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = "Connectez-vous pour accéder à l'application."
login_manager.login_message_category = "error"


# ════════════════════════════════════════════════════════════════
# MODÈLES
# ════════════════════════════════════════════════════════════════

class Categorie(db.Model):
    __tablename__ = 'categories'
    id  = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.String(120), nullable=False, unique=True)
    produits = db.relationship('Produit', backref='categorie', lazy=True)


class Fournisseur(db.Model):
    __tablename__ = 'fournisseurs'
    id        = db.Column(db.Integer, primary_key=True)
    nom       = db.Column(db.String(200), nullable=False)
    contact   = db.Column(db.String(200), default='')
    email     = db.Column(db.String(200), default='')
    telephone = db.Column(db.String(50),  default='')
    produits  = db.relationship('Produit', backref='fournisseur', lazy=True)


class Produit(db.Model):
    __tablename__ = 'produits'
    id             = db.Column(db.Integer, primary_key=True)
    nom            = db.Column(db.String(200), nullable=False)
    quantite       = db.Column(db.Integer, nullable=False, default=0)
    prix           = db.Column(db.Float,   nullable=False, default=0.0)
    seuil          = db.Column(db.Integer, nullable=False, default=5)
    categorie_id   = db.Column(db.Integer, db.ForeignKey('categories.id'),   nullable=True)
    fournisseur_id = db.Column(db.Integer, db.ForeignKey('fournisseurs.id'), nullable=True)
    mouvements     = db.relationship('Mouvement', backref='produit', lazy=True)

    @property
    def statut(self):
        if self.quantite == 0:              return 'rupture'
        if self.quantite <= self.seuil:     return 'faible'
        return 'ok'

    @property
    def valeur(self):
        return self.quantite * self.prix


class Mouvement(db.Model):
    __tablename__ = 'mouvements'
    id          = db.Column(db.Integer, primary_key=True)
    produit_id  = db.Column(db.Integer, db.ForeignKey('produits.id'), nullable=False)
    produit_nom = db.Column(db.String(200), nullable=False)
    type        = db.Column(db.String(10),  nullable=False)
    quantite    = db.Column(db.Integer, nullable=False)
    date        = db.Column(db.Date,    nullable=False, default=date.today)
    note        = db.Column(db.Text,    default='')


class Utilisateur(db.Model, UserMixin):
    __tablename__ = 'utilisateurs'
    id       = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80),  nullable=False, unique=True)
    password = db.Column(db.String(256), nullable=False)
    email    = db.Column(db.String(200), default='')

    def set_password(self, pwd):
        self.password = generate_password_hash(pwd)

    def check_password(self, pwd):
        return check_password_hash(self.password, pwd)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(Utilisateur, int(user_id))


def init_db():
    db.create_all()
    if Utilisateur.query.count() == 0:
        admin = Utilisateur(username='admin')
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()


# ════════════════════════════════════════════════════════════════
# AUTH  — /login limité à 5 tentatives/minute (anti brute-force)
# ════════════════════════════════════════════════════════════════

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit('5 per minute')    # ← limite les tentatives de connexion
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = Utilisateur.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user, remember=request.form.get('remember') == 'on')
            return redirect(request.args.get('next') or url_for('index'))
        flash("Identifiants incorrects.", "error")
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash("Vous avez été déconnecté.", "success")
    return redirect(url_for('login'))


@app.route('/changer-mot-de-passe', methods=['GET', 'POST'])
@login_required
def changer_mdp():
    if request.method == 'POST':
        ancien  = request.form.get('ancien', '')
        nouveau = request.form.get('nouveau', '')
        confirm = request.form.get('confirm', '')
        if not current_user.check_password(ancien):
            flash("Ancien mot de passe incorrect.", "error")
        elif nouveau != confirm:
            flash("Les mots de passe ne correspondent pas.", "error")
        elif len(nouveau) < 6:
            flash("Minimum 6 caractères.", "error")
        else:
            current_user.set_password(nouveau)
            db.session.commit()
            flash("Mot de passe mis à jour.", "success")
            return redirect(url_for('index'))
    return render_template('changer_mdp.html')


# ════════════════════════════════════════════════════════════════
# ROUTES PRODUITS (identiques à app_postgresql.py)
# — coller ici le reste des routes depuis app_postgresql.py —
# ════════════════════════════════════════════════════════════════

# ... (index, add, update, delete, mouvement, dashboard,
#      graphiques, categories, fournisseurs, scanner,
#      alertes email, exports — identiques à app_postgresql.py)


# ════════════════════════════════════════════════════════════════
# LANCEMENT
# ════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    with app.app_context():
        init_db()
    # En production, utiliser gunicorn, pas app.run()
    # gunicorn -w 4 -b 0.0.0.0:8000 app:app
    app.run(debug=app.config.get('DEBUG', False))
