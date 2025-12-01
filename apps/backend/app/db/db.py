# app/db.py
import sqlite3
from flask import g
import os
from .base import sqla_db
from ..models.activitysource import ActivitySource

STL_DB = '/app/db/supertl2.db'
STRAVA_DB = '/stravadb/strava.db'

def get_stl_db():
    """Get the db for the stl app data."""
    if 'stl_db' not in g:
        g.db = sqlite3.connect(STL_DB)
        g.db.row_factory = sqlite3.Row
    return g.db

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

def import_strava_data():
    """Import new Strava activities into the Supertl2Extra table."""
    supertl_db = get_stl_db()

    stl_cursor = supertl_db.cursor()

    # Attach the Strava database under the alias "strava"
    stl_cursor.execute(f"ATTACH DATABASE '{STRAVA_DB}' AS strava")

    ## ACTIVITY IMPORT ##
    # Print which activities are new
    stl_cursor.execute("""
                       SELECT name, activityId FROM strava.Activity WHERE activityId NOT IN (SELECT activityId FROM StravaActivity)
                       """)
    new_activities = stl_cursor.fetchall()
    print(f"Found {len(new_activities)} new activities to import.")
    for activity in new_activities:
        print(f"Importing new activity: {activity['name']}")

    # Insert activities that don't exist yet in supertl
    stl_cursor.execute("""
        INSERT INTO StravaActivity
        SELECT *
        FROM strava.Activity
        WHERE activityId NOT IN (SELECT activityId FROM StravaActivity)
    """)

    ## STREAM IMPORT ##
    # Print which activities are new
    stl_cursor.execute("""
                       SELECT DISTINCT activityId FROM strava.ActivityStream WHERE activityId NOT IN (SELECT activityId FROM StravaActivityStream)
                       """)
    new_activity_streams = stl_cursor.fetchall()
    print(f"Found {len(new_activity_streams)} new activities with streams to import.")

    # Insert activities that don't exist yet in supertl
    stl_cursor.execute("""
        INSERT INTO StravaActivityStream
        SELECT *
        FROM strava.ActivityStream s
        WHERE NOT EXISTS (
            SELECT 1 FROM StravaActivityStream t
            WHERE t.activityId = s.activityId AND t.streamType = s.streamType
        )
    """)

    supertl_db.commit()

def get_canonical_activities(limit=100, offset=0):
    """
    Return canonical activities with optional TrainingLogData joined.
    """
    db = get_stl_db()

    cur = db.execute(
        """
        SELECT
            a.id,
            a.start_time_utc,
            a.sport as sportType,
            a.name,
            a.distance_m as distance,
            a.moving_time_s as movingTimeInSeconds,

            -- Training Log fields
            t.canonical_activity_id,
            t.isTraining,
            t.categoryId,
            t.notes,
            t.tags

        FROM activity a
        LEFT JOIN TrainingLogData t
          ON t.canonical_activity_id = a.id

        ORDER BY a.start_time_utc DESC
        LIMIT ? OFFSET ?
        """,
        (limit, offset),
    )

    return cur.fetchall()


def get_canonical_activity_count():
    """
    Return total number of canonical activities.
    """
    db = get_stl_db()
    cur = db.execute("SELECT COUNT(*) AS cnt FROM activity")
    row = cur.fetchone()
    return row["cnt"] if row else 0


def get_canonical_activity(activity_id: int):
    """
    Return a single canonical activity row by id.
    """
    db = get_stl_db()
    cur = db.execute(
        """
        SELECT
            id,
            start_time_utc,
            end_time_utc,
            elapsed_time_s,
            moving_time_s,
            distance_m,
            sport,
            name,
            source_quality,
            created_at_utc,
            updated_at_utc
        FROM activity
        WHERE id = ?
        """,
        (activity_id,),
    )
    return cur.fetchone()

def get_canonical_id_for_strava_activity(strava_activity_id: str | int) -> int | None:
    """
    Given a Strava activityId, return the canonical activity.id, or None.
    """
    return (
        sqla_db.session.query(ActivitySource.activity_id)
        .filter(
            ActivitySource.source == "strava",
            ActivitySource.source_activity_id == str(strava_activity_id),
        )
        .scalar()
    )

def get_strava_activity_id_for_canonical_activity(canonical_id: int) -> str | None:
    """
    Given a canonical activity.id, return the Strava activityId, or None.
    """
    return (
        sqla_db.session.query(ActivitySource.source_activity_id)
        .filter(
            ActivitySource.activity_id == canonical_id,
            ActivitySource.source == "strava",
        )
        .scalar()
    )

