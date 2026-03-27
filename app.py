# app.py — version finale corrigée
# pip install python-dotenv flask-wtf flask-talisman flask-limiter

from dotenv import load_dotenv
load_dotenv()

import logging
import time
from logging.handlers import RotatingFileHandler
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, flash, make_response, session
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

app = Flask(__name__)

# ════════════════════════════════════════════════════════════════
# LOGGING & MONITORING
# ════════════════════════════════════════════════════════════════

def setup_logging(app):
    log_level = logging.DEBUG if app.debug else logging.INFO
    formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s %(module)s:%(lineno)d — %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.setLevel(log_level)
    if not app.debug:
        try:
            fh = RotatingFileHandler('logs/stockapp.log',
                                     maxBytes=5*1024*1024, backupCount=5, encoding='utf-8')
            fh.setFormatter(formatter)
            fh.setLevel(logging.INFO)
            app.logger.addHandler(fh)
        except FileNotFoundError:
            pass
    app.logger.addHandler(console)
    app.logger.setLevel(log_level)
    app.logger.propagate = False


def setup_sentry(app):
    dsn = os.environ.get('SENTRY_DSN')
    if not dsn:
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
        sentry_sdk.init(
            dsn=dsn,
            integrations=[FlaskIntegration(), SqlalchemyIntegration()],
            traces_sample_rate=0.2,
            environment=os.environ.get('FLASK_ENV', 'development'),
            release=os.environ.get('APP_VERSION', 'unknown'),
        )
    except ImportError:
        app.logger.warning("sentry-sdk non installé")


# ════════════════════════════════════════════════════════════════
# CONFIGURATION
# ════════════════════════════════════════════════════════════════

_secret = os.environ.get('SECRET_KEY')
if not _secret:
    raise RuntimeError(
        "Variable SECRET_KEY manquante.\n"
        "Génère-en une : python -c \"import secrets; print(secrets.token_hex(32))\"\n"
        "Puis ajoute-la dans ton fichier .env"
    )
app.config['SECRET_KEY'] = _secret

_db_url = os.environ.get('DATABASE_URL', 'sqlite:///stock.db')
if _db_url.startswith('postgres://'):
    _db_url = _db_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI']    = _db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

app.config['MAIL_SERVER']         = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT']           = int(os.environ.get('MAIL_PORT', 587))
app.config['MAIL_USE_TLS']        = True
app.config['MAIL_USERNAME']       = os.environ.get('MAIL_USERNAME', '')
app.config['MAIL_PASSWORD']       = os.environ.get('MAIL_PASSWORD', '')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_USERNAME', '')

app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE']   = not app.debug
app.config['PERMANENT_SESSION_LIFETIME'] = 300  # 5 minutes en secondes

# ════════════════════════════════════════════════════════════════
# EXTENSIONS
# ════════════════════════════════════════════════════════════════

db      = SQLAlchemy(app)
migrate = Migrate(app, db)
mail    = Mail(app)
csrf    = CSRFProtect(app)

if os.environ.get('FLASK_ENV') == 'production':
    Talisman(app,
        force_https=True,
        strict_transport_security=True,
        strict_transport_security_max_age=31536000,
        content_security_policy={
            'default-src': "'self'",
            'script-src':  ["'self'", 'cdnjs.cloudflare.com',
                            'cdn.jsdelivr.net', "'unsafe-inline'"],
            'style-src':   ["'self'", "'unsafe-inline'",
                            'cdnjs.cloudflare.com', 'cdn.jsdelivr.net',
                            'fonts.googleapis.com'],
            'font-src':    ['fonts.gstatic.com', 'cdn.jsdelivr.net',
                            'cdnjs.cloudflare.com'],
            'img-src':     ["'self'", 'data:'],
        }
    )

setup_logging(app)
setup_sentry(app)

limiter = Limiter(
    get_remote_address, app=app,
    default_limits=['200 per day', '50 per hour'],
    storage_uri='memory://',
    enabled=os.environ.get('FLASK_ENV') == 'production',
)

login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = "Connectez-vous pour accéder à l'application."
login_manager.login_message_category = "error"

# ════════════════════════════════════════════════════════════════
# MODÈLES SQLAlchemy
# ════════════════════════════════════════════════════════════════

class Notification(db.Model):
    __tablename__ = 'notifications'
    id             = db.Column(db.Integer, primary_key=True)
    utilisateur_id = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'), nullable=False)
    entreprise_id  = db.Column(db.Integer, db.ForeignKey('entreprises.id'),  nullable=False)
    type           = db.Column(db.String(30),  nullable=False)
    titre          = db.Column(db.String(200), nullable=False)
    message        = db.Column(db.Text,        nullable=False)
    lien           = db.Column(db.String(200), nullable=True)
    lue            = db.Column(db.Boolean,     default=False)
    cree_le        = db.Column(db.DateTime,    nullable=False, default=datetime.now)

    def to_dict(self):
        return {
            'id': self.id, 'type': self.type, 'titre': self.titre,
            'message': self.message, 'lien': self.lien, 'lue': self.lue,
            'cree_le': self.cree_le.strftime('%d/%m %H:%M'),
        }


class Abonnement(db.Model):
    __tablename__ = 'abonnements'
    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'), nullable=False, unique=True)
    plan         = db.Column(db.String(20), nullable=False, default='free')
    statut       = db.Column(db.String(20), nullable=False, default='actif')
    date_debut   = db.Column(db.DateTime, nullable=True)
    date_fin     = db.Column(db.DateTime, nullable=True)
    cree_le      = db.Column(db.DateTime, nullable=False, default=datetime.now)
    renouvele_le = db.Column(db.DateTime, nullable=True)

    utilisateur  = db.relationship('Utilisateur', back_populates='abonnement')

    def est_actif(self):
        if self.plan == 'free':
            return True
        if self.statut == 'expire':
            return False
        if self.date_fin and datetime.now() > self.date_fin:
            self.statut = 'expire'
            try: db.session.commit()
            except: db.session.rollback()
            return False
        return self.statut == 'actif'

    def jours_restants(self):
        if not self.date_fin or self.plan == 'free':
            return None
        return max(0, (self.date_fin - datetime.now()).days)

    def renouveler(self, plan=None):
        from datetime import timedelta
        if plan: self.plan = plan
        duree = 30 if self.plan == 'monthly' else 365
        self.date_debut   = datetime.now()
        self.date_fin     = datetime.now() + timedelta(days=duree)
        self.statut       = 'actif'
        self.renouvele_le = datetime.now()
        db.session.commit()

    def to_dict(self):
        return {
            'plan': self.plan, 'statut': self.statut,
            'est_actif': self.est_actif(),
            'date_fin': self.date_fin.strftime('%d/%m/%Y') if self.date_fin else None,
            'jours_restants': self.jours_restants(),
        }


# Limites par plan
LIMITES_AB = {
    'free':    {'produits': 10,   'utilisateurs': 1,    'export_pdf': False, 'alertes': False},
    'monthly': {'produits': 9999, 'utilisateurs': 9999, 'export_pdf': True,  'alertes': True},
    'yearly':  {'produits': 9999, 'utilisateurs': 9999, 'export_pdf': True,  'alertes': True},
}

PRIX_AB = {
    'monthly': {'prix': 2,  'label': '2 €/mois', 'duree': 30},
    'yearly':  {'prix': 13, 'label': '13 €/an',  'duree': 365},
}


def get_abonnement(user=None):
    if user is None:
        user = current_user
    if not hasattr(user, 'is_authenticated') or not user.is_authenticated:
        return None
    if user.abonnement:
        return user.abonnement
    ab = Abonnement(user_id=user.id, plan='free', statut='actif')
    db.session.add(ab)
    try: db.session.commit()
    except: db.session.rollback()
    return ab


def abonnement_actif(user=None):
    if user is None: user = current_user
    if getattr(user, 'is_admin', False):
        return True  # Admin toujours actif
    ab = get_abonnement(user)
    return ab.est_actif() if ab else False


def limite_produits_ab(user=None):
    if user is None: user = current_user
    if getattr(user, 'is_admin', False):
        return 999999  # Admin illimité
    ab = get_abonnement(user)
    plan = ab.plan if ab and ab.est_actif() else 'free'
    return LIMITES_AB.get(plan, LIMITES_AB['free'])['produits']


def peut_faire_ab(feature, user=None):
    if user is None: user = current_user
    if getattr(user, 'is_admin', False):
        return True  # Admin peut tout faire
    ab = get_abonnement(user)
    plan = ab.plan if ab and ab.est_actif() else 'free'
    return LIMITES_AB.get(plan, LIMITES_AB['free']).get(feature, False)


def verifier_expiration_batch():
    from sqlalchemy import and_
    expires = Abonnement.query.filter(
        Abonnement.statut == 'actif',
        Abonnement.plan != 'free',
        Abonnement.date_fin < datetime.now()
    ).all()
    for ab in expires:
        ab.statut = 'expire'
        if ab.utilisateur and ab.utilisateur.entreprise_id:
            creer_notification(
                entreprise_id=ab.utilisateur.entreprise_id,
                type='alerte',
                titre='Abonnement expiré',
                message=f'Votre plan {ab.plan.upper()} a expiré. Renouvelez pour continuer.',
                lien='/upgrade'
            )
    if expires:
        db.session.commit()
    return len(expires)


