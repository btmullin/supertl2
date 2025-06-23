# app/db.py
import sqlite3
from flask import g
import os

STL_DB = '/app/db/supertl2.db'
STRAVA_DB = '/app/db/strava.db'

def get_stl_db():
    """Get the db for the stl app data."""
    if 'stl_db' not in g:
        g.db = sqlite3.connect(STL_DB)
        g.db.row_factory = sqlite3.Row
    return g.db

def get_strava_db():
    """Get the db for the strava imports."""
    if 'strava_db' not in g:
        g.strava_db = sqlite3.connect(STRAVA_DB)
        g.strava_db.row_factory = sqlite3.Row
    return g.strava_db

def close_dbs(e=None):
    """Close all of the databases."""
    db = g.pop('stl_db', None)
    if db is not None:
        db.close()

    strava_db = g.pop('strava_db', None)
    if strava_db is not None:
        strava_db.close()

def initialize_dbs():
    """Initialize all of the DBs for the app if they doesn't exist."""
    init_sqlite_db(path=STRAVA_DB)
    init_sqlite_db(path=STL_DB)

def init_sqlite_db(path):
    """Initialize the SQLite DB if it doesn't exist."""
    if not os.path.exists(path):
        print(f"Initializing DB at {path}")
        conn = sqlite3.connect(path)

        # Infer base name and directory
        base = os.path.splitext(os.path.basename(path))[0]  # e.g., 'supertl2'
        db_dir = os.path.dirname(path)

        schema_path = os.path.join(db_dir, f"{base}_schema.sql")
        data_path = os.path.join(db_dir, f"{base}_data.sql")

        # Apply schema (required)
        if os.path.exists(schema_path):
            with open(schema_path, 'r', encoding='utf-8') as f:
                conn.executescript(f.read())
        else:
            print(f"⚠️ Schema file not found: {schema_path}")
            conn.close()
            return

        # Apply optional data if it exists
        if os.path.exists(data_path):
            with open(data_path, 'r', encoding='utf-8') as f:
                conn.executescript(f.read())

        conn.commit()
        conn.close()

        print(f"✅ Initialized {base}.db")
    else:
        print(f"✔️ DB already exists: {path}")
