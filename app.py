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


class Vente(db.Model):
    __tablename__ = 'ventes'
    id             = db.Column(db.Integer, primary_key=True)
    numero         = db.Column(db.String(20),  nullable=False, unique=True)
    entreprise_id  = db.Column(db.Integer, db.ForeignKey('entreprises.id'), nullable=False)
    cree_par       = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'), nullable=False)
    client_nom     = db.Column(db.String(200), nullable=True)
    client_tel     = db.Column(db.String(30),  nullable=True)
    client_email   = db.Column(db.String(200), nullable=True)
    total          = db.Column(db.Float, nullable=False, default=0.0)
    remise         = db.Column(db.Float, nullable=False, default=0.0)
    total_final    = db.Column(db.Float, nullable=False, default=0.0)
    mode_paiement  = db.Column(db.String(30), default='especes')
    note           = db.Column(db.Text, nullable=True)
    statut         = db.Column(db.String(20), default='validee')
    whatsapp_envoye= db.Column(db.Boolean, default=False)
    email_envoye   = db.Column(db.Boolean, default=False)
    cree_le        = db.Column(db.DateTime, nullable=False, default=datetime.now)
    lignes         = db.relationship('LigneVente', backref='vente',
                                     lazy=True, cascade='all, delete-orphan')

    def generer_message_whatsapp(self, devise='euros'):
        sep = '\n'
        lignes_txt = ''
        for l in self.lignes:
            st = round(l.quantite * l.prix_unitaire, 2)
            lignes_txt += '- ' + l.produit_nom + ' x' + str(l.quantite)
            lignes_txt += ' = ' + str(st) + ' ' + devise + sep
        paiements = {
            'especes': 'Especes', 'carte': 'Carte bancaire',
            'virement': 'Virement', 'cheque': 'Cheque'
        }
        paiement = paiements.get(self.mode_paiement, self.mode_paiement)
        lines = [
            'Recu de vente #' + self.numero,
            'Date : ' + self.cree_le.strftime('%d/%m/%Y %H:%M'),
        ]
        if self.client_nom:
            lines.append('Client : ' + self.client_nom)
        lines.append('')
        lines.append('Detail :')
        lines.append(lignes_txt.rstrip())
        lines.append('')
        lines.append('Sous-total : ' + str(round(self.total, 2)) + ' ' + devise)
        if self.remise > 0:
            lines.append('Remise : -' + str(int(self.remise)) + '%')
        lines.append('TOTAL : ' + str(round(self.total_final, 2)) + ' ' + devise)
        lines.append('Paiement : ' + paiement)
        lines.append('')
        lines.append('Merci pour votre achat !')
        lines.append('StockApp')
        return sep.join(lines)

    def to_dict(self):
        return {
            'id': self.id, 'numero': self.numero,
            'client_nom': self.client_nom, 'client_tel': self.client_tel,
            'total': self.total, 'remise': self.remise,
            'total_final': self.total_final,
            'mode_paiement': self.mode_paiement, 'statut': self.statut,
            'whatsapp_envoye': self.whatsapp_envoye,
            'cree_le': self.cree_le.strftime('%d/%m/%Y %H:%M'),
            'lignes': [l.to_dict() for l in self.lignes],
        }


class LigneVente(db.Model):
    __tablename__ = 'lignes_vente'
    id            = db.Column(db.Integer, primary_key=True)
    vente_id      = db.Column(db.Integer, db.ForeignKey('ventes.id'), nullable=False)
    produit_id    = db.Column(db.Integer, db.ForeignKey('produits.id'), nullable=True)
    produit_nom   = db.Column(db.String(200), nullable=False)
    quantite      = db.Column(db.Integer, nullable=False)
    prix_unitaire = db.Column(db.Float, nullable=False)
    sous_total    = db.Column(db.Float, nullable=False)

    def to_dict(self):
        return {
            'produit_nom': self.produit_nom, 'quantite': self.quantite,
            'prix_unitaire': self.prix_unitaire, 'sous_total': self.sous_total,
        }




class Recu(db.Model):
    __tablename__ = 'recus'
    id             = db.Column(db.Integer, primary_key=True)
    numero         = db.Column(db.String(20),  nullable=False, unique=True)
    entreprise_id  = db.Column(db.Integer, db.ForeignKey('entreprises.id'), nullable=False)
    cree_par       = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'), nullable=False)
    client_nom     = db.Column(db.String(200), nullable=True)
    client_tel     = db.Column(db.String(30),  nullable=True)
    client_email   = db.Column(db.String(200), nullable=True)
    lignes_json    = db.Column(db.Text,        nullable=False)  # JSON liste produits
    total          = db.Column(db.Float,       nullable=False, default=0.0)
    note           = db.Column(db.Text,        nullable=True)
    whatsapp_envoye= db.Column(db.Boolean,     default=False)
    email_envoye   = db.Column(db.Boolean,     default=False)
    cree_le        = db.Column(db.DateTime,    nullable=False, default=datetime.now)

    def get_lignes(self):
        return json.loads(self.lignes_json) if self.lignes_json else []

    def generer_message(self, devise='€'):
        """Génère le message texte du reçu."""
        lignes = self.get_lignes()
        msg  = f"🧾 *Reçu #{self.numero}*\n"
        msg += f"📅 {self.cree_le.strftime('%d/%m/%Y %H:%M')}\n"
        if self.client_nom:
            msg += f"👤 {self.client_nom}\n"
        msg += "\n"
        for l in lignes:
            sous_total = l['quantite'] * l['prix']
            msg += f"• {l['nom']} x{l['quantite']} = {sous_total:.2f}{devise}\n"
        msg += f"\n💰 *Total : {self.total:.2f}{devise}*"
        if self.note:
            msg += f"\n📝 {self.note}"
        msg += "\n\nMerci pour votre achat ! 🙏"
        return msg

    def to_dict(self):
        return {
            'id': self.id, 'numero': self.numero,
            'client_nom': self.client_nom, 'client_tel': self.client_tel,
            'total': self.total, 'lignes': self.get_lignes(),
            'whatsapp_envoye': self.whatsapp_envoye,
            'email_envoye': self.email_envoye,
            'cree_le': self.cree_le.strftime('%d/%m/%Y %H:%M'),
        }


class CodeInvitation(db.Model):
    __tablename__ = 'codes_invitation'
    id         = db.Column(db.Integer, primary_key=True)
    code       = db.Column(db.String(50), nullable=False, unique=True)
    cree_par   = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'), nullable=True)
    utilise    = db.Column(db.Boolean, default=False)
    utilise_par= db.Column(db.Integer, db.ForeignKey('utilisateurs.id'), nullable=True)
    max_usages = db.Column(db.Integer, default=1)
    nb_usages  = db.Column(db.Integer, default=0)
    expire_le  = db.Column(db.DateTime, nullable=True)
    cree_le    = db.Column(db.DateTime, nullable=False, default=datetime.now)
    domaines_autorises = db.Column(db.String(500), nullable=True)  # ex: "gmail.com,entreprise.com"

    def est_valide(self):
        if self.utilise and self.nb_usages >= self.max_usages:
            return False
        if self.expire_le and datetime.now() > self.expire_le:
            return False
        return True

    def utiliser(self, user_id):
        self.nb_usages += 1
        self.utilise_par = user_id
        if self.nb_usages >= self.max_usages:
            self.utilise = True
        db.session.commit()


# Limites par plan
LIMITES_AB = {
    'free':    {'produits': 10,   'utilisateurs': 1,    'export_pdf': False, 'alertes': False},
    'monthly': {'produits': 9999, 'utilisateurs': 9999, 'export_pdf': True,  'alertes': True},
    'yearly':  {'produits': 9999, 'utilisateurs': 9999, 'export_pdf': True,  'alertes': True},
}