class Entreprise(db.Model):
    __tablename__ = 'entreprises'
    id             = db.Column(db.Integer, primary_key=True)
    nom            = db.Column(db.String(200), nullable=False)
    slug           = db.Column(db.String(100), nullable=False, unique=True)
    plan           = db.Column(db.String(20),  default='free')
    cree_le        = db.Column(db.Date, nullable=False, default=date.today)
    stripe_customer_id = db.Column(db.String(100), nullable=True)
    stripe_sub_id      = db.Column(db.String(100), nullable=True)
    stripe_status      = db.Column(db.String(30),  nullable=True)

    utilisateurs = db.relationship('Utilisateur', backref='entreprise', lazy=True)
    produits     = db.relationship('Produit',     backref='entreprise', lazy=True)
    categories   = db.relationship('Categorie',   backref='entreprise', lazy=True)
    fournisseurs = db.relationship('Fournisseur', backref='entreprise', lazy=True)
    mouvements   = db.relationship('Mouvement',   backref='entreprise', lazy=True)

    @property
    def limite_produits(self):
        return 9999 if self.plan == 'pro' else 50


class Categorie(db.Model):
    __tablename__ = 'categories'
    id            = db.Column(db.Integer, primary_key=True)
    nom           = db.Column(db.String(120), nullable=False)
    entreprise_id = db.Column(db.Integer, db.ForeignKey('entreprises.id'), nullable=True)
    produits      = db.relationship('Produit', backref='categorie', lazy=True)


class Fournisseur(db.Model):
    __tablename__ = 'fournisseurs'
    id            = db.Column(db.Integer, primary_key=True)
    nom           = db.Column(db.String(200), nullable=False)
    contact       = db.Column(db.String(200), default='')
    email         = db.Column(db.String(200), default='')
    telephone     = db.Column(db.String(50),  default='')
    entreprise_id = db.Column(db.Integer, db.ForeignKey('entreprises.id'), nullable=True)
    produits      = db.relationship('Produit', backref='fournisseur', lazy=True)


class Produit(db.Model):
    __tablename__ = 'produits'
    id             = db.Column(db.Integer, primary_key=True)
    nom            = db.Column(db.String(200), nullable=False)
    code_barres    = db.Column(db.String(100), nullable=True)
    quantite       = db.Column(db.Integer, nullable=False, default=0)
    prix           = db.Column(db.Float,   nullable=False, default=0.0)
    seuil          = db.Column(db.Integer, nullable=False, default=5)
    categorie_id   = db.Column(db.Integer, db.ForeignKey('categories.id'),   nullable=True)
    fournisseur_id = db.Column(db.Integer, db.ForeignKey('fournisseurs.id'), nullable=True)
    entreprise_id  = db.Column(db.Integer, db.ForeignKey('entreprises.id'),  nullable=True)
    mouvements     = db.relationship('Mouvement', backref='produit', lazy=True)

    @property
    def statut(self):
        if self.quantite == 0:          return 'rupture'
        if self.quantite <= self.seuil: return 'faible'
        return 'ok'

    @property
    def valeur(self):
        return self.quantite * self.prix


class Mouvement(db.Model):
    __tablename__ = 'mouvements'
    id            = db.Column(db.Integer, primary_key=True)
    produit_id    = db.Column(db.Integer, db.ForeignKey('produits.id'), nullable=False)
    produit_nom   = db.Column(db.String(200), nullable=False)
    type          = db.Column(db.String(10),  nullable=False)
    quantite      = db.Column(db.Integer, nullable=False)
    date          = db.Column(db.Date,    nullable=False, default=date.today)
    note          = db.Column(db.Text,    default='')
    entreprise_id = db.Column(db.Integer, db.ForeignKey('entreprises.id'), nullable=True)


class Utilisateur(db.Model, UserMixin):
    __tablename__ = 'utilisateurs'
    id                   = db.Column(db.Integer, primary_key=True)
    username             = db.Column(db.String(80),  nullable=False, unique=True)
    password             = db.Column(db.String(256), nullable=False)
    email                = db.Column(db.String(200), default='')
    devise               = db.Column(db.String(10),  default='€')
    role                 = db.Column(db.String(20),  default='admin')
    entreprise_id        = db.Column(db.Integer, db.ForeignKey('entreprises.id'), nullable=True)
    email_verifie        = db.Column(db.Boolean, default=False)
    token_verification   = db.Column(db.String(100), nullable=True)
    token_reset          = db.Column(db.String(100), nullable=True)
    token_reset_exp      = db.Column(db.DateTime,    nullable=True)
    onboarding_complete  = db.Column(db.Boolean,     default=False)

    abonnement = db.relationship('Abonnement', back_populates='utilisateur', uselist=False, cascade='all, delete-orphan')

    def set_password(self, pwd):
        self.password = generate_password_hash(pwd)

    def check_password(self, pwd):
        return check_password_hash(self.password, pwd)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(Utilisateur, int(user_id))

# ════════════════════════════════════════════════════════════════
# PLANS — définis avant les décorateurs et context_processor
# ════════════════════════════════════════════════════════════════

PLANS = {
    'free': {
        'nom': 'Gratuit', 'prix': 0, 'affichage': '0 €/mois',
        'features': ['50 produits max', '1 utilisateur', 'Export CSV',
                     'Dashboard & graphiques', 'Scanner code-barres'],
        'badge': None, 'price_id': None,
        'limites': {
            'produits': 50, 'utilisateurs': 1, 'export_pdf': False,
            'alertes_email': False, 'categories': 10, 'fournisseurs': 5,
            'historique_jours': 30,
        }
    },
    'starter': {
        'nom': 'Starter', 'prix': 2, 'affichage': '2 €/mois',
        'features': ['200 produits', '3 utilisateurs', 'Export CSV & PDF',
                     'Alertes email', 'Support email'],
        'badge': None, 'price_id': os.environ.get('STRIPE_PRICE_ID_STARTER', ''),
        'limites': {
            'produits': 200, 'utilisateurs': 3, 'export_pdf': True,
            'alertes_email': True, 'categories': 50, 'fournisseurs': 30,
            'historique_jours': 90,
        }
    },
    'pro': {
        'nom': 'Pro', 'prix': 13, 'affichage': '13 €/mois',
        'features': ['Produits illimités', 'Équipe illimitée', 'Export PDF',
                     'Alertes email', 'Historique complet', 'Support prioritaire'],
        'badge': 'Populaire', 'price_id': os.environ.get('STRIPE_PRICE_ID_PRO', ''),
        'limites': {
            'produits': 9999, 'utilisateurs': 9999, 'export_pdf': True,
            'alertes_email': True, 'categories': 9999, 'fournisseurs': 9999,
            'historique_jours': 9999,
        }
    },
}


def get_limite(feature):
    if not current_user.is_authenticated:
        return None
    e = get_entreprise()
    plan_id = e.plan if e else 'free'
    return PLANS.get(plan_id, PLANS['free'])['limites'].get(feature)


def plan_permet(feature):
    limite = get_limite(feature)
    if isinstance(limite, bool): return limite
    if isinstance(limite, int):  return limite > 0
    return False


def verifier_limite(feature, count_actuel=None):
    limite = get_limite(feature)
    if limite is None: return True, None
    if isinstance(limite, bool):
        if not limite:
            return False, "Cette fonctionnalité n'est pas disponible sur votre plan actuel."
        return True, None
    if isinstance(limite, int) and count_actuel is not None:
        if count_actuel >= limite:
            return False, f"Limite atteinte ({count_actuel}/{limite}). Passez au plan Pro pour continuer."
    return True, None

# ════════════════════════════════════════════════════════════════
# DÉCORATEURS
# ════════════════════════════════════════════════════════════════

def plan_requis(feature, redirect_to='abonnement'):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            ok, msg = verifier_limite(feature)
            if not ok:
                flash(msg or "Fonctionnalité non disponible sur votre plan.", "error")
                return redirect(url_for(redirect_to))
            return f(*args, **kwargs)
        return decorated
    return decorator


def role_requis(*roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('login'))
            if current_user.role not in roles:
                flash(f"Accès refusé. Rôle requis : {' ou '.join(roles)}.", "error")
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        return decorated
    return decorator

def admin_requis(f):    return role_requis('admin')(f)
def manager_ou_admin(f): return role_requis('admin', 'manager')(f)

