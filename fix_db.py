import sqlite3, os

db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'stock.db')
print(f"Base: {db_path}")

c = sqlite3.connect(db_path)

# Vérifier les tables existantes
tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print(f"Tables existantes: {tables}")

if 'utilisateurs' not in tables:
    print("La table utilisateurs n'existe pas — supprime stock.db et relance app.py")
    c.close()
    exit(0)

colonnes = [
    ("utilisateurs", "devise",             "VARCHAR(10) DEFAULT '€'"),
    ("utilisateurs", "role",               "VARCHAR(20) DEFAULT 'admin'"),
    ("utilisateurs", "entreprise_id",      "INTEGER DEFAULT NULL"),
    ("utilisateurs", "email_verifie",      "BOOLEAN DEFAULT 0"),
    ("utilisateurs", "is_active",          "BOOLEAN DEFAULT 1"),
    ("utilisateurs", "validation_admin",   "BOOLEAN DEFAULT 1"),
    ("utilisateurs", "cree_le",            "DATETIME DEFAULT NULL"),
    ("utilisateurs", "token_verification", "VARCHAR(100) DEFAULT NULL"),
    ("utilisateurs", "token_reset",        "VARCHAR(100) DEFAULT NULL"),
    ("utilisateurs", "token_reset_exp",    "DATETIME DEFAULT NULL"),
    ("utilisateurs", "onboarding_complete","BOOLEAN DEFAULT 0"),
]

if 'produits' in tables:
    colonnes += [
        ("produits", "code_barres", "VARCHAR(100) DEFAULT NULL"),
    ]

for table, col, typ in colonnes:
    if table not in tables:
        print(f"SKIP - table {table} inexistante")
        continue
    existing = [r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()]
    if col not in existing:
        try:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
            print(f"OK - {table}.{col} ajoutée")
        except Exception as e:
            print(f"ERREUR {table}.{col}: {e}")
    else:
        print(f"SKIP - {table}.{col} existe déjà")

# Activer tous les comptes
if 'utilisateurs' in tables:
    c.execute("UPDATE utilisateurs SET is_active=1 WHERE is_active IS NULL OR is_active=0")
    print(f"OK - comptes activés")

c.commit()
c.close()
print("\nTerminé !")