# ════════════════════════════════════════════════════════════════
# DEVISES & CONVERSIONS
# ════════════════════════════════════════════════════════════════

DEVISES = {
    '€':   {'nom': 'Euro',           'symbole': '€',   'taux_vers_eur': 1.0},
    '$':   {'nom': 'Dollar US',      'symbole': '$',   'taux_vers_eur': 0.92},
    '£':   {'nom': 'Livre sterling', 'symbole': '£',   'taux_vers_eur': 1.17},
    'CHF': {'nom': 'Franc suisse',   'symbole': 'CHF', 'taux_vers_eur': 1.04},
    'MAD': {'nom': 'Dirham marocain','symbole': 'MAD', 'taux_vers_eur': 0.092},
    'TND': {'nom': 'Dinar tunisien', 'symbole': 'TND', 'taux_vers_eur': 0.29},
    'DZD': {'nom': 'Dinar algérien', 'symbole': 'DZD', 'taux_vers_eur': 0.0068},
    'XOF': {'nom': 'Franc CFA (UEMOA)','symbole':'CFA','taux_vers_eur': 0.00152},
    'XAF': {'nom': 'Franc CFA (CEMAC)','symbole':'CFA','taux_vers_eur': 0.00152},
    'GHS': {'nom': 'Cedi ghanéen',   'symbole': 'GHS', 'taux_vers_eur': 0.063},
    'NGN': {'nom': 'Naira nigérian', 'symbole': '₦',   'taux_vers_eur': 0.00058},
    'EGP': {'nom': 'Livre égyptienne','symbole':'EGP', 'taux_vers_eur': 0.019},
    'CAD': {'nom': 'Dollar canadien','symbole': 'CA$', 'taux_vers_eur': 0.68},
    'AED': {'nom': 'Dirham émirati', 'symbole': 'AED', 'taux_vers_eur': 0.25},
}

# 1 EUR = combien de chaque devise
TAUX_EUR = {k: round(1 / v['taux_vers_eur'], 2) for k, v in DEVISES.items()}
# Ex: 1€ = 655.96 CFA, 1€ = 10.87 MAD


def convertir(montant, devise_source, devise_cible):
    """Convertit un montant d'une devise vers une autre."""
    if devise_source == devise_cible:
        return montant
    # Convertir en EUR d'abord
    taux_src = DEVISES.get(devise_source, {}).get('taux_vers_eur', 1.0)
    taux_dst = DEVISES.get(devise_cible, {}).get('taux_vers_eur', 1.0)
    montant_eur = montant * taux_src
    return round(montant_eur / taux_dst, 2)


def taux_de_change(devise_source, devise_cible):
    """Retourne le taux de change entre deux devises."""
    if devise_source == devise_cible:
        return 1.0
    taux_src = DEVISES.get(devise_source, {}).get('taux_vers_eur', 1.0)
    taux_dst = DEVISES.get(devise_cible, {}).get('taux_vers_eur', 1.0)
    return round(taux_src / taux_dst, 6)