def superadmin_requis(f):
    """Décorateur : restreint l'accès aux utilisateurs is_admin=True."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('login'))
        if not getattr(current_user, 'is_admin', False):
            flash("Accès réservé aux super-administrateurs.", "error")
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated

# ════════════════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════════════════

def get_entreprise():
    if current_user.is_authenticated and current_user.entreprise_id:
        return Entreprise.query.get(current_user.entreprise_id)
    return None


def creer_notification(entreprise_id, type, titre, message, lien=None, user_id=None):
    if user_id:
        cibles = [user_id]
    else:
        cibles = [u.id for u in Utilisateur.query.filter(
            Utilisateur.entreprise_id == entreprise_id,
            Utilisateur.role.in_(['admin', 'manager'])
        ).all()]
    for uid in cibles:
        db.session.add(Notification(
            utilisateur_id=uid, entreprise_id=entreprise_id,
            type=type, titre=titre, message=message, lien=lien
        ))
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()

# ════════════════════════════════════════════════════════════════
# CONTEXT PROCESSOR — injecte variables dans tous les templates
# ════════════════════════════════════════════════════════════════

@app.context_processor
def inject_globals():
    devise     = '€'
    entreprise = None
    role       = 'operateur'
    nb_notifs  = 0
    plan_actuel = 'free'

    if current_user.is_authenticated:
        devise      = getattr(current_user, 'devise', '€') or '€'
        entreprise  = get_entreprise()
        role        = getattr(current_user, 'role', 'operateur')
        nb_notifs   = Notification.query.filter_by(
            utilisateur_id=current_user.id, lue=False
        ).count()
        if entreprise:
            plan_actuel = entreprise.plan or 'free'

    est_pro = plan_actuel == 'pro'
    limites = PLANS.get(plan_actuel, PLANS['free'])['limites']
    show_onboarding = (
        current_user.is_authenticated and
        not getattr(current_user, 'onboarding_complete', True)
    )
    # Abonnement utilisateur
    ab = get_abonnement() if current_user.is_authenticated else None
    plan_ab = ab.plan if ab else 'free'
    ab_actif = ab.est_actif() if ab else False
    is_superadmin = getattr(current_user, 'is_admin', False) if current_user.is_authenticated else False

    return {
        'devise': devise, 'entreprise': entreprise, 'role': role,
        'est_admin':   role == 'admin',
        'est_manager': role in ('admin', 'manager'),
        'show_onboarding': show_onboarding,
        'nb_notifs': nb_notifs,
        'plan_actuel': plan_actuel,
        'est_pro': est_pro,
        'limites': limites,
        'abonnement': ab,
        'plan_ab': plan_ab,
        'ab_actif': ab_actif,
        'PRIX_AB': PRIX_AB,
        'LIMITES_AB': LIMITES_AB,
        'is_superadmin': is_superadmin,
    }

# ════════════════════════════════════════════════════════════════
# MIDDLEWARE & ERROR HANDLERS
# ════════════════════════════════════════════════════════════════

@app.before_request
def _check_session_timeout():
    """Déconnecte automatiquement après 5 min d'inactivité."""
    if current_user.is_authenticated:
        last_active = session.get('last_active')
        now = datetime.now().timestamp()
        if last_active and now - last_active > 300:  # 5 min
            session.clear()
            logout_user()
            flash("Session expirée. Veuillez vous reconnecter.", "error")
            return redirect(url_for('login'))
        session['last_active'] = now
        session.permanent = True


@app.before_request
def _log_req_start():
    request._start_time = time.time()


@app.after_request
def _log_req_end(response):
    if hasattr(request, '_start_time'):
        ms   = round((time.time() - request._start_time) * 1000)
        user = (current_user.username
                if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated
                else 'anonyme')
        if not request.path.startswith('/static'):
            lvl = logging.WARNING if response.status_code >= 400 else logging.INFO
            app.logger.log(lvl,
                f"{request.method} {request.path} → {response.status_code} ({ms}ms) [{user}]")
    return response


@app.errorhandler(404)
def err_404(e):
    return render_template('erreur.html', code=404, message="Page introuvable."), 404

@app.errorhandler(403)
def err_403(e):
    return render_template('erreur.html', code=403, message="Accès refusé."), 403

@app.errorhandler(500)
def err_500(e):
    app.logger.error(f"500 {request.path} : {e}", exc_info=True)
    return render_template('erreur.html', code=500,
                           message="Erreur serveur. Notre équipe a été notifiée."), 500

@app.errorhandler(429)
def err_429(e):
    return render_template('erreur.html', code=429,
                           message="Trop de tentatives. Attendez 1 minute."), 429

# ════════════════════════════════════════════════════════════════
# INIT DB
# ════════════════════════════════════════════════════════════════

