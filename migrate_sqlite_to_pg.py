"""
Script de migration des données SQLite → PostgreSQL.
Lancer UNE SEULE FOIS après avoir configuré DATABASE_URL.

Usage :
    set DATABASE_URL=postgresql://user:password@host:5432/stockdb  (Windows)
    export DATABASE_URL=postgresql://...                             (Mac/Linux)
    python migrate_sqlite_to_pg.py
"""
import sqlite3
import os
import sys

# ── Vérification ────────────────────────────────────────────────
DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL or 'sqlite' in DATABASE_URL:
    print("ERREUR : Définir DATABASE_URL avec une URL PostgreSQL.")
    print("Exemple : postgresql://user:password@localhost:5432/stockdb")
    sys.exit(1)

if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

SQLITE_PATH = 'stock.db'
if not os.path.exists(SQLITE_PATH):
    print(f"ERREUR : Fichier {SQLITE_PATH} introuvable.")
    sys.exit(1)

# ── Connexion SQLite (source) ────────────────────────────────────
sqlite_conn = sqlite3.connect(SQLITE_PATH)
sqlite_conn.row_factory = sqlite3.Row

# ── Connexion PostgreSQL (destination) via psycopg2 ─────────────
try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("ERREUR : pip install psycopg2-binary")
    sys.exit(1)

pg_conn   = psycopg2.connect(DATABASE_URL)
pg_cursor = pg_conn.cursor()

print("Connexions établies.")
print("=" * 50)

# ── Créer les tables PostgreSQL via Flask-SQLAlchemy ────────────
print("Création des tables PostgreSQL...")
os.environ['DATABASE_URL'] = DATABASE_URL
os.environ['FLASK_APP'] = 'app_postgresql.py'

from app_postgresql import app, db
with app.app_context():
    db.create_all()
    print("  Tables créées.")

    # ── Migrer categories ────────────────────────────────────────
    rows = sqlite_conn.execute("SELECT * FROM categories").fetchall()
    count = 0
    for r in rows:
        try:
            pg_cursor.execute(
                "INSERT INTO categories (id, nom) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (r['id'], r['nom'])
            )
            count += 1
        except Exception as e:
            print(f"  SKIP categorie {r['id']} : {e}")
    pg_conn.commit()
    print(f"  categories : {count}/{len(rows)} lignes migrées")

    # ── Migrer fournisseurs ──────────────────────────────────────
    rows = sqlite_conn.execute("SELECT * FROM fournisseurs").fetchall()
    count = 0
    for r in rows:
        try:
            pg_cursor.execute(
                "INSERT INTO fournisseurs (id, nom, contact, email, telephone) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (r['id'], r['nom'], r['contact'], r['email'], r['telephone'])
            )
            count += 1
        except Exception as e:
            print(f"  SKIP fournisseur {r['id']} : {e}")
    pg_conn.commit()
    print(f"  fournisseurs : {count}/{len(rows)} lignes migrées")

    # ── Migrer utilisateurs ──────────────────────────────────────
    rows = sqlite_conn.execute("SELECT * FROM utilisateurs").fetchall()
    count = 0
    for r in rows:
        try:
            email = r['email'] if 'email' in r.keys() else ''
            pg_cursor.execute(
                "INSERT INTO utilisateurs (id, username, password, email) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (r['id'], r['username'], r['password'], email)
            )
            count += 1
        except Exception as e:
            print(f"  SKIP utilisateur {r['id']} : {e}")
    pg_conn.commit()
    print(f"  utilisateurs : {count}/{len(rows)} lignes migrées")

    # ── Migrer produits ──────────────────────────────────────────
    rows = sqlite_conn.execute("SELECT * FROM produits").fetchall()
    keys = rows[0].keys() if rows else []
    count = 0
    for r in rows:
        try:
            cat_id  = r['categorie_id']   if 'categorie_id'   in keys else None
            four_id = r['fournisseur_id'] if 'fournisseur_id' in keys else None
            pg_cursor.execute(
                "INSERT INTO produits (id, nom, quantite, prix, seuil, categorie_id, fournisseur_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (r['id'], r['nom'], r['quantite'], r['prix'], r['seuil'], cat_id, four_id)
            )
            count += 1
        except Exception as e:
            print(f"  SKIP produit {r['id']} : {e}")
    pg_conn.commit()
    print(f"  produits : {count}/{len(rows)} lignes migrées")

    # ── Migrer mouvements ────────────────────────────────────────
    rows = sqlite_conn.execute("SELECT * FROM mouvements").fetchall()
    count = 0
    for r in rows:
        try:
            pg_cursor.execute(
                "INSERT INTO mouvements (id, produit_id, produit_nom, type, quantite, date, note) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (r['id'], r['produit_id'], r['produit_nom'],
                 r['type'], r['quantite'], r['date'], r['note'])
            )
            count += 1
        except Exception as e:
            print(f"  SKIP mouvement {r['id']} : {e}")
    pg_conn.commit()
    print(f"  mouvements : {count}/{len(rows)} lignes migrées")

    # ── Resynchroniser les séquences PostgreSQL ──────────────────
    # (évite les conflits d'ID lors des prochains INSERT)
    tables = ['categories', 'fournisseurs', 'utilisateurs', 'produits', 'mouvements']
    for table in tables:
        try:
            pg_cursor.execute(f"""
                SELECT setval(pg_get_serial_sequence('{table}', 'id'),
                              COALESCE(MAX(id), 1))
                FROM {table}
            """)
            pg_conn.commit()
        except Exception as e:
            print(f"  SKIP sequence {table} : {e}")
    print("  Séquences resynchronisées.")

print("=" * 50)
print("Migration terminée avec succès !")
print("Lance maintenant : python app_postgresql.py")

sqlite_conn.close()
pg_conn.close()