PRIX_AB = {
    'monthly': {'prix': 2,  'label': '2 €/mois', 'duree': 30},
    'yearly':  {'prix': 15, 'label': '15 €/an',  'duree': 365},
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
    is_active            = db.Column(db.Boolean, default=True)   # False = en attente validation admin
    validation_admin     = db.Column(db.Boolean, default=True)   # True = validé par admin
    is_admin             = db.Column(db.Boolean, default=False)  # Super-admin
    token_verification   = db.Column(db.String(100), nullable=True)
    cree_le              = db.Column(db.DateTime, nullable=True)
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

# ════════════════════════════════════════════════════════════════
# CONFIGURATION INSCRIPTION
# ════════════════════════════════════════════════════════════════
INSCRIPTION_CONFIG = {
    'mode': os.environ.get('INSCRIPTION_MODE', 'invitation'),
    # Modes disponibles :
    # 'libre'      — tout le monde peut s'inscrire
    # 'invitation' — code d'invitation requis
    # 'admin'      — validation manuelle par admin
    # 'domaine'    — restriction par domaine email
    'domaines_autorises': os.environ.get('DOMAINES_AUTORISES', '').split(','),
    'limite_par_jour': int(os.environ.get('MAX_INSCRIPTIONS_JOUR', '10')),
}


def compter_inscriptions_jour():
    """Nombre d'inscriptions aujourd'hui (anti-abus)."""
    debut = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return Utilisateur.query.filter(Utilisateur.cree_le >= debut).count()            if hasattr(Utilisateur, 'cree_le') else 0


PLANS = {
    'free': {
        'nom': 'Gratuit', 'prix': 0, 'affichage': '0 €/mois',
        'features': ['10 produits max', '1 utilisateur', 'Export CSV',
                     'Dashboard & graphiques', 'Scanner code-barres'],
        'badge': None, 'price_id': None,
        'limites': {
            'produits': 10, 'utilisateurs': 1, 'export_pdf': False,
            'alertes_email': False, 'categories': 5, 'fournisseurs': 3,
            'historique_jours': 7,
        }
    },
    'monthly': {
        'nom': 'Mensuel', 'prix': 2, 'affichage': '2 €/mois',
        'features': ['Produits illimités', 'Utilisateurs illimités',
                     'Export CSV & PDF', 'Alertes email',
                     'Scanner code-barres', 'Support email'],
        'badge': None, 'price_id': os.environ.get('STRIPE_PRICE_ID_MONTHLY', ''),
        'limites': {
            'produits': 9999, 'utilisateurs': 9999, 'export_pdf': True,
            'alertes_email': True, 'categories': 9999, 'fournisseurs': 9999,
            'historique_jours': 9999,
        }
    },
    'yearly': {
        'nom': 'Annuel', 'prix': 15, 'affichage': '15 €/an',
        'features': ['Produits illimités', 'Utilisateurs illimités',
                     'Export CSV & PDF', 'Alertes email',
                     'Scanner code-barres', 'Support prioritaire',
                     '✨ Économisez 9 € vs mensuel'],
        'badge': 'Meilleur prix', 'price_id': os.environ.get('STRIPE_PRICE_ID_YEARLY', ''),
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
            # Priorité au plan de l'abonnement utilisateur s'il existe
            ab_user = get_abonnement() if current_user.is_authenticated else None
            if ab_user and ab_user.plan in ('monthly', 'yearly'):
                plan_actuel = 'pro'  # monthly/yearly = Pro dans PLANS
            else:
                plan_actuel = entreprise.plan or 'free'

    est_pro = plan_actuel in ('monthly', 'yearly')
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

    en_attente_count = 0
    if current_user.is_authenticated and getattr(current_user, 'role', '') == 'admin':
        en_attente_count = Utilisateur.query.filter_by(is_active=False).count()

    # Infos devise
    devise_info   = DEVISES.get(devise, DEVISES.get('€'))
    taux_cfa      = taux_de_change(devise, 'XOF') if devise != 'XOF' else 1.0
    # Prix stockés directement dans la devise de l'utilisateur
    # Pas de conversion — l'utilisateur saisit et voit dans SA devise
    taux_affichage = 1.0
    devise_symbole = devise_info.get('symbole', devise) if devise_info else devise

    return {
        'devise': devise, 'entreprise': entreprise, 'role': role,
        'devise_info': devise_info,
        'devise_symbole': devise_symbole,
        'taux_affichage': taux_affichage,
        'DEVISES': DEVISES,
        'TAUX_EUR': TAUX_EUR,
        'taux_cfa': taux_cfa,
        'en_attente_count': en_attente_count,
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

    # ── Toutes les migrations AVANT toute requête ORM ──
    # SQLite : exécutées une par une, erreurs ignorées silencieusement
    migrations_sql = [
        "ALTER TABLE utilisateurs  ADD COLUMN devise             VARCHAR(10)  DEFAULT '€'",
        "ALTER TABLE utilisateurs  ADD COLUMN role               VARCHAR(20)  DEFAULT 'admin'",
        "ALTER TABLE utilisateurs  ADD COLUMN entreprise_id      INTEGER      DEFAULT NULL",
        "ALTER TABLE utilisateurs  ADD COLUMN email_verifie      BOOLEAN      DEFAULT 0",
        "ALTER TABLE utilisateurs  ADD COLUMN is_active          BOOLEAN      DEFAULT 1",
        "ALTER TABLE utilisateurs  ADD COLUMN validation_admin   BOOLEAN      DEFAULT 1",
        "ALTER TABLE utilisateurs  ADD COLUMN cree_le            DATETIME     DEFAULT NULL",
        "ALTER TABLE utilisateurs  ADD COLUMN token_verification VARCHAR(100) DEFAULT NULL",
        "ALTER TABLE utilisateurs  ADD COLUMN token_reset        VARCHAR(100) DEFAULT NULL",
        "ALTER TABLE utilisateurs  ADD COLUMN token_reset_exp    DATETIME     DEFAULT NULL",
        "ALTER TABLE utilisateurs  ADD COLUMN onboarding_complete BOOLEAN     DEFAULT 0",
        "ALTER TABLE utilisateurs  ADD COLUMN is_admin          BOOLEAN      DEFAULT 0",
        "ALTER TABLE produits      ADD COLUMN entreprise_id      INTEGER      DEFAULT NULL",
        "ALTER TABLE produits      ADD COLUMN code_barres        VARCHAR(100) DEFAULT NULL",
        "ALTER TABLE categories    ADD COLUMN entreprise_id      INTEGER      DEFAULT NULL",
        "ALTER TABLE fournisseurs  ADD COLUMN entreprise_id      INTEGER      DEFAULT NULL",
        "ALTER TABLE mouvements    ADD COLUMN entreprise_id      INTEGER      DEFAULT NULL",
        "ALTER TABLE entreprises   ADD COLUMN stripe_customer_id VARCHAR(100) DEFAULT NULL",
        "ALTER TABLE entreprises   ADD COLUMN stripe_sub_id      VARCHAR(100) DEFAULT NULL",
        "ALTER TABLE entreprises   ADD COLUMN stripe_status      VARCHAR(30)  DEFAULT NULL",
        "ALTER TABLE utilisateurs  ADD COLUMN is_admin           BOOLEAN      DEFAULT 0",
    ]
    for sql in migrations_sql:
        try:
            db.session.execute(db.text(sql))
            db.session.commit()
        except Exception:
            db.session.rollback()

    # Tables créées si elles n'existent pas
    for create_sql in [
        """CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            utilisateur_id INTEGER NOT NULL, entreprise_id INTEGER NOT NULL,
            type VARCHAR(30) NOT NULL, titre VARCHAR(200) NOT NULL,
            message TEXT NOT NULL, lien VARCHAR(200),
            lue BOOLEAN DEFAULT 0, cree_le DATETIME DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS abonnements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE, plan VARCHAR(20) NOT NULL DEFAULT 'free',
            statut VARCHAR(20) NOT NULL DEFAULT 'actif',
            date_debut DATETIME, date_fin DATETIME,
            cree_le DATETIME DEFAULT CURRENT_TIMESTAMP, renouvele_le DATETIME)""",
        """CREATE TABLE IF NOT EXISTS codes_invitation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code VARCHAR(50) NOT NULL UNIQUE, cree_par INTEGER,
            utilise BOOLEAN DEFAULT 0, utilise_par INTEGER,
            max_usages INTEGER DEFAULT 1, nb_usages INTEGER DEFAULT 0,
            expire_le DATETIME, cree_le DATETIME DEFAULT CURRENT_TIMESTAMP,
            domaines_autorises VARCHAR(500))""",
        """CREATE TABLE IF NOT EXISTS recus (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            numero VARCHAR(20) NOT NULL UNIQUE,
            entreprise_id INTEGER NOT NULL, cree_par INTEGER NOT NULL,
            client_nom VARCHAR(200), client_tel VARCHAR(30),
            client_email VARCHAR(200), lignes_json TEXT NOT NULL,
            total REAL NOT NULL DEFAULT 0, note TEXT,
            whatsapp_envoye BOOLEAN DEFAULT 0, email_envoye BOOLEAN DEFAULT 0,
            cree_le DATETIME DEFAULT CURRENT_TIMESTAMP)""",
    ]:
        try:
            db.session.execute(db.text(create_sql))
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

    # Compte admin
    admin = Utilisateur.query.filter_by(username='admin').first()
    if not admin:
        admin = Utilisateur(username='admin', role='admin',
                            entreprise_id=entreprise.id,
                            email_verifie=True, onboarding_complete=True,
                            is_active=True, validation_admin=True,
                            is_admin=True)
        db.session.add(admin)
    admin.set_password('l@wson00196')
    admin.role = 'admin'; admin.is_admin = True
    admin.is_active = True; admin.email_verifie = True

    # Compte LAWSON — même droits qu'admin
    lawson = Utilisateur.query.filter_by(username='LAWSON').first()
    if not lawson:
        lawson = Utilisateur(username='LAWSON', role='admin',
                             entreprise_id=entreprise.id,
                             email_verifie=True, onboarding_complete=True,
                             is_active=True, validation_admin=True,
                             is_admin=True)
        db.session.add(lawson)
    else:
        lawson.role = 'admin'; lawson.is_admin = True
        lawson.is_active = True; lawson.email_verifie = True
    lawson.set_password('0012345678!')

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
            # Bloquer si compte désactivé ou en attente validation
            if not getattr(user, 'is_active', True):
                if not getattr(user, 'validation_admin', True):
                    flash("Votre compte est en attente de validation par un administrateur.", "error")
                else:
                    flash("Votre compte a été désactivé. Contactez l'administrateur.", "error")
                return redirect(url_for('login'))
            # Bloquer inscription autonome non vérifiée
            if not user.email_verifie and user.email and INSCRIPTION_CONFIG['mode'] == 'libre':
                flash("Vérifiez votre email avant de vous connecter.", "error")
                return redirect(url_for('login'))
            login_user(user, remember=request.form.get('remember') == 'on')
            app.logger.info(f"Connexion : {user.username} [{request.remote_addr}]")
            return redirect(request.args.get('next') or url_for('index'))
        flash("Identifiants incorrects.", "error")
        app.logger.warning(f"Tentative connexion échouée : {request.form.get('username','')} [{request.remote_addr}]")
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
    # Admin et rôle 'admin' : produits illimités
    if current_user.role != 'admin' and not getattr(current_user, 'is_admin', False):
        lim_ab = limite_produits_ab()
        if nb >= lim_ab:
            ab = get_abonnement()
            plan = ab.plan if ab else 'free'
            if plan == 'free':
                flash(f"Limite atteinte ({nb}/{lim_ab} produits). Passez au plan Monthly ou Yearly pour continuer.", "error")
            else:
                flash(f"Limite atteinte ({nb}/{lim_ab} produits).", "error")
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
@limiter.limit('5 per hour')  # Anti-abus : max 5 inscriptions/heure par IP
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    mode = INSCRIPTION_CONFIG['mode']

    if request.method == 'POST':
        import re, secrets as sec

        nom_entreprise = request.form.get('nom_entreprise','').strip()
        username       = request.form.get('username','').strip()
        email          = request.form.get('email','').strip().lower()
        password       = request.form.get('password','')
        confirm        = request.form.get('confirm','')
        code_invite    = request.form.get('code_invitation','').strip().upper()

        # ── Validations de base ──
        erreurs = []
        if not nom_entreprise: erreurs.append("Le nom de l'entreprise est obligatoire.")
        if not username or len(username) < 3:
            erreurs.append("Nom d'utilisateur trop court (3 caractères min.).")
        if not re.match(r'^[a-zA-Z0-9_.-]+$', username):
            erreurs.append("Nom d'utilisateur : lettres, chiffres, _ . - uniquement.")
        if not email or '@' not in email:
            erreurs.append("Email invalide.")
        if len(password) < 6:
            erreurs.append("Mot de passe trop court (6 caractères min.).")
        if password != confirm:
            erreurs.append("Les mots de passe ne correspondent pas.")
        if Utilisateur.query.filter_by(username=username).first():
            erreurs.append("Ce nom d'utilisateur est déjà pris.")
        if Utilisateur.query.filter_by(email=email).first():
            erreurs.append("Cet email est déjà utilisé.")

        # ── Limite journalière anti-abus ──
        if compter_inscriptions_jour() >= INSCRIPTION_CONFIG['limite_par_jour']:
            erreurs.append("Limite d'inscriptions journalière atteinte. Réessayez demain.")

        # ── Contrôle selon le MODE ──
        compte_actif = True  # Par défaut actif sauf mode admin
        code_obj     = None

        if mode == 'invitation':
            if not code_invite:
                erreurs.append("Un code d'invitation est requis pour s'inscrire.")
            else:
                code_obj = CodeInvitation.query.filter_by(code=code_invite).first()
                if not code_obj or not code_obj.est_valide():
                    erreurs.append("Code d'invitation invalide ou expiré.")
                elif code_obj.domaines_autorises:
                    domaines = [d.strip() for d in code_obj.domaines_autorises.split(',')]
                    domaine_email = email.split('@')[-1]
                    if domaine_email not in domaines:
                        erreurs.append(f"Email non autorisé pour ce code (domaine: {domaine_email}).")

        elif mode == 'domaine':
            domaines = [d.strip() for d in INSCRIPTION_CONFIG['domaines_autorises'] if d.strip()]
            if domaines:
                domaine_email = email.split('@')[-1]
                if domaine_email not in domaines:
                    erreurs.append(f"Inscription réservée aux emails : {', '.join(domaines)}.")

        elif mode == 'admin':
            compte_actif = False  # Attente validation admin

        # Afficher erreurs
        if erreurs:
            for e in erreurs: flash(e, "error")
            return render_template('register.html', mode=mode)

        # ── Création du compte ──
        slug = re.sub(r'[^a-z0-9]+','-',nom_entreprise.lower()).strip('-') or 'entreprise'
        if Entreprise.query.filter_by(slug=slug).first():
            slug = f"{slug}-{Entreprise.query.count()+1}"

        token      = sec.token_urlsafe(32)
        entreprise = Entreprise(nom=nom_entreprise, slug=slug, plan='free')
        db.session.add(entreprise)
        db.session.flush()

        admin = Utilisateur(
            username=username, email=email, role='admin',
            entreprise_id=entreprise.id,
            email_verifie=(mode != 'libre'),  # vérifié si pas mode libre
            is_active=compte_actif,
            validation_admin=compte_actif,
            token_verification=token if mode == 'libre' else None,
            cree_le=datetime.now()
        )
        admin.set_password(password)
        db.session.add(admin)
        db.session.flush()

        # Marquer le code d'invitation comme utilisé
        if code_obj:
            code_obj.utiliser(admin.id)

        db.session.commit()

        # ── Log création ──
        app.logger.info(f"Nouveau compte : {username} ({email}) mode={mode} actif={compte_actif} ip={request.remote_addr}")

        # ── Message selon le mode ──
        if mode == 'admin' and not compte_actif:
            flash("Compte créé ! Un administrateur doit valider votre inscription. Vous recevrez une notification.", "success")
            # Notifier les admins
            _notifier_admins_inscription(admin)
        elif mode == 'libre':
            _envoyer_email_bienvenue(admin, entreprise, token)
            flash("Compte créé ! Vérifiez votre email pour activer votre espace.", "success")
        else:
            flash(f"Compte créé avec succès ! Bienvenue, {username} 🎉", "success")

        return redirect(url_for('login'))

    return render_template('register.html', mode=mode)


def _notifier_admins_inscription(user):
    """Notifie tous les super-admins qu'un compte attend validation."""
    # Notifier l'admin de l'entreprise par défaut (entreprise 1)
    admins = Utilisateur.query.filter_by(role='admin').limit(5).all()
    for admin in admins:
        if admin.entreprise_id:
            creer_notification(
                entreprise_id=admin.entreprise_id,
                type='info',
                titre='Nouveau compte en attente',
                message=f'L\'utilisateur {user.username} attend la validation de son compte.',
                lien='/admin/utilisateurs',
                user_id=admin.id
            )


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
    if plan_id not in PLANS or not PLANS[plan_id]['price_id']:
        flash("Plan invalide ou non configuré.", "error")
        return redirect(url_for('abonnement'))
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
# VENTES
# ════════════════════════════════════════════════════════════════

def generer_numero_vente(entreprise_id):
    nb = Vente.query.filter_by(entreprise_id=entreprise_id).count() + 1
    prefix = datetime.now().strftime('%Y%m%d')
    return 'VTE-' + prefix + '-' + str(nb).zfill(4)


@app.route('/ventes')
@login_required
def liste_ventes():
    eid    = current_user.entreprise_id
    ventes = Vente.query.filter_by(entreprise_id=eid)                        .order_by(Vente.cree_le.desc()).limit(100).all()
    ventes_valides = [v for v in ventes if v.statut == 'validee']
    nb_ventes  = len(ventes_valides)
    total_ca   = sum(v.total_final for v in ventes_valides)
    total_jour = sum(v.total_final for v in ventes_valides
                     if v.cree_le.date() == datetime.now().date())
    total_mois = sum(v.total_final for v in ventes_valides
                     if v.cree_le.month == datetime.now().month)
    return render_template('ventes.html', ventes=ventes,
                           nb_ventes=nb_ventes, total_ca=total_ca,
                           total_jour=total_jour, total_mois=total_mois)


@app.route('/ventes/creer', methods=['GET', 'POST'])
@login_required
@manager_ou_admin
def creer_vente():
    eid      = current_user.entreprise_id
    produits = Produit.query.filter_by(entreprise_id=eid).order_by(Produit.nom).all()
    devise   = getattr(current_user, 'devise', '') or 'euros'

    if request.method == 'POST':
        client_nom    = request.form.get('client_nom',   '').strip()
        client_tel    = request.form.get('client_tel',   '').strip()
        client_email  = request.form.get('client_email', '').strip()
        mode_paiement = request.form.get('mode_paiement', 'especes')
        remise_pct    = float(request.form.get('remise', 0) or 0)
        note          = request.form.get('note', '').strip()
        envoyer_wa    = request.form.get('envoyer_whatsapp') == 'on'

        produit_ids = request.form.getlist('produit_id[]')
        quantites   = request.form.getlist('quantite[]')
        prix_list   = request.form.getlist('prix[]')

        lignes_data = []
        total       = 0.0

        for pid, qte_str, prix_str in zip(produit_ids, quantites, prix_list):
            if not pid:
                continue
            try:
                qte  = int(qte_str)
                prix = float(prix_str)
                if qte <= 0:
                    continue
            except (ValueError, TypeError):
                continue
            p = Produit.query.filter_by(id=pid, entreprise_id=eid).first()
            if not p:
                continue
            if p.quantite < qte:
                flash('Stock insuffisant pour ' + p.nom + ' (stock: ' + str(p.quantite) + ')', 'error')
                return render_template('creer_vente.html', produits=produits)
            st = round(qte * prix, 2)
            total += st
            lignes_data.append({'produit': p, 'nom': p.nom, 'qte': qte, 'prix': prix, 'st': st})

        if not lignes_data:
            flash('Ajoutez au moins un produit.', 'error')
            produits_json = json.dumps([{'id':p.id,'nom':p.nom,'prix':p.prix,'quantite':p.quantite} for p in produits], ensure_ascii=False)
            return render_template('creer_vente.html', produits=produits, produits_json=produits_json)

        remise_pct  = max(0, min(100, remise_pct))
        total_final = round(total * (1 - remise_pct / 100), 2)

        vente = Vente(
            numero        = generer_numero_vente(eid),
            entreprise_id = eid,
            cree_par      = current_user.id,
            client_nom    = client_nom or None,
            client_tel    = client_tel or None,
            client_email  = client_email or None,
            total         = round(total, 2),
            remise        = remise_pct,
            total_final   = total_final,
            mode_paiement = mode_paiement,
            note          = note or None,
            statut        = 'validee'
        )
        db.session.add(vente)
        db.session.flush()

        for d in lignes_data:
            ligne = LigneVente(
                vente_id      = vente.id,
                produit_id    = d['produit'].id,
                produit_nom   = d['nom'],
                quantite      = d['qte'],
                prix_unitaire = d['prix'],
                sous_total    = d['st']
            )
            db.session.add(ligne)
            # Décrémenter le stock
            d['produit'].quantite -= d['qte']
            db.session.add(Mouvement(
                produit_id    = d['produit'].id,
                produit_nom   = d['nom'],
                type          = 'sortie',
                quantite      = d['qte'],
                date          = date.today(),
                note          = 'Vente #' + vente.numero,
                entreprise_id = eid
            ))

        db.session.commit()

        messages_retour = ['Vente #' + vente.numero + ' enregistree (' + str(total_final) + ' ' + devise + ')']

        # Envoi WhatsApp
        if envoyer_wa and client_tel:
            tel_formate, err = formater_numero_tel(client_tel)
            if err:
                messages_retour.append('WhatsApp : numero invalide (' + err + ')')
            else:
                msg_wa = vente.generer_message_whatsapp(devise)
                ok, err = envoyer_whatsapp(tel_formate, msg_wa)
                if ok:
                    vente.whatsapp_envoye = True
                    db.session.commit()
                    messages_retour.append('WhatsApp envoye !')
                else:
                    messages_retour.append('WhatsApp echoue : ' + str(err))

        flash(' | '.join(messages_retour), 'success')
        return redirect(url_for('voir_vente', id=vente.id))

    produits_json = json.dumps([
        {'id': p.id, 'nom': p.nom, 'prix': p.prix, 'quantite': p.quantite}
        for p in produits
    ], ensure_ascii=False)
    return render_template('creer_vente.html', produits=produits, produits_json=produits_json)


@app.route('/ventes/<int:id>')
@login_required
def voir_vente(id):
    vente  = Vente.query.filter_by(id=id, entreprise_id=current_user.entreprise_id).first_or_404()
    devise = getattr(current_user, 'devise', '') or 'euros'
    return render_template('voir_vente.html', vente=vente, devise=devise)


@app.route('/ventes/<int:id>/whatsapp', methods=['POST'])
@login_required
@manager_ou_admin
def renvoyer_whatsapp_vente(id):
    vente  = Vente.query.filter_by(id=id, entreprise_id=current_user.entreprise_id).first_or_404()
    devise = getattr(current_user, 'devise', '') or 'euros'
    if not vente.client_tel:
        flash('Aucun numero de telephone pour cette vente.', 'error')
        return redirect(url_for('voir_vente', id=id))
    tel_formate, err = formater_numero_tel(vente.client_tel)
    if err:
        flash('Numero invalide : ' + err, 'error')
        return redirect(url_for('voir_vente', id=id))
    msg = vente.generer_message_whatsapp(devise)
    ok, err = envoyer_whatsapp(tel_formate, msg)
    if ok:
        vente.whatsapp_envoye = True
        db.session.commit()
        flash('WhatsApp renvoye avec succes.', 'success')
    else:
        flash('Echec WhatsApp : ' + str(err), 'error')
    return redirect(url_for('voir_vente', id=id))


@app.route('/ventes/<int:id>/annuler', methods=['POST'])
@login_required
@admin_requis
def annuler_vente(id):
    vente = Vente.query.filter_by(id=id, entreprise_id=current_user.entreprise_id).first_or_404()
    if vente.statut == 'annulee':
        flash('Cette vente est deja annulee.', 'error')
        return redirect(url_for('voir_vente', id=id))
    # Remettre le stock
    for l in vente.lignes:
        if l.produit_id:
            p = Produit.query.get(l.produit_id)
            if p:
                p.quantite += l.quantite
                db.session.add(Mouvement(
                    produit_id    = p.id,
                    produit_nom   = p.nom,
                    type          = 'entree',
                    quantite      = l.quantite,
                    date          = date.today(),
                    note          = 'Annulation vente #' + vente.numero,
                    entreprise_id = current_user.entreprise_id
                ))
    vente.statut = 'annulee'
    db.session.commit()
    flash('Vente #' + vente.numero + ' annulee. Stock restaure.', 'success')
    return redirect(url_for('liste_ventes'))

# ════════════════════════════════════════════════════════════════
# REÇUS & WHATSAPP
# ════════════════════════════════════════════════════════════════

def generer_numero_recu(entreprise_id):
    prefix = datetime.now().strftime('%Y%m%d')
    nb = Recu.query.filter_by(entreprise_id=entreprise_id).count() + 1
    return 'REC-' + prefix + '-' + str(nb).zfill(4)


def formater_numero_tel(numero):
    """
    Formate un numéro de téléphone au format international E.164.
    Exemples : 0612345678 → +33612345678 | +212661234567 → +212661234567
    """
    import re
    numero = re.sub(r'[\s\-\.\(\)]', '', str(numero).strip())
    if numero.startswith('00'):
        numero = '+' + numero[2:]
    elif numero.startswith('0') and not numero.startswith('+'):
        numero = '+33' + numero[1:]  # France par défaut
    if not numero.startswith('+'):
        numero = '+' + numero
    # Validation : doit contenir 10-15 chiffres après le +
    if not re.match(r'^\+\d{9,15}$', numero):
        return None, "Numéro invalide (format attendu : +33612345678)"
    return numero, None


def envoyer_whatsapp(numero, message):
    """
    Envoie un message WhatsApp via Twilio.
    Nécessite : TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM
    Retourne (True, None) ou (False, erreur)
    """
    account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
    auth_token  = os.environ.get('TWILIO_AUTH_TOKEN')
    from_number = os.environ.get('TWILIO_WHATSAPP_FROM', 'whatsapp:+14155238886')

    if not account_sid or not auth_token:
        app.logger.warning("Twilio non configuré (TWILIO_ACCOUNT_SID manquant)")
        return False, "WhatsApp non configuré. Ajoutez TWILIO_ACCOUNT_SID et TWILIO_AUTH_TOKEN."

    try:
        from twilio.rest import Client
        client  = Client(account_sid, auth_token)
        msg = client.messages.create(
            from_=from_number,
            to=f'whatsapp:{numero}',
            body=message
        )
        app.logger.info(f"WhatsApp envoyé à {numero} — SID: {msg.sid}")
        return True, None
    except ImportError:
        return False, "Twilio non installé. Lancez : pip install twilio"
    except Exception as e:
        app.logger.error(f"WhatsApp erreur : {e}")
        return False, str(e)


def envoyer_recu_email(recu, devise='€'):
    """Envoie le reçu par email au client."""
    if not recu.client_email:
        return False, "Pas d'email client"
    if not app.config.get('MAIL_USERNAME'):
        return False, "Email non configuré"

    lignes = recu.get_lignes()
    lignes_html = "".join([
        f'''<tr>
          <td style="padding:8px 12px;border-bottom:1px solid #eee">{l["nom"]}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:center">{l["quantite"]}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:right">{l["prix"]:.2f}{devise}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:right;font-weight:600">
            {l["quantite"]*l["prix"]:.2f}{devise}
          </td>
        </tr>'''
        for l in lignes
    ])

    html = f"""
    <html><body style="font-family:Arial;background:#f5f5f5;margin:0;padding:0">
    <div style="max-width:600px;margin:32px auto;background:#fff;border-radius:12px;overflow:hidden">
      <div style="background:#1a1a18;padding:20px 28px;color:#fff;font-family:monospace;font-size:15px">
        📦 stockapp &nbsp;·&nbsp; <span style="opacity:.6">Reçu #{recu.numero}</span>
      </div>
      <div style="padding:28px">
        <h2 style="margin:0 0 4px;color:#1a1a18">Reçu d'achat</h2>
        <p style="color:#7a7870;margin:0 0 20px;font-size:14px">
          {recu.cree_le.strftime("%d/%m/%Y à %H:%M")}
          {"· Client : " + recu.client_nom if recu.client_nom else ""}
        </p>
        <table style="width:100%;border-collapse:collapse;font-size:14px">
          <thead>
            <tr style="background:#f5f5f5">
              <th style="padding:10px 12px;text-align:left;font-size:11px;color:#777;text-transform:uppercase">Produit</th>
              <th style="padding:10px 12px;text-align:center;font-size:11px;color:#777;text-transform:uppercase">Qté</th>
              <th style="padding:10px 12px;text-align:right;font-size:11px;color:#777;text-transform:uppercase">Prix unit.</th>
              <th style="padding:10px 12px;text-align:right;font-size:11px;color:#777;text-transform:uppercase">Sous-total</th>
            </tr>
          </thead>
          <tbody>{lignes_html}</tbody>
          <tfoot>
            <tr>
              <td colspan="3" style="padding:12px;text-align:right;font-weight:600;font-size:16px">Total :</td>
              <td style="padding:12px;text-align:right;font-weight:700;font-size:18px;color:#1a1a18">
                {recu.total:.2f}{devise}
              </td>
            </tr>
          </tfoot>
        </table>
        {"<p style=\"color:#7a7870;font-size:13px;margin-top:16px\">Note : " + recu.note + "</p>" if recu.note else ""}
      </div>
      <div style="padding:16px 28px;background:#f5f5f5;font-size:12px;color:#777;text-align:center">
        Merci pour votre achat 🙏
      </div>
    </div>
    </body></html>"""

    try:
        mail.send(Message(
            subject=f"Votre reçu #{recu.numero}",
            recipients=[recu.client_email],
            html=html
        ))
        return True, None
    except Exception as e:
        return False, str(e)


def generer_pdf_recu(recu, devise='€'):
    """Génère un PDF du reçu avec ReportLab. Retourne un BytesIO."""
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT

    buffer = io.BytesIO()
    doc    = SimpleDocTemplate(buffer, pagesize=A4,
                               rightMargin=20*mm, leftMargin=20*mm,
                               topMargin=20*mm, bottomMargin=20*mm)
    styles = getSampleStyleSheet()
    story  = []

    # En-tête
    story.append(Paragraph("REÇU D'ACHAT",
        ParagraphStyle('H', parent=styles['Title'], fontSize=22, spaceAfter=2,
                       textColor=colors.HexColor('#1A1A18'), alignment=TA_LEFT)))
    story.append(Paragraph(
        f"N° {recu.numero} &nbsp;·&nbsp; {recu.cree_le.strftime('%d/%m/%Y %H:%M')}",
        ParagraphStyle('Sub', parent=styles['Normal'], fontSize=11,
                       textColor=colors.HexColor('#7A7870'), spaceAfter=4)))
    if recu.client_nom:
        story.append(Paragraph(f"Client : {recu.client_nom}",
            ParagraphStyle('C', parent=styles['Normal'], fontSize=11,
                           textColor=colors.HexColor('#1A1A18'), spaceAfter=2)))
    if recu.client_tel:
        story.append(Paragraph(f"Tél : {recu.client_tel}",
            ParagraphStyle('T', parent=styles['Normal'], fontSize=10,
                           textColor=colors.HexColor('#7A7870'), spaceAfter=8)))

    story.append(HRFlowable(width="100%", thickness=0.5,
                             color=colors.HexColor('#DDDBD4'), spaceAfter=10))

    # Tableau produits
    rows = [['Produit', 'Qté', 'Prix unit.', 'Sous-total']]
    lignes = recu.get_lignes()
    for l in lignes:
        rows.append([
            l['nom'], str(l['quantite']),
            f"{l['prix']:.2f} {devise}",
            f"{l['quantite']*l['prix']:.2f} {devise}"
        ])
    rows.append(['', '', 'TOTAL', f"{recu.total:.2f} {devise}"])

    t = Table(rows, colWidths=[90*mm, 20*mm, 35*mm, 35*mm])
    t.setStyle(TableStyle([
        ('BACKGROUND',  (0,0), (-1,0), colors.HexColor('#1A1A18')),
        ('TEXTCOLOR',   (0,0), (-1,0), colors.white),
        ('FONTNAME',    (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE',    (0,0), (-1,-1), 10),
        ('ALIGN',       (1,0), (-1,-1), 'CENTER'),
        ('ALIGN',       (2,0), (-1,-1), 'RIGHT'),
        ('ROWBACKGROUNDS', (0,1), (-1,-2), [colors.white, colors.HexColor('#FAFAF8')]),
        ('FONTNAME',    (0,-1), (-1,-1), 'Helvetica-Bold'),
        ('FONTSIZE',    (-1,-1), (-1,-1), 12),
        ('BACKGROUND',  (0,-1), (-1,-1), colors.HexColor('#F5F4F0')),
        ('BOX',         (0,0), (-1,-1), 0.5, colors.HexColor('#DDDBD4')),
        ('INNERGRID',   (0,0), (-1,-1), 0.5, colors.HexColor('#DDDBD4')),
        ('TOPPADDING',  (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(t)

    if recu.note:
        story.append(Spacer(1, 8*mm))
        story.append(Paragraph(f"Note : {recu.note}",
            ParagraphStyle('N', parent=styles['Normal'], fontSize=10,
                           textColor=colors.HexColor('#7A7870'))))

    story.append(Spacer(1, 12*mm))
    story.append(Paragraph("Merci pour votre achat !",
        ParagraphStyle('F', parent=styles['Normal'], fontSize=11,
                       textColor=colors.HexColor('#7A7870'), alignment=TA_CENTER)))

    doc.build(story)
    buffer.seek(0)
    return buffer




# ════════════════════════════════════════════════════════════════
# REÇUS — routes
# ════════════════════════════════════════════════════════════════

@app.route('/recus')
@login_required
def liste_recus():
    eid   = current_user.entreprise_id
    recus = Recu.query.filter_by(entreprise_id=eid).order_by(Recu.cree_le.desc()).limit(100).all()
    return render_template('recus.html', recus=recus)


@app.route('/recus/creer', methods=['GET', 'POST'])
@login_required
@manager_ou_admin
def creer_recu():
    eid      = current_user.entreprise_id
    produits = Produit.query.filter_by(entreprise_id=eid).order_by(Produit.nom).all()
    devise   = getattr(current_user, 'devise', '') or 'euros'
    if request.method == 'POST':
        client_nom   = request.form.get('client_nom',   '').strip()
        client_tel   = request.form.get('client_tel',   '').strip()
        client_email = request.form.get('client_email', '').strip()
        note         = request.form.get('note', '').strip()
        envoyer_wa   = request.form.get('envoyer_whatsapp') == 'on'
        envoyer_mail = request.form.get('envoyer_email') == 'on'
        lignes, total = [], 0.0
        for pid, qte_str, prix_str in zip(
            request.form.getlist('produit_id[]'),
            request.form.getlist('quantite[]'),
            request.form.getlist('prix[]')
        ):
            if not pid: continue
            try:
                qte = int(qte_str); prix = float(prix_str)
                if qte <= 0: continue
            except (ValueError, TypeError): continue
            p = Produit.query.filter_by(id=pid, entreprise_id=eid).first()
            if not p: continue
            st = round(qte * prix, 2); total += st
            lignes.append({'produit_id': p.id, 'nom': p.nom, 'quantite': qte, 'prix': prix, 'sous_total': st})
        if not lignes:
            flash('Ajoutez au moins un produit.', 'error')
            return render_template('creer_recu.html', produits=produits)
        tel_formate = None
        if client_tel:
            tel_formate, err = formater_numero_tel(client_tel)
            if err:
                flash('Numéro invalide : ' + err, 'error')
                return render_template('creer_recu.html', produits=produits)
        recu = Recu(
            numero=generer_numero_recu(eid), entreprise_id=eid,
            cree_par=current_user.id, client_nom=client_nom or None,
            client_tel=tel_formate or client_tel or None,
            client_email=client_email or None,
            lignes_json=json.dumps(lignes, ensure_ascii=False),
            total=round(total, 2), note=note or None
        )
        db.session.add(recu); db.session.commit()
        msgs = ['Reçu #' + recu.numero + ' créé.']
        if envoyer_wa and tel_formate:
            ok, err = envoyer_whatsapp(tel_formate, recu.generer_message(devise))
            if ok: recu.whatsapp_envoye = True; db.session.commit(); msgs.append('WhatsApp envoyé.')
            else: msgs.append('WhatsApp échoué : ' + str(err))
        if envoyer_mail and client_email:
            ok, err = envoyer_recu_email(recu, devise)
            if ok: recu.email_envoye = True; db.session.commit(); msgs.append('Email envoyé.')
            else: msgs.append('Email échoué.')
        flash(' | '.join(msgs), 'success')
        return redirect(url_for('voir_recu', id=recu.id))
    produits_json = json.dumps([
        {'id': p.id, 'nom': p.nom, 'prix': p.prix, 'quantite': p.quantite}
        for p in produits
    ], ensure_ascii=False)
    return render_template('creer_recu.html', produits=produits, produits_json=produits_json)


@app.route('/recus/<int:id>')
@login_required
def voir_recu(id):
    recu = Recu.query.filter_by(id=id, entreprise_id=current_user.entreprise_id).first_or_404()
    return render_template('voir_recu.html', recu=recu, devise=getattr(current_user,'devise','')+'' or 'euros')


@app.route('/recus/<int:id>/pdf')
@login_required
def telecharger_recu_pdf(id):
    recu   = Recu.query.filter_by(id=id, entreprise_id=current_user.entreprise_id).first_or_404()
    devise = getattr(current_user, 'devise', '') or 'euros'
    buf    = generer_pdf_recu(recu, devise)
    response = make_response(buf.read())
    response.headers['Content-Type']        = 'application/pdf'
    response.headers['Content-Disposition'] = 'attachment; filename="recu-' + recu.numero + '.pdf"'
    return response


@app.route('/recus/<int:id>/renvoyer', methods=['POST'])
@login_required
@manager_ou_admin
def renvoyer_recu(id):
    recu   = Recu.query.filter_by(id=id, entreprise_id=current_user.entreprise_id).first_or_404()
    devise = getattr(current_user, 'devise', '') or 'euros'
    canal  = request.form.get('canal', 'whatsapp')
    if canal == 'whatsapp':
        if not recu.client_tel: flash('Aucun numéro.', 'error')
        else:
            ok, err = envoyer_whatsapp(recu.client_tel, recu.generer_message(devise))
            if ok: recu.whatsapp_envoye = True; db.session.commit(); flash('WhatsApp renvoyé.', 'success')
            else: flash('Échec : ' + str(err), 'error')
    elif canal == 'email':
        if not recu.client_email: flash('Aucun email.', 'error')
        else:
            ok, err = envoyer_recu_email(recu, devise)
            if ok: recu.email_envoye = True; db.session.commit(); flash('Email renvoyé.', 'success')
            else: flash('Échec email.', 'error')
    return redirect(url_for('voir_recu', id=id))


@app.route('/recus/<int:id>/supprimer', methods=['POST'])
@login_required
@admin_requis
def supprimer_recu(id):
    recu = Recu.query.filter_by(id=id, entreprise_id=current_user.entreprise_id).first_or_404()
    db.session.delete(recu); db.session.commit()
    flash('Reçu #' + recu.numero + ' supprimé.', 'success')
    return redirect(url_for('liste_recus'))


# ════════════════════════════════════════════════════════════════
# ADMIN — gestion des comptes utilisateurs
# ════════════════════════════════════════════════════════════════

@app.route('/admin/utilisateurs')
@login_required
@admin_requis
def admin_utilisateurs():
    en_attente = Utilisateur.query.filter_by(is_active=False).all()
    tous       = Utilisateur.query.order_by(Utilisateur.id.desc()).all()
    codes      = CodeInvitation.query.order_by(CodeInvitation.cree_le.desc()).limit(20).all()
    return render_template('admin_utilisateurs.html', en_attente=en_attente, tous=tous, codes=codes)


@app.route('/admin/utilisateurs/activer/<int:id>', methods=['POST'])
@login_required
@admin_requis
def activer_compte(id):
    u = Utilisateur.query.get_or_404(id)
    u.is_active = True; u.validation_admin = True; u.email_verifie = True
    db.session.commit()
    flash('Compte « ' + u.username + ' » activé.', 'success')
    return redirect(url_for('admin_utilisateurs'))


@app.route('/admin/utilisateurs/refuser/<int:id>', methods=['POST'])
@login_required
@admin_requis
def refuser_compte(id):
    u = Utilisateur.query.get_or_404(id)
    nom = u.username; db.session.delete(u); db.session.commit()
    flash('Compte « ' + nom + ' » refusé.', 'success')
    return redirect(url_for('admin_utilisateurs'))


@app.route('/admin/utilisateurs/toggle/<int:id>', methods=['POST'])
@login_required
@admin_requis
def toggle_compte(id):
    u = Utilisateur.query.get_or_404(id)
    if u.id == current_user.id:
        flash('Vous ne pouvez pas vous désactiver.', 'error')
        return redirect(url_for('admin_utilisateurs'))
    u.is_active = not u.is_active; db.session.commit()
    flash('Compte « ' + u.username + ' » ' + ('activé' if u.is_active else 'désactivé') + '.', 'success')
    return redirect(url_for('admin_utilisateurs'))


@app.route('/admin/codes/creer', methods=['POST'])
@login_required
@admin_requis
def creer_code_invitation():
    import secrets as sec
    from datetime import timedelta
    nb_usages  = int(request.form.get('nb_usages', 1))
    duree_jours= int(request.form.get('duree_jours', 7))
    domaines   = request.form.get('domaines', '').strip() or None
    code_str   = request.form.get('code_custom','').strip().upper() or sec.token_urlsafe(8).upper()
    if CodeInvitation.query.filter_by(code=code_str).first():
        flash('Ce code existe déjà.', 'error')
        return redirect(url_for('admin_utilisateurs'))
    code = CodeInvitation(code=code_str, cree_par=current_user.id,
                          max_usages=nb_usages,
                          expire_le=datetime.now() + timedelta(days=duree_jours),
                          domaines_autorises=domaines)
    db.session.add(code); db.session.commit()
    flash('Code « ' + code_str + ' » créé.', 'success')
    return redirect(url_for('admin_utilisateurs'))


@app.route('/admin/codes/supprimer/<int:id>', methods=['POST'])
@login_required
@admin_requis
def supprimer_code(id):
    c = CodeInvitation.query.get_or_404(id)
    db.session.delete(c); db.session.commit()
    flash('Code supprimé.', 'success')
    return redirect(url_for('admin_utilisateurs'))


@app.route('/admin/donner-acces/<int:user_id>', methods=['POST'])
@login_required
@admin_requis
def donner_acces(user_id):
    """Donne un accès illimité (plan monthly) à un utilisateur."""
    from datetime import timedelta
    u = Utilisateur.query.get_or_404(user_id)
    plan = request.form.get('plan', 'monthly')

    # Créer ou mettre à jour l'abonnement
    ab = Abonnement.query.filter_by(user_id=u.id).first()
    if not ab:
        ab = Abonnement(user_id=u.id)
        db.session.add(ab)

    if plan == 'admin':
        # Accès admin complet
        u.role = 'admin'
        u.is_admin = True
        ab.plan = 'yearly'
        ab.statut = 'actif'
        ab.date_fin = None  # Illimité
        flash(f"« {u.username} » est maintenant admin avec accès illimité.", "success")
    elif plan == 'yearly':
        ab.plan = 'yearly'
        ab.statut = 'actif'
        ab.date_debut = datetime.now()
        ab.date_fin = datetime.now() + timedelta(days=365)
        flash(f"Accès annuel donné à « {u.username} » (valable 1 an).", "success")
    else:
        ab.plan = 'monthly'
        ab.statut = 'actif'
        ab.date_debut = datetime.now()
        ab.date_fin = datetime.now() + timedelta(days=30)
        flash(f"Accès mensuel donné à « {u.username} » (valable 30 jours).", "success")

    db.session.commit()

    creer_notification(
        entreprise_id=u.entreprise_id or current_user.entreprise_id,
        type='succes',
        titre='Accès mis à jour',
        message="Votre acces a ete mis a jour par l administrateur.",
        user_id=u.id
    )
    return redirect(url_for('admin_utilisateurs'))


@app.route('/admin/retirer-acces/<int:user_id>', methods=['POST'])
@login_required
@admin_requis
def retirer_acces(user_id):
    """Repasse un utilisateur en plan Free."""
    u = Utilisateur.query.get_or_404(user_id)
    ab = Abonnement.query.filter_by(user_id=u.id).first()
    if ab:
        ab.plan = 'free'; ab.statut = 'actif'; ab.date_fin = None
        db.session.commit()
    flash(f"Accès de « {u.username} » repassé en Gratuit.", "success")
    return redirect(url_for('admin_utilisateurs'))


# ════════════════════════════════════════════════════════════════
# CONVERSIONS DEVISES
# ════════════════════════════════════════════════════════════════

@app.route('/api/convertir')
@login_required
def api_convertir():
    """API de conversion de devises."""
    try:
        montant = float(request.args.get('montant', 0))
        src     = request.args.get('de', '€')
        dst     = request.args.get('vers', 'XOF')
        resultat = convertir(montant, src, dst)
        taux     = taux_de_change(src, dst)
        return {
            'ok': True,
            'montant': montant,
            'de': src,
            'vers': dst,
            'resultat': resultat,
            'taux': taux,
            'affichage': f"1 {src} = {taux} {dst}"
        }
    except Exception as e:
        return {'ok': False, 'erreur': str(e)}, 400


@app.route('/parametres/devise', methods=['POST'])
@login_required
def changer_devise():
    """Change la devise ET convertit tous les prix en base de données."""
    nouvelle_devise = request.form.get('devise', '€')
    if nouvelle_devise not in DEVISES:
        flash("Devise non supportée.", "error")
        return redirect(request.referrer or url_for('index'))

    old_devise = current_user.devise or '€'

    # Même devise → rien à faire
    if old_devise == nouvelle_devise:
        return redirect(request.referrer or url_for('index'))

    taux = taux_de_change(old_devise, nouvelle_devise)
    eid  = current_user.entreprise_id
    symb = DEVISES[nouvelle_devise]['symbole']
    nom  = DEVISES[nouvelle_devise]['nom']

    nb_produits_convertis = 0
    nb_ventes_converties  = 0

    try:
        # ── 1. Convertir les prix des produits ──
        produits = Produit.query.filter_by(entreprise_id=eid).all()
        for p in produits:
            p.prix = round(p.prix * taux, 2)
            nb_produits_convertis += 1

        # ── 2. Convertir les totaux des ventes ──
        ventes = Vente.query.filter_by(entreprise_id=eid).all()
        for v in ventes:
            v.total       = round(v.total       * taux, 2)
            v.total_final = round(v.total_final * taux, 2)
            # Convertir les lignes de vente
            for l in v.lignes:
                l.prix_unitaire = round(l.prix_unitaire * taux, 2)
                l.sous_total    = round(l.sous_total    * taux, 2)
            nb_ventes_converties += 1

        # ── 3. Convertir les reçus ──
        recus = Recu.query.filter_by(entreprise_id=eid).all()
        for r in recus:
            r.total = round(r.total * taux, 2)
            # Convertir les lignes JSON du reçu
            lignes = r.get_lignes()
            for l in lignes:
                l['prix']       = round(l.get('prix', 0) * taux, 2)
                l['sous_total'] = round(l.get('sous_total', 0) * taux, 2)
            r.lignes_json = json.dumps(lignes, ensure_ascii=False)

        # ── 4. Mettre à jour la devise de l'utilisateur ──
        current_user.devise = nouvelle_devise
        db.session.commit()

        app.logger.info(
            f"Conversion devise {old_devise}→{nouvelle_devise} "
            f"(taux {taux}) pour {current_user.username}: "
            f"{nb_produits_convertis} produits, {nb_ventes_converties} ventes"
        )

        flash(
            f"Devise changée vers {symb} ({nom}). "
            f"Taux appliqué : 1 {old_devise} = {taux:.4f} {nouvelle_devise}. "
            f"{nb_produits_convertis} produit(s) et {nb_ventes_converties} vente(s) convertis.",
            "success"
        )

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Erreur conversion devise : {e}")
        flash(f"Erreur lors de la conversion : {str(e)}", "error")

    return redirect(request.referrer or url_for('index'))

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