def init_db():
    db.create_all()

    migrations = [
        "ALTER TABLE utilisateurs  ADD COLUMN devise             VARCHAR(10)  DEFAULT '€'",
        "ALTER TABLE utilisateurs  ADD COLUMN role               VARCHAR(20)  DEFAULT 'admin'",
        "ALTER TABLE utilisateurs  ADD COLUMN entreprise_id      INTEGER      DEFAULT NULL",
        "ALTER TABLE utilisateurs  ADD COLUMN email_verifie      BOOLEAN      DEFAULT 0",
        "ALTER TABLE utilisateurs  ADD COLUMN token_verification VARCHAR(100) DEFAULT NULL",
        "ALTER TABLE utilisateurs  ADD COLUMN token_reset        VARCHAR(100) DEFAULT NULL",
        "ALTER TABLE utilisateurs  ADD COLUMN token_reset_exp    DATETIME     DEFAULT NULL",
        "ALTER TABLE utilisateurs  ADD COLUMN onboarding_complete BOOLEAN     DEFAULT 0",
        "ALTER TABLE produits      ADD COLUMN entreprise_id      INTEGER      DEFAULT NULL",
        "ALTER TABLE categories    ADD COLUMN entreprise_id      INTEGER      DEFAULT NULL",
        "ALTER TABLE fournisseurs  ADD COLUMN entreprise_id      INTEGER      DEFAULT NULL",
        "ALTER TABLE mouvements    ADD COLUMN entreprise_id      INTEGER      DEFAULT NULL",
        "ALTER TABLE produits      ADD COLUMN code_barres       VARCHAR(100) DEFAULT NULL",
        "ALTER TABLE entreprises   ADD COLUMN stripe_customer_id VARCHAR(100) DEFAULT NULL",
        "ALTER TABLE entreprises   ADD COLUMN stripe_sub_id      VARCHAR(100) DEFAULT NULL",
        "ALTER TABLE entreprises   ADD COLUMN stripe_status      VARCHAR(30)  DEFAULT NULL",
        "ALTER TABLE utilisateurs  ADD COLUMN is_admin           BOOLEAN      DEFAULT 0",
    ]
    for sql in migrations:
        try:
            db.session.execute(db.text(sql))
            db.session.commit()
        except Exception:
            db.session.rollback()

    # Table abonnements
    try:
        db.session.execute(db.text("""
            CREATE TABLE IF NOT EXISTS abonnements (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      INTEGER NOT NULL UNIQUE,
                plan         VARCHAR(20) NOT NULL DEFAULT 'free',
                statut       VARCHAR(20) NOT NULL DEFAULT 'actif',
                date_debut   DATETIME,
                date_fin     DATETIME,
                cree_le      DATETIME DEFAULT CURRENT_TIMESTAMP,
                renouvele_le DATETIME
            )
        """))
        db.session.commit()
    except Exception:
        db.session.rollback()

    # Table notifications
    try:
        db.session.execute(db.text("""
            CREATE TABLE IF NOT EXISTS notifications (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                utilisateur_id  INTEGER NOT NULL,
                entreprise_id   INTEGER NOT NULL,
                type            VARCHAR(30)  NOT NULL,
                titre           VARCHAR(200) NOT NULL,
                message         TEXT NOT NULL,
                lien            VARCHAR(200),
                lue             BOOLEAN DEFAULT 0,
                cree_le         DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        db.session.commit()
    except Exception:
        db.session.rollback()

    # Entreprise par défaut
    if Entreprise.query.count() == 0:
        entreprise = Entreprise(nom='Mon Entreprise', slug='default')
        db.session.add(entreprise)
        db.session.flush()
    else:
        entreprise = Entreprise.query.first()

    # Admin seulement s'il n'existe pas
    if not Utilisateur.query.filter_by(username='admin').first():
        admin = Utilisateur(username='admin', role='admin',
                            entreprise_id=entreprise.id,
                            email_verifie=True, onboarding_complete=True,
                            is_admin=True)
        admin.set_password('admin123')
        db.session.add(admin)

    db.session.commit()

    # Rattacher données existantes sans entreprise
    for model in [Utilisateur, Produit, Categorie, Fournisseur, Mouvement]:
        model.query.filter_by(entreprise_id=None).update({'entreprise_id': entreprise.id})

    # Débloquer TOUS les comptes existants
    Utilisateur.query.filter(
        Utilisateur.email_verifie == False
    ).update({'email_verifie': True})

    # S'assurer que admin est vérifié
    u = Utilisateur.query.filter_by(username='admin').first()
    if u:
        u.email_verifie       = True
        u.onboarding_complete = True

    db.session.commit()

# ════════════════════════════════════════════════════════════════
# AUTH
# ════════════════════════════════════════════════════════════════

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit('5 per minute')
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = Utilisateur.query.filter_by(username=username).first()
        if user and user.check_password(password):
            # Bloquer uniquement les inscriptions autonomes non vérifiées
            if not user.email_verifie and user.email:
                flash("Vérifiez votre email avant de vous connecter.", "error")
                return redirect(url_for('login'))
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
# PRODUITS
# ════════════════════════════════════════════════════════════════

@app.route('/')
@login_required
def index():
    eid = current_user.entreprise_id
    produits     = Produit.query.filter_by(entreprise_id=eid).order_by(Produit.nom).all()
    categories   = Categorie.query.filter_by(entreprise_id=eid).order_by(Categorie.nom).all()
    fournisseurs = Fournisseur.query.filter_by(entreprise_id=eid).order_by(Fournisseur.nom).all()
    return render_template('index.html', produits=produits,
                           categories=categories, fournisseurs=fournisseurs)


@app.route('/add', methods=['POST'])
@login_required
@manager_ou_admin
def add():
    nom            = request.form.get('nom', '').strip()
    code_barres    = request.form.get('code_barres', '').strip() or None
    quantite       = request.form.get('quantite', '')
    prix           = request.form.get('prix', '')
    seuil          = request.form.get('seuil', '5')
    categorie_id   = request.form.get('categorie_id') or None
    fournisseur_id = request.form.get('fournisseur_id') or None
    if not nom:
        flash("Le nom est obligatoire.", "error")
        return redirect(url_for('index'))
    try:
        quantite = int(quantite); prix = float(prix); seuil = int(seuil)
    except ValueError:
        flash("Quantité, prix et seuil doivent être des nombres.", "error")
        return redirect(url_for('index'))
    nb = Produit.query.filter_by(entreprise_id=current_user.entreprise_id).count()
    # Admin : accès illimité sans vérification
    if not getattr(current_user, 'is_admin', False):
        lim_ab = limite_produits_ab()
        if nb >= lim_ab:
            ab = get_abonnement()
            plan = ab.plan if ab else 'free'
            if plan == 'free':
                flash(f"Limite atteinte ({nb}/{lim_ab} produits). Passez au plan Monthly ou Yearly.", "error")
            else:
                flash(f"Limite atteinte ({nb}/{lim_ab} produits).", "error")
            return redirect(url_for('index'))
        ok, msg = verifier_limite('produits', nb)
        if not ok:
            flash(msg, "error")
            return redirect(url_for('index'))
    db.session.add(Produit(nom=nom, code_barres=code_barres,
                           quantite=quantite, prix=prix, seuil=seuil,
                           categorie_id=categorie_id, fournisseur_id=fournisseur_id,
                           entreprise_id=current_user.entreprise_id))
    db.session.commit()
    flash(f"Produit « {nom} » ajouté.", "success")
    return redirect(url_for('index'))


@app.route('/update/<int:id>', methods=['GET', 'POST'])
@login_required
@manager_ou_admin
def update(id):
    p = Produit.query.filter_by(id=id, entreprise_id=current_user.entreprise_id).first_or_404()
    categories   = Categorie.query.filter_by(entreprise_id=current_user.entreprise_id).order_by(Categorie.nom).all()
    fournisseurs = Fournisseur.query.filter_by(entreprise_id=current_user.entreprise_id).order_by(Fournisseur.nom).all()
    if request.method == 'POST':
        try:
            p.nom            = request.form.get('nom', '').strip()
            p.code_barres    = request.form.get('code_barres', '').strip() or None
            p.quantite       = int(request.form.get('quantite', 0))
            p.prix           = float(request.form.get('prix', 0))
            p.seuil          = int(request.form.get('seuil', 5))
            p.categorie_id   = request.form.get('categorie_id') or None
            p.fournisseur_id = request.form.get('fournisseur_id') or None
            db.session.commit()
            flash(f"Produit « {p.nom} » mis à jour.", "success")
            return redirect(url_for('index'))
        except ValueError:
            flash("Données invalides.", "error")
    return render_template('update.html', produit=p,
                           categories=categories, fournisseurs=fournisseurs)


@app.route('/delete/<int:id>', methods=['POST'])
@login_required
@admin_requis
def delete(id):
    p = Produit.query.filter_by(id=id, entreprise_id=current_user.entreprise_id).first_or_404()
    Mouvement.query.filter_by(produit_id=id).delete()
    db.session.delete(p)
    db.session.commit()
    flash(f"Produit « {p.nom} » supprimé.", "success")
    return redirect(url_for('index'))


@app.route('/mouvement/<int:id>', methods=['POST'])
@login_required
@manager_ou_admin
def mouvement(id):
    p      = Produit.query.filter_by(id=id, entreprise_id=current_user.entreprise_id).first_or_404()
    action = request.form.get('action')
    note   = request.form.get('note', '')
    try:
        qte = int(request.form.get('qte', 0))
    except ValueError:
        flash("Quantité invalide.", "error")
        return redirect(url_for('index'))
    if qte <= 0:
        flash("La quantité doit être > 0.", "error")
        return redirect(url_for('index'))
    if action == 'sortie' and p.quantite < qte:
        flash("Stock insuffisant.", "error")
        return redirect(url_for('index'))
    delta = qte if action == 'entree' else -qte
    p.quantite += delta
    db.session.add(Mouvement(produit_id=p.id, produit_nom=p.nom,
                             type=action, quantite=qte, date=date.today(), note=note,
                             entreprise_id=current_user.entreprise_id))
    db.session.commit()
    verifier_et_alerter(p)
    flash(f"Mouvement enregistré ({'+' if delta > 0 else ''}{delta}).", "success")
    return redirect(url_for('index'))

# ════════════════════════════════════════════════════════════════
# CATÉGORIES
# ════════════════════════════════════════════════════════════════

@app.route('/categories')
@login_required
def categories():
    cats = Categorie.query.filter_by(entreprise_id=current_user.entreprise_id).order_by(Categorie.nom).all()
    return render_template('categories.html', categories=cats)

@app.route('/categories/add', methods=['POST'])
@login_required
@manager_ou_admin
def add_categorie():
    nom = request.form.get('nom', '').strip()
    if not nom:
        flash("Nom obligatoire.", "error")
        return redirect(url_for('categories'))
    if Categorie.query.filter_by(nom=nom, entreprise_id=current_user.entreprise_id).first():
        flash("Ce nom existe déjà.", "error")
        return redirect(url_for('categories'))
    nb = Categorie.query.filter_by(entreprise_id=current_user.entreprise_id).count()
    ok, msg = verifier_limite('categories', nb)
    if not ok:
        flash(msg, "error")
        return redirect(url_for('categories'))
    db.session.add(Categorie(nom=nom, entreprise_id=current_user.entreprise_id))
    db.session.commit()
    flash(f"Catégorie « {nom} » créée.", "success")
    return redirect(url_for('categories'))

@app.route('/categories/delete/<int:id>', methods=['POST'])
@login_required
@admin_requis
def delete_categorie(id):
    c = Categorie.query.filter_by(id=id, entreprise_id=current_user.entreprise_id).first_or_404()
    for p in c.produits: p.categorie_id = None
    db.session.delete(c)
    db.session.commit()
    flash("Catégorie supprimée.", "success")
    return redirect(url_for('categories'))

@app.route('/categories/edit/<int:id>', methods=['POST'])
@login_required
@manager_ou_admin
def edit_categorie(id):
    c = Categorie.query.filter_by(id=id, entreprise_id=current_user.entreprise_id).first_or_404()
    c.nom = request.form.get('nom', '').strip()
    db.session.commit()
    flash("Catégorie mise à jour.", "success")
    return redirect(url_for('categories'))

# ════════════════════════════════════════════════════════════════
# FOURNISSEURS
# ════════════════════════════════════════════════════════════════

@app.route('/fournisseurs')
@login_required
def fournisseurs():
    fours = Fournisseur.query.filter_by(entreprise_id=current_user.entreprise_id).order_by(Fournisseur.nom).all()
    return render_template('fournisseurs.html', fournisseurs=fours)

@app.route('/fournisseurs/add', methods=['POST'])
@login_required
@manager_ou_admin
def add_fournisseur():
    f = Fournisseur(nom=request.form.get('nom','').strip(),
                    contact=request.form.get('contact','').strip(),
                    email=request.form.get('email','').strip(),
                    telephone=request.form.get('telephone','').strip())
    if not f.nom:
        flash("Nom obligatoire.", "error")
        return redirect(url_for('fournisseurs'))
    nb = Fournisseur.query.filter_by(entreprise_id=current_user.entreprise_id).count()
    ok, msg = verifier_limite('fournisseurs', nb)
    if not ok:
        flash(msg, "error")
        return redirect(url_for('fournisseurs'))
    f.entreprise_id = current_user.entreprise_id
    db.session.add(f)
    db.session.commit()
    flash(f"Fournisseur « {f.nom} » ajouté.", "success")
    return redirect(url_for('fournisseurs'))

@app.route('/fournisseurs/delete/<int:id>', methods=['POST'])
@login_required
@admin_requis
def delete_fournisseur(id):
    f = Fournisseur.query.filter_by(id=id, entreprise_id=current_user.entreprise_id).first_or_404()
    for p in f.produits: p.fournisseur_id = None
    db.session.delete(f)
    db.session.commit()
    flash("Fournisseur supprimé.", "success")
    return redirect(url_for('fournisseurs'))

@app.route('/fournisseurs/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@manager_ou_admin
def edit_fournisseur(id):
    f = Fournisseur.query.filter_by(id=id, entreprise_id=current_user.entreprise_id).first_or_404()
    if request.method == 'POST':
        f.nom=request.form.get('nom','').strip(); f.contact=request.form.get('contact','').strip()
        f.email=request.form.get('email','').strip(); f.telephone=request.form.get('telephone','').strip()
        db.session.commit()
        flash(f"Fournisseur « {f.nom} » mis à jour.", "success")
        return redirect(url_for('fournisseurs'))
    return render_template('edit_fournisseur.html', fournisseur=f)

# ════════════════════════════════════════════════════════════════
# SCANNER
# ════════════════════════════════════════════════════════════════

@app.route('/scanner')
@login_required
def scanner():
    eid = current_user.entreprise_id
    produits = Produit.query.filter_by(entreprise_id=eid).order_by(Produit.nom).all()
    produits_json = json.dumps([{'id':p.id,'nom':p.nom,'code_barres':p.code_barres,
                                  'quantite':p.quantite,'seuil':p.seuil,'prix':p.prix}
                                 for p in produits], ensure_ascii=False)
    return render_template('scanner.html', produits_json=produits_json)

@app.route('/scanner/mouvement', methods=['POST'])
@login_required
def scanner_mouvement():
    produit_id = request.form.get('produit_id')
    action     = request.form.get('action')
    try:
        qte = int(request.form.get('qte', 1))
    except ValueError:
        return {'ok': False, 'message': 'Quantité invalide'}, 400
    p = db.session.get(Produit, int(produit_id)) if produit_id else None
    if not p:
        return {'ok': False, 'message': 'Produit introuvable'}, 404
    if action == 'sortie' and p.quantite < qte:
        return {'ok': False, 'message': 'Stock insuffisant'}, 400
    delta = qte if action == 'entree' else -qte
    p.quantite += delta
    db.session.add(Mouvement(produit_id=p.id, produit_nom=p.nom,
                             type=action, quantite=qte, date=date.today(),
                             note='Scanner code-barres',
                             entreprise_id=current_user.entreprise_id))
    db.session.commit()
    verifier_et_alerter(p)
    return {'ok': True, 'nom': p.nom, 'nouveau_stock': p.quantite, 'delta': delta}

# ════════════════════════════════════════════════════════════════
# DASHBOARD & GRAPHIQUES
# ════════════════════════════════════════════════════════════════

@app.route('/dashboard')
@login_required
def dashboard():
    eid = current_user.entreprise_id
    produits = Produit.query.filter_by(entreprise_id=eid).order_by(Produit.nom).all()
    produits_json = json.dumps([{'id':p.id,'nom':p.nom,'quantite':p.quantite,
                                  'seuil':p.seuil,'prix':p.prix} for p in produits], ensure_ascii=False)
    return render_template('dashboard.html', produits_json=produits_json)

@app.route('/graphiques')
@login_required
def graphiques():
    from sqlalchemy import func
    from datetime import timedelta
    eid     = current_user.entreprise_id
    produits = Produit.query.filter_by(entreprise_id=eid).order_by(Produit.nom).all()
    cutoff  = date.today() - timedelta(days=30)
    entrees = (db.session.query(Mouvement.date, func.sum(Mouvement.quantite).label('total'))
               .filter(Mouvement.entreprise_id==eid, Mouvement.type=='entree', Mouvement.date>=cutoff)
               .group_by(Mouvement.date).order_by(Mouvement.date).all())
    sorties = (db.session.query(Mouvement.date, func.sum(Mouvement.quantite).label('total'))
               .filter(Mouvement.entreprise_id==eid, Mouvement.type=='sortie', Mouvement.date>=cutoff)
               .group_by(Mouvement.date).order_by(Mouvement.date).all())
    top_mvt = (db.session.query(Mouvement.produit_nom, func.sum(Mouvement.quantite).label('total'))
               .filter(Mouvement.entreprise_id==eid)
               .group_by(Mouvement.produit_nom)
               .order_by(func.sum(Mouvement.quantite).desc()).limit(8).all())
    data = {
        'produits': [{'id':p.id,'nom':p.nom,'quantite':p.quantite,'seuil':p.seuil,'prix':p.prix} for p in produits],
        'entrees':  [{'date':str(r.date),'total':r.total} for r in entrees],
        'sorties':  [{'date':str(r.date),'total':r.total} for r in sorties],
        'top_mvt':  [{'produit_nom':r.produit_nom,'total':r.total} for r in top_mvt],
        'stock_val': [],
    }
    return render_template('graphiques.html', data_json=json.dumps(data, ensure_ascii=False))

# ════════════════════════════════════════════════════════════════
# ALERTES EMAIL
# ════════════════════════════════════════════════════════════════

def envoyer_alerte_stock(produits_alertes):
    if not produits_alertes: return
    destinataires = [u.email for u in Utilisateur.query.all() if u.email]
    if not destinataires: return
    nb_rup = sum(1 for p in produits_alertes if p['statut']=='rupture')
    nb_fbl = sum(1 for p in produits_alertes if p['statut']=='faible')
    lignes = ""
    for p in produits_alertes:
        cbg = '#FEF0EE' if p['statut']=='rupture' else '#FFF4E6'
        ctxt= '#C0392B' if p['statut']=='rupture' else '#B7651A'
        lbl = 'RUPTURE' if p['statut']=='rupture' else 'Stock faible'
        lignes += f'<tr><td style="padding:10px 16px;border-bottom:1px solid #ddd"><strong>{p["nom"]}</strong></td><td style="text-align:center;padding:10px">{p["quantite"]}</td><td style="text-align:center;padding:10px;color:#777">{p["seuil"]}</td><td style="text-align:center;padding:10px"><span style="background:{cbg};color:{ctxt};padding:3px 8px;border-radius:4px;font-size:11px">{lbl}</span></td></tr>'
    html = f'<html><body style="font-family:Arial;background:#f5f5f5"><div style="max-width:600px;margin:32px auto;background:#fff;border-radius:12px;overflow:hidden"><div style="background:#1a1a18;padding:20px 28px;color:#fff;font-family:monospace">stockapp</div><div style="padding:24px 28px"><h2 style="margin:0 0 6px">Alerte stock</h2><p style="color:#777;margin:0">{len(produits_alertes)} produit(s) en alerte</p></div><div style="padding:0 28px;display:flex;gap:12px"><div style="flex:1;background:#fef0ee;border-radius:8px;padding:12px"><div style="color:#c0392b;font-size:11px;text-transform:uppercase">Ruptures</div><div style="font-size:24px;font-weight:700;color:#c0392b">{nb_rup}</div></div><div style="flex:1;background:#fff4e6;border-radius:8px;padding:12px"><div style="color:#b7651a;font-size:11px;text-transform:uppercase">Faible</div><div style="font-size:24px;font-weight:700;color:#b7651a">{nb_fbl}</div></div></div><div style="padding:20px 28px"><table style="width:100%;border-collapse:collapse"><thead><tr style="background:#f5f5f5"><th style="padding:10px;text-align:left;font-size:11px;color:#777">Produit</th><th style="padding:10px;font-size:11px;color:#777">Stock</th><th style="padding:10px;font-size:11px;color:#777">Seuil</th><th style="padding:10px;font-size:11px;color:#777">Statut</th></tr></thead><tbody>{lignes}</tbody></table></div><div style="padding:16px 28px;background:#f5f5f5;font-size:12px;color:#777">Email automatique · {datetime.now().strftime("%d/%m/%Y %H:%M")}</div></div></body></html>'
    try:
        mail.send(Message(subject=f"[StockApp] {len(produits_alertes)} produit(s) en alerte",
                          recipients=destinataires, html=html))
    except Exception as e:
        app.logger.error(f"Email alerte : {e}")


def verifier_et_alerter(produit):
    alertes = []
    if produit.quantite == 0:
        alertes.append({'nom':produit.nom,'quantite':0,'seuil':produit.seuil,'statut':'rupture'})
        creer_notification(entreprise_id=produit.entreprise_id, type='rupture',
                           titre=f'Rupture — {produit.nom}',
                           message=f'« {produit.nom} » est épuisé (stock = 0).', lien='/')
    elif produit.quantite <= produit.seuil:
        alertes.append({'nom':produit.nom,'quantite':produit.quantite,'seuil':produit.seuil,'statut':'faible'})
        creer_notification(entreprise_id=produit.entreprise_id, type='stock_bas',
                           titre=f'Stock faible — {produit.nom}',
                           message=f'Il reste {produit.quantite} unité(s) (seuil : {produit.seuil}).', lien='/')
    envoyer_alerte_stock(alertes)


@app.route('/alertes/envoyer', methods=['POST'])
@login_required
@plan_requis('alertes_email')
def envoyer_rapport_alertes():
    alertes = [{'nom':p.nom,'quantite':p.quantite,'seuil':p.seuil,
                'statut':'rupture' if p.quantite==0 else 'faible'}
               for p in Produit.query.filter_by(entreprise_id=current_user.entreprise_id).all()
               if p.quantite <= p.seuil]
    if not alertes:
        flash("Aucun produit en alerte.", "success")
        return redirect(url_for('index'))
    envoyer_alerte_stock(alertes)
    flash(f"Email envoyé pour {len(alertes)} produit(s).", "success")
    return redirect(url_for('index'))


@app.route('/parametres', methods=['GET', 'POST'])
@app.route('/parametres/email', methods=['GET', 'POST'])
@login_required
def parametres_email():
    if request.method == 'POST':
        current_user.email  = request.form.get('email', '').strip()
        current_user.devise = request.form.get('devise', '€').strip() or '€'
        db.session.commit()
        flash("Paramètres mis à jour.", "success")
        return redirect(url_for('parametres_email'))
    users = Utilisateur.query.filter_by(
        entreprise_id=current_user.entreprise_id
    ).all() if current_user.role == 'admin' else []
    plans = PLANS
    return render_template('parametres.html', user=current_user,
                           users=users, plans=plans)

# ════════════════════════════════════════════════════════════════
# EXPORTS
# ════════════════════════════════════════════════════════════════

@app.route('/export/csv/produits')
@login_required
@manager_ou_admin
def export_csv_produits():
    produits = Produit.query.filter_by(entreprise_id=current_user.entreprise_id).order_by(Produit.nom).all()
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['ID','Nom','Quantite','Prix (EUR)','Seuil','Statut'])
    for p in produits:
        writer.writerow([p.id,p.nom,p.quantite,f"{p.prix:.2f}",p.seuil,
                         'Rupture' if p.statut=='rupture' else ('Faible' if p.statut=='faible' else 'OK')])
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8-sig'
    response.headers['Content-Disposition'] = f'attachment; filename="produits_{datetime.now().strftime("%Y%m%d_%H%M")}.csv"'
    return response


@app.route('/export/csv/mouvements')
@login_required
@manager_ou_admin
def export_csv_mouvements():
    mvts = Mouvement.query.filter_by(entreprise_id=current_user.entreprise_id).order_by(Mouvement.date.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['Date','Produit','Type','Quantite','Note'])
    for m in mvts:
        writer.writerow([m.date,m.produit_nom,'Entree' if m.type=='entree' else 'Sortie',m.quantite,m.note or ''])
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8-sig'
    response.headers['Content-Disposition'] = f'attachment; filename="mouvements_{datetime.now().strftime("%Y%m%d_%H%M")}.csv"'
    return response


@app.route('/export/pdf/stock')
@login_required
@manager_ou_admin
def export_pdf_stock():
    produits = Produit.query.filter_by(entreprise_id=current_user.entreprise_id).order_by(Produit.nom).all()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            rightMargin=15*mm, leftMargin=15*mm,
                            topMargin=20*mm, bottomMargin=15*mm)
    styles = getSampleStyleSheet()
    story  = []
    story.append(Paragraph("Rapport de stock", ParagraphStyle('T', parent=styles['Title'],
                 fontSize=20, spaceAfter=4, textColor=colors.HexColor('#1A1A18'), alignment=TA_LEFT)))
    story.append(Paragraph(
        f"Genere le {datetime.now().strftime('%d/%m/%Y a %H:%M')} par {current_user.username}",
        ParagraphStyle('S', parent=styles['Normal'], fontSize=10,
                       textColor=colors.HexColor('#7A7870'), spaceAfter=14)))
    valeur = sum(p.valeur for p in produits)
    nb_alerte  = sum(1 for p in produits if p.statut=='faible')
    nb_rupture = sum(1 for p in produits if p.statut=='rupture')
    kpi = Table([['Références','Valeur totale','Alertes','Ruptures'],
                 [str(len(produits)),f"{valeur:,.0f} EUR",str(nb_alerte),str(nb_rupture)]],
                colWidths=[42*mm,52*mm,42*mm,42*mm])
    kpi.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#F5F4F0')),
        ('TEXTCOLOR',(0,0),(-1,0),colors.HexColor('#7A7870')),
        ('FONTNAME',(0,1),(-1,1),'Helvetica-Bold'),
        ('FONTSIZE',(0,0),(-1,0),8),('FONTSIZE',(0,1),(-1,1),18),
        ('ALIGN',(0,0),(-1,-1),'CENTER'),('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('BOX',(0,0),(-1,-1),0.5,colors.HexColor('#DDDBD4')),
        ('INNERGRID',(0,0),(-1,-1),0.5,colors.HexColor('#DDDBD4')),
        ('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6),
    ]))
    story.append(kpi); story.append(Spacer(1,10*mm))
    story.append(Paragraph("Liste des produits", styles['Heading2']))
    rows = [['Nom','Quantite','Seuil','Prix unitaire','Valeur stock','Statut']]
    for p in produits:
        lbl = 'Rupture' if p.statut=='rupture' else ('Faible' if p.statut=='faible' else 'OK')
        rows.append([p.nom,str(p.quantite),str(p.seuil),f"{p.prix:.2f} EUR",f"{p.valeur:,.2f} EUR",lbl])
    t = Table(rows, colWidths=[65*mm,22*mm,22*mm,30*mm,30*mm,20*mm], repeatRows=1)
    cmds = [
        ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#1A1A18')),
        ('TEXTCOLOR',(0,0),(-1,0),colors.white),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),
        ('FONTSIZE',(0,0),(-1,-1),9),('ALIGN',(1,0),(-1,-1),'CENTER'),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#FAFAF8')]),
        ('BOX',(0,0),(-1,-1),0.5,colors.HexColor('#DDDBD4')),
        ('INNERGRID',(0,0),(-1,-1),0.5,colors.HexColor('#DDDBD4')),
    ]
    for i, p in enumerate(produits, start=1):
        if p.statut=='rupture':
            cmds += [('TEXTCOLOR',(5,i),(5,i),colors.HexColor('#C0392B')),
                     ('FONTNAME',(5,i),(5,i),'Helvetica-Bold')]
        elif p.statut=='faible':
            cmds.append(('TEXTCOLOR',(5,i),(5,i),colors.HexColor('#B7651A')))
    t.setStyle(TableStyle(cmds)); story.append(t)
    doc.build(story); buffer.seek(0)
    response = make_response(buffer.read())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename="rapport_{datetime.now().strftime("%Y%m%d_%H%M")}.pdf"'
    return response

# ════════════════════════════════════════════════════════════════
# INSCRIPTION & AUTH PUBLIQUE
# ════════════════════════════════════════════════════════════════

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    plans_disponibles = [
        {'id':'free','nom':'Gratuit','prix':'0 €/mois','limite':'50 produits'},
        {'id':'pro', 'nom':'Pro',    'prix':'9 €/mois','limite':'Illimité'},
    ]
    if request.method == 'POST':
        import re, secrets as sec
        nom_entreprise = request.form.get('nom_entreprise','').strip()
        username       = request.form.get('username','').strip()
        email          = request.form.get('email','').strip()
        password       = request.form.get('password','')
        confirm        = request.form.get('confirm','')
        plan           = request.form.get('plan','free')
        erreurs = []
        if not nom_entreprise: erreurs.append("Le nom de l'entreprise est obligatoire.")
        if not username:       erreurs.append("Le nom d'utilisateur est obligatoire.")
        if not email or '@' not in email: erreurs.append("Email invalide.")
        if len(password) < 6:  erreurs.append("Mot de passe trop court (6 caractères min.).")
        if password != confirm: erreurs.append("Les mots de passe ne correspondent pas.")
        if Utilisateur.query.filter_by(username=username).first():
            erreurs.append("Ce nom d'utilisateur est déjà pris.")
        if Utilisateur.query.filter_by(email=email).first():
            erreurs.append("Cet email est déjà utilisé.")
        if plan not in ('free','pro'): plan = 'free'
        if erreurs:
            for e in erreurs: flash(e, "error")
            return render_template('register.html', plans=plans_disponibles)
        slug = re.sub(r'[^a-z0-9]+','-',nom_entreprise.lower()).strip('-')
        if Entreprise.query.filter_by(slug=slug).first():
            slug = f"{slug}-{Entreprise.query.count()+1}"
        token = sec.token_urlsafe(32)
        entreprise = Entreprise(nom=nom_entreprise, slug=slug, plan=plan)
        db.session.add(entreprise); db.session.flush()
        admin = Utilisateur(username=username, email=email, role='admin',
                            entreprise_id=entreprise.id,
                            email_verifie=False, token_verification=token)
        admin.set_password(password)
        db.session.add(admin); db.session.commit()
        _envoyer_email_bienvenue(admin, entreprise, token)
        flash("Compte créé ! Vérifiez votre email pour activer votre espace.", "success")
        return redirect(url_for('login'))
    return render_template('register.html', plans=plans_disponibles)


@app.route('/verifier-email/<token>')
def verifier_email(token):
    user = Utilisateur.query.filter_by(token_verification=token).first()
    if not user:
        flash("Lien invalide ou expiré.", "error")
        return redirect(url_for('login'))
    user.email_verifie = True; user.token_verification = None
    db.session.commit()
    login_user(user)
    flash(f"Email vérifié ! Bienvenue, {user.username} 🎉", "success")
    return redirect(url_for('index'))


def _envoyer_email_bienvenue(user, entreprise, token):
    if not app.config.get('MAIL_USERNAME'): return
    lien = url_for('verifier_email', token=token, _external=True)
    html = f"""<html><body style="font-family:Arial;background:#f5f5f5">
    <div style="max-width:600px;margin:32px auto;background:#fff;border-radius:12px;overflow:hidden">
      <div style="background:#1a1a18;padding:20px 28px;color:#fff;font-family:monospace">📦 stockapp</div>
      <div style="padding:32px 28px">
        <h2>Bienvenue, {user.username} !</h2>
        <p style="color:#7a7870">Votre espace <strong>{entreprise.nom}</strong> est créé.</p>
        <a href="{lien}" style="display:inline-block;background:#1a1a18;color:#fff;padding:12px 28px;border-radius:8px;text-decoration:none;font-weight:500">Vérifier mon email →</a>
      </div>
    </div></body></html>"""
    try:
        mail.send(Message(subject=f"[StockApp] Vérifiez votre email",
                          recipients=[user.email], html=html))
    except Exception as e:
        app.logger.error(f"Email bienvenue : {e}")


@app.route('/mot-de-passe-oublie', methods=['GET', 'POST'])
def mot_de_passe_oublie():
    if current_user.is_authenticated: return redirect(url_for('index'))
    if request.method == 'POST':
        from datetime import timedelta
        import secrets as sec
        email = request.form.get('email','').strip()
        user  = Utilisateur.query.filter_by(email=email).first()
        flash("Si cet email existe, un lien a été envoyé.", "success")
        if user:
            token = sec.token_urlsafe(32)
            user.token_reset     = token
            user.token_reset_exp = datetime.now() + timedelta(hours=1)
            db.session.commit()
            _envoyer_email_reset(user, token)
        return redirect(url_for('login'))
    return render_template('forgot_password.html')


@app.route('/reinitialiser-mot-de-passe/<token>', methods=['GET', 'POST'])
def reinitialiser_mot_de_passe(token):
    if current_user.is_authenticated: return redirect(url_for('index'))
    user = Utilisateur.query.filter_by(token_reset=token).first()
    if not user or not user.token_reset_exp or datetime.now() > user.token_reset_exp:
        flash("Lien invalide ou expiré.", "error")
        return redirect(url_for('mot_de_passe_oublie'))
    if request.method == 'POST':
        nouveau = request.form.get('password','')
        confirm = request.form.get('confirm','')
        if len(nouveau) < 6:
            flash("Minimum 6 caractères.", "error")
            return render_template('reset_password.html', token=token)
        if nouveau != confirm:
            flash("Les mots de passe ne correspondent pas.", "error")
            return render_template('reset_password.html', token=token)
        user.set_password(nouveau)
        user.token_reset = None; user.token_reset_exp = None; user.email_verifie = True
        db.session.commit()
        flash("Mot de passe modifié.", "success")
        return redirect(url_for('login'))
    return render_template('reset_password.html', token=token)


def _envoyer_email_reset(user, token):
    if not app.config.get('MAIL_USERNAME'):
        app.logger.warning(f"[RESET] Token pour {user.email} : {token}")
        return
    lien = url_for('reinitialiser_mot_de_passe', token=token, _external=True)
    html = f"""<html><body style="font-family:Arial;background:#f5f5f5">
    <div style="max-width:600px;margin:32px auto;background:#fff;border-radius:12px;overflow:hidden">
      <div style="background:#1a1a18;padding:20px 28px;color:#fff;font-family:monospace">📦 stockapp</div>
      <div style="padding:32px 28px">
        <h2>Réinitialisation de mot de passe</h2>
        <p style="color:#7a7870">Bonjour <strong>{user.username}</strong>,</p>
        <p style="color:#7a7870">Ce lien est valable <strong>1 heure</strong>.</p>
        <a href="{lien}" style="display:inline-block;background:#1a1a18;color:#fff;padding:12px 28px;border-radius:8px;text-decoration:none;font-weight:500">Choisir un nouveau mot de passe →</a>
      </div>
    </div></body></html>"""
    try:
        mail.send(Message(subject="[StockApp] Réinitialisation mot de passe",
                          recipients=[user.email], html=html))
    except Exception as e:
        app.logger.error(f"Email reset : {e}")

# ════════════════════════════════════════════════════════════════
# UTILISATEURS & RÔLES
# ════════════════════════════════════════════════════════════════

@app.route('/utilisateurs')
@login_required
@admin_requis
def utilisateurs():
    users = Utilisateur.query.filter_by(entreprise_id=current_user.entreprise_id).all()
    return render_template('utilisateurs.html', users=users)


@app.route('/utilisateurs/add', methods=['POST'])
@login_required
@admin_requis
def add_utilisateur():
    nb = Utilisateur.query.filter_by(entreprise_id=current_user.entreprise_id).count()
    ok, msg = verifier_limite('utilisateurs', nb)
    if not ok:
        flash(msg, "error")
        return redirect(url_for('utilisateurs'))
    username = request.form.get('username','').strip()
    password = request.form.get('password','')
    role     = request.form.get('role','operateur')
    if not username or not password:
        flash("Nom d'utilisateur et mot de passe obligatoires.", "error")
        return redirect(url_for('utilisateurs'))
    if Utilisateur.query.filter_by(username=username).first():
        flash("Ce nom d'utilisateur est déjà pris.", "error")
        return redirect(url_for('utilisateurs'))
    if len(password) < 6:
        flash("Mot de passe trop court.", "error")
        return redirect(url_for('utilisateurs'))
    u = Utilisateur(username=username, role=role,
                    entreprise_id=current_user.entreprise_id,
                    email_verifie=True)  # créé par admin = vérifié
    u.set_password(password)
    db.session.add(u); db.session.commit()
    flash(f"Utilisateur « {username} » créé.", "success")
    return redirect(url_for('utilisateurs'))


@app.route('/utilisateurs/delete/<int:id>', methods=['POST'])
@login_required
@admin_requis
def delete_utilisateur(id):
    u = Utilisateur.query.filter_by(id=id, entreprise_id=current_user.entreprise_id).first_or_404()
    if u.id == current_user.id:
        flash("Vous ne pouvez pas supprimer votre propre compte.", "error")
        return redirect(url_for('utilisateurs'))
    db.session.delete(u); db.session.commit()
    flash(f"Utilisateur « {u.username} » supprimé.", "success")
    return redirect(url_for('utilisateurs'))


@app.route('/utilisateurs/role/<int:id>', methods=['POST'])
@login_required
@admin_requis
def changer_role(id):
    u = Utilisateur.query.filter_by(id=id, entreprise_id=current_user.entreprise_id).first_or_404()
    if u.id == current_user.id:
        flash("Vous ne pouvez pas changer votre propre rôle.", "error")
        return redirect(url_for('utilisateurs'))
    nouveau_role = request.form.get('role','operateur')
    if nouveau_role not in ('admin','manager','operateur'):
        flash("Rôle invalide.", "error")
        return redirect(url_for('utilisateurs'))
    u.role = nouveau_role; db.session.commit()
    flash(f"Rôle de « {u.username} » → {nouveau_role}.", "success")
    return redirect(url_for('utilisateurs'))

# ════════════════════════════════════════════════════════════════
# HEALTH CHECK & MÉTRIQUES
# ════════════════════════════════════════════════════════════════

@app.route('/favicon.ico')
def favicon():
    return '', 204  # No content — évite le 404 dans les logs


@app.route('/health')
def health_check():
    import platform
    status = {'ok': True, 'checks': {}}
    try:
        db.session.execute(db.text('SELECT 1'))
        status['checks']['database'] = 'ok'
    except Exception as e:
        status['checks']['database'] = f'error: {e}'
        status['ok'] = False
    status['env']    = os.environ.get('FLASK_ENV','development')
    status['python'] = platform.python_version()
    return status, (200 if status['ok'] else 503)


@app.route('/metrics')
@login_required
@admin_requis
def metrics():
    from sqlalchemy import func
    eid = current_user.entreprise_id
    return {
        'produits':   {'total': Produit.query.filter_by(entreprise_id=eid).count(),
                       'ruptures': Produit.query.filter_by(entreprise_id=eid, quantite=0).count()},
        'mouvements': {'total': Mouvement.query.filter_by(entreprise_id=eid).count()},
        'plan':       get_entreprise().plan if get_entreprise() else 'unknown',
    }

# ════════════════════════════════════════════════════════════════
# STRIPE
# ════════════════════════════════════════════════════════════════

def get_stripe():
    try:
        import stripe as _stripe
        _stripe.api_key = os.environ.get('STRIPE_SECRET_KEY','')
        return _stripe
    except ImportError:
        return None


@app.route('/tarifs')
def tarifs():
    return render_template('tarifs.html', plans=PLANS, connecte=current_user.is_authenticated)


@app.route('/abonnement')
@login_required
@admin_requis
def abonnement():
    return render_template('abonnement.html', plans=PLANS, entreprise=get_entreprise())


@app.route('/stripe/checkout/<plan_id>', methods=['POST'])
@login_required
@admin_requis
def stripe_checkout(plan_id):
    if plan_id not in PLANS or PLANS[plan_id]['price_id'] is None:
        flash("Plan invalide.", "error"); return redirect(url_for('abonnement'))
    stripe = get_stripe()
    if stripe is None:
        flash("Paiement non disponible pour le moment. Contactez l'administrateur.", "error")
        return redirect(url_for('abonnement'))
    if not stripe.api_key:
        flash("Paiement non configuré. Contactez l'administrateur.", "error")
        return redirect(url_for('abonnement'))
    entreprise = get_entreprise()
    try:
        if not entreprise.stripe_customer_id:
            customer = stripe.Customer.create(email=current_user.email or '', name=entreprise.nom,
                                              metadata={'entreprise_id': str(entreprise.id)})
            entreprise.stripe_customer_id = customer.id; db.session.commit()
        session = stripe.checkout.Session.create(
            customer=entreprise.stripe_customer_id,
            payment_method_types=['card'],
            line_items=[{'price': PLANS[plan_id]['price_id'], 'quantity': 1}],
            mode='subscription',
            success_url=url_for('stripe_succes', _external=True)+'?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=url_for('abonnement', _external=True),
            metadata={'entreprise_id': str(entreprise.id), 'plan': plan_id},
        )
        return redirect(session.url, code=303)
    except Exception as e:
        flash(f"Erreur Stripe : {e}", "error"); return redirect(url_for('abonnement'))


@app.route('/stripe/succes')
@login_required
def stripe_succes():
    flash("Abonnement Pro activé 🎉", "success")
    creer_notification(entreprise_id=current_user.entreprise_id, type='succes',
                       titre='Abonnement Pro activé',
                       message='Tous les plafonds ont été levés.',
                       lien=url_for('abonnement'))
    return redirect(url_for('index'))


@app.route('/stripe/portail', methods=['POST'])
@login_required
@admin_requis
def stripe_portail():
    stripe = get_stripe()
    if stripe is None or not stripe.api_key:
        flash("Stripe non configuré.", "error"); return redirect(url_for('abonnement'))
    entreprise = get_entreprise()
    if not entreprise or not entreprise.stripe_customer_id:
        flash("Aucun abonnement actif.", "error"); return redirect(url_for('abonnement'))
    try:
        session = stripe.billing_portal.Session.create(
            customer=entreprise.stripe_customer_id,
            return_url=url_for('abonnement', _external=True))
        return redirect(session.url, code=303)
    except Exception as e:
        flash(f"Erreur Stripe : {e}", "error"); return redirect(url_for('abonnement'))


@app.route('/stripe/webhook', methods=['POST'])
@csrf.exempt
def stripe_webhook():
    stripe = get_stripe()
    if stripe is None:
        return {'error': 'stripe not installed'}, 500
    payload = request.get_data()
    sig     = request.headers.get('Stripe-Signature','')
    try:
        event = stripe.Webhook.construct_event(
            payload, sig, os.environ.get('STRIPE_WEBHOOK_SECRET',''))
    except Exception as e:
        return {'error': str(e)}, 400
    data = event['data']['object']
    if event['type'] == 'checkout.session.completed':
        eid = data.get('metadata',{}).get('entreprise_id')
        sub_id = data.get('subscription')
        if eid and sub_id:
            e = db.session.get(Entreprise, int(eid))
            if e:
                e.plan='pro'; e.stripe_sub_id=sub_id; e.stripe_status='active'
                db.session.commit()
    elif event['type'] in ('customer.subscription.updated','customer.subscription.deleted'):
        e = Entreprise.query.filter_by(stripe_sub_id=data['id']).first()
        if e:
            statut = data.get('status','canceled'); e.stripe_status = statut
            if statut in ('canceled','unpaid','incomplete_expired'):
                e.plan = 'free'
            db.session.commit()
    return {'ok': True}


# ════════════════════════════════════════════════════════════════
# CODES-BARRES — association rapide
# ════════════════════════════════════════════════════════════════

@app.route('/produits/associer-codes', methods=['GET', 'POST'])
@login_required
@manager_ou_admin
def associer_codes():
    """Page pour associer les codes-barres aux produits existants."""
    eid = current_user.entreprise_id
    produits = Produit.query.filter_by(entreprise_id=eid).order_by(Produit.nom).all()

    if request.method == 'POST':
        updated = 0
        for p in produits:
            code = request.form.get(f'code_{p.id}', '').strip()
            if code and code != (p.code_barres or ''):
                p.code_barres = code
                updated += 1
            elif not code and p.code_barres:
                p.code_barres = None
                updated += 1
        db.session.commit()
        flash(f"{updated} produit(s) mis à jour.", "success")
        return redirect(url_for('associer_codes'))

    return render_template('associer_codes.html', produits=produits)


@app.route('/produits/code-barres/<int:id>', methods=['POST'])
@login_required
@manager_ou_admin
def update_code_barres(id):
    """Met à jour le code-barres d'un produit (appelé depuis le scanner)."""
    p = Produit.query.filter_by(
        id=id, entreprise_id=current_user.entreprise_id
    ).first_or_404()
    p.code_barres = request.form.get('code_barres', '').strip() or None
    db.session.commit()
    return {'ok': True, 'nom': p.nom, 'code_barres': p.code_barres}



# ════════════════════════════════════════════════════════════════
# GESTION DES RÔLES ADMIN
# ════════════════════════════════════════════════════════════════

@app.route('/admin/promouvoir/<int:id>', methods=['POST'])
@login_required
@superadmin_requis
def promouvoir_admin(id):
    """Promouvoit un utilisateur en super-admin."""
    u = Utilisateur.query.filter_by(
        id=id, entreprise_id=current_user.entreprise_id
    ).first_or_404()
    if u.id == current_user.id:
        flash("Vous êtes déjà super-admin.", "error")
        return redirect(url_for('utilisateurs'))
    u.is_admin = True
    u.role     = 'admin'
    db.session.commit()
    flash(f"« {u.username} » est maintenant super-admin.", "success")
    creer_notification(
        entreprise_id=current_user.entreprise_id,
        type='info',
        titre='Promotion super-admin',
        message=f'{u.username} a été promu super-administrateur.',
    )
    return redirect(url_for('utilisateurs'))


@app.route('/admin/retrograder/<int:id>', methods=['POST'])
@login_required
@superadmin_requis
def retrograder_admin(id):
    """Retire les droits super-admin d'un utilisateur."""
    u = Utilisateur.query.filter_by(
        id=id, entreprise_id=current_user.entreprise_id
    ).first_or_404()
    if u.id == current_user.id:
        flash("Vous ne pouvez pas vous rétrograder vous-même.", "error")
        return redirect(url_for('utilisateurs'))
    u.is_admin = False
    db.session.commit()
    flash(f"Droits admin retirés à « {u.username} ».", "success")
    return redirect(url_for('utilisateurs'))


@app.route('/admin/utilisateurs')
@login_required
@superadmin_requis
def admin_utilisateurs():
    """Vue admin : tous les utilisateurs de toutes les entreprises."""
    tous = Utilisateur.query.order_by(Utilisateur.id.desc()).all()
    return {'utilisateurs': [
        {'id': u.id, 'username': u.username, 'email': u.email,
         'role': u.role, 'is_admin': u.is_admin,
         'entreprise_id': u.entreprise_id}
        for u in tous
    ]}

# ════════════════════════════════════════════════════════════════
# ABONNEMENTS UTILISATEUR — upgrade / gestion
# ════════════════════════════════════════════════════════════════

@app.route('/upgrade')
@login_required
def upgrade_page():
    """Page de choix d'abonnement."""
    ab = get_abonnement()
    return render_template('upgrade.html', ab=ab, PRIX_AB=PRIX_AB, LIMITES_AB=LIMITES_AB)


@app.route('/upgrade/<plan>', methods=['POST'])
@login_required
def upgrade_plan(plan):
    """Passe l'utilisateur au plan choisi (monthly ou yearly).
    En production : intégrer Stripe avant de changer le plan.
    """
    if plan not in ('monthly', 'yearly'):
        flash("Plan invalide.", "error")
        return redirect(url_for('upgrade_page'))

    from datetime import timedelta
    ab = get_abonnement()
    if not ab:
        ab = Abonnement(user_id=current_user.id)
        db.session.add(ab)

    duree = PRIX_AB[plan]['duree']
    ab.plan        = plan
    ab.statut      = 'actif'
    ab.date_debut  = datetime.now()
    ab.date_fin    = datetime.now() + timedelta(days=duree)
    ab.renouvele_le= datetime.now()
    db.session.commit()

    label = PRIX_AB[plan]['label']
    flash(f"Abonnement {plan.upper()} activé ({label}) ! Merci 🎉", "success")
    creer_notification(
        entreprise_id=current_user.entreprise_id,
        type='succes',
        titre=f'Plan {plan.upper()} activé',
        message="Votre abonnement " + plan.upper() + " (" + label + ") est actif.",
        lien='/upgrade'
    )
    return redirect(url_for('upgrade_page'))


@app.route('/upgrade/annuler', methods=['POST'])
@login_required
def annuler_abonnement():
    """Repasse l'utilisateur en Free."""
    ab = get_abonnement()
    if ab and ab.plan != 'free':
        ab.plan     = 'free'
        ab.statut   = 'actif'
        ab.date_fin = None
        db.session.commit()
        flash("Abonnement annulé. Vous êtes repassé au plan gratuit.", "success")
    return redirect(url_for('upgrade_page'))


@app.route('/abonnement/statut')
@login_required
def statut_abonnement_api():
    """API JSON — statut abonnement de l'utilisateur connecté."""
    ab = get_abonnement()
    return ab.to_dict() if ab else {'plan': 'free', 'statut': 'actif', 'est_actif': True}

# ════════════════════════════════════════════════════════════════
# NOTIFICATIONS
# ════════════════════════════════════════════════════════════════

@app.route('/notifications')
@login_required
def notifications():
    notifs = Notification.query.filter_by(utilisateur_id=current_user.id)\
                               .order_by(Notification.cree_le.desc()).limit(30).all()
    return {'notifications': [n.to_dict() for n in notifs],
            'non_lues': sum(1 for n in notifs if not n.lue)}

@app.route('/notifications/lire/<int:id>', methods=['POST'])
@login_required
def lire_notification(id):
    n = Notification.query.filter_by(id=id, utilisateur_id=current_user.id).first_or_404()
    n.lue = True; db.session.commit()
    return {'ok': True}

@app.route('/notifications/lire-tout', methods=['POST'])
@login_required
def lire_toutes_notifications():
    Notification.query.filter_by(utilisateur_id=current_user.id, lue=False).update({'lue': True})
    db.session.commit()
    return {'ok': True}

@app.route('/notifications/supprimer/<int:id>', methods=['POST'])
@login_required
def supprimer_notification(id):
    n = Notification.query.filter_by(id=id, utilisateur_id=current_user.id).first_or_404()
    db.session.delete(n); db.session.commit()
    return {'ok': True}

# ════════════════════════════════════════════════════════════════
# ONBOARDING
# ════════════════════════════════════════════════════════════════

@app.route('/onboarding/terminer', methods=['POST'])
@login_required
def terminer_onboarding():
    current_user.onboarding_complete = True
    db.session.commit()
    return {'ok': True}

@app.route('/onboarding/statut')
@login_required
def statut_onboarding():
    eid = current_user.entreprise_id
    return {
        'produit':     Produit.query.filter_by(entreprise_id=eid).count() > 0,
        'categorie':   Categorie.query.filter_by(entreprise_id=eid).count() > 0,
        'mouvement':   Mouvement.query.filter_by(entreprise_id=eid).count() > 0,
        'fournisseur': Fournisseur.query.filter_by(entreprise_id=eid).count() > 0,
    }

# ════════════════════════════════════════════════════════════════
# LANCEMENT
# ════════════════════════════════════════════════════════════════

# Exécuter init_db au démarrage (fonctionne avec gunicorn ET python app.py)
with app.app_context():
    try:
        init_db()
    except Exception as e:
        print(f"init_db error: {e}")

if __name__ == '__main__':
    app.run(debug=os.environ.get('FLASK_ENV') != 'production')
