#!/usr/bin/env python3
"""
Backfill *new* Strava activities into the canonical activity + activity_source tables.

Usage:
- As a script:
    python backfill_new_strava_to_canonical.py

- As a function from Flask:
    from util.canoncial.backfill_new_strava_to_canonical import backfill_new_strava
    backfill_new_strava(db_path)

Where db_path is the path to supertl2.db (we'll pull it from SQLAlchemy engine.url.database).
"""

import os
import sqlite3
from datetime import datetime

# Try to get timezone support; fall back gracefully
try:
    from zoneinfo import ZoneInfo  # Python 3.9+
    LOCAL_TZ = ZoneInfo("America/Chicago")
    USE_TZ = True
except Exception:
    LOCAL_TZ = None
    USE_TZ = False

# Fallback default if no path is passed (can be overridden via env var)
DEFAULT_DB_PATH = os.environ.get("SUPERTL2_DB_PATH", "supertl2.db")


def _to_times(start_local: str) -> tuple[str, str]:
    """
    Convert 'YYYY-MM-DD HH:MM:SS' local timestamp to:
    - UTC ISO8601 (YYYY-MM-DDTHH:MM:SSZ)
    - local ISO8601 (for start_time_local)

    If zoneinfo isn't available, we treat local as UTC but still
    format it correctly.
    """
    dt_local = datetime.fromisoformat(start_local)  # naive

    if USE_TZ and LOCAL_TZ is not None:
        dt_local = dt_local.replace(tzinfo=LOCAL_TZ)
        dt_utc = dt_local.astimezone(ZoneInfo("UTC"))
        start_time_utc = dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        start_time_local = dt_local.isoformat()
    else:
        # Fallback: treat local time as UTC
        start_time_utc = dt_local.strftime("%Y-%m-%dT%H:%M:%SZ")
        start_time_local = dt_local.isoformat()

    return start_time_utc, start_time_local


def backfill_new_strava(db_path: str | None = None) -> dict:
    """
    Backfill StravaActivity rows that don't yet have an activity_source entry.

    :param db_path: Path to supertl2.db. If None, uses DEFAULT_DB_PATH.
    :return: dict with counts for logging / debugging
    """
    if db_path is None:
        db_path = DEFAULT_DB_PATH

    db_path = os.path.abspath(db_path)
    print(f"[backfill_new_strava] Using DB: {db_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Sanity checks
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {r["name"] for r in cur.fetchall()}
    required = {"StravaActivity", "activity", "activity_source"}
    missing = required - tables
    if missing:
        raise RuntimeError(
            f"Missing required tables in {db_path}: {', '.join(sorted(missing))}"
        )

    # Count unmapped before
    cur.execute("""
        SELECT COUNT(*) AS unmapped
        FROM StravaActivity s
        LEFT JOIN activity_source src
          ON src.source = 'strava'
         AND src.source_activity_id = s.activityId
        WHERE src.activity_id IS NULL
    """)
    unmapped_before = cur.fetchone()["unmapped"]
    print(f"[backfill_new_strava] Unmapped Strava rows BEFORE: {unmapped_before}")

    if unmapped_before == 0:
        conn.close()
        return {
            "unmapped_before": 0,
            "inserted_activities": 0,
            "inserted_sources": 0,
            "updated_tld": 0,
            "unmapped_after": 0,
        }

    # Fetch unmapped rows
    cur.execute("""
        SELECT s.activityId,
               s.startDateTime,
               s.sportType,
               s.distance,
               s.movingTimeInSeconds,
               s.name
        FROM StravaActivity s
        LEFT JOIN activity_source src
          ON src.source = 'strava'
         AND src.source_activity_id = s.activityId
        WHERE src.activity_id IS NULL
        ORDER BY s.startDateTime
    """)
    rows = cur.fetchall()
    print(f"[backfill_new_strava] Will backfill {len(rows)} Strava activities.")

    inserted_activities = 0
    inserted_sources = 0
    updated_tld = 0

    try:
        for r in rows:
            activity_id_strava = r["activityId"]
            start_local = r["startDateTime"]
            sport_type = r["sportType"]
            distance_m = r["distance"]
            moving_time_s = r["movingTimeInSeconds"]
            name = r["name"]

            start_time_utc, start_time_local = _to_times(start_local)
            elapsed_time_s = moving_time_s  # simple assumption

            # Insert into activity
            cur.execute("""
                INSERT INTO activity (
                    start_time_utc,
                    end_time_utc,
                    elapsed_time_s,
                    moving_time_s,
                    distance_m,
                    name,
                    sport,
                    source_quality
                )
                VALUES (?, NULL, ?, ?, ?, ?, ?, 0)
            """, (
                start_time_utc,
                elapsed_time_s,
                moving_time_s,
                distance_m,
                name,
                sport_type,
            ))
            canonical_activity_id = cur.lastrowid
            inserted_activities += 1

            # Insert into activity_source
            cur.execute("""
                INSERT INTO activity_source (
                    activity_id,
                    source,
                    source_activity_id,
                    start_time_utc,
                    elapsed_time_s,
                    distance_m,
                    sport,
                    payload_hash,
                    match_confidence,
                    start_time_local
                )
                VALUES (
                    ?, 'strava', ?, ?, ?, ?, ?, NULL, ?, ?
                )
            """, (
                canonical_activity_id,
                activity_id_strava,
                start_time_utc,
                elapsed_time_s,
                distance_m,
                sport_type,
                "direct-strava",
                start_time_local,
            ))
            inserted_sources += 1

            # Link TrainingLogData if present
            cur.execute("""
                UPDATE TrainingLogData
                   SET canonical_activity_id = ?
                 WHERE activityId = ?
            """, (canonical_activity_id, activity_id_strava))
            updated_tld += cur.rowcount

        conn.commit()

    except Exception:
        conn.rollback()
        conn.close()
        raise

    # Re-count unmapped after
    cur.execute("""
        SELECT COUNT(*) AS unmapped
        FROM StravaActivity s
        LEFT JOIN activity_source src
          ON src.source = 'strava'
         AND src.source_activity_id = s.activityId
        WHERE src.activity_id IS NULL
    """)
    unmapped_after = cur.fetchone()["unmapped"]
    conn.close()

    print(f"[backfill_new_strava] Inserted {inserted_activities} activity rows.")
    print(f"[backfill_new_strava] Inserted {inserted_sources} activity_source rows.")
    print(f"[backfill_new_strava] Updated {updated_tld} TrainingLogData rows.")
    print(f"[backfill_new_strava] Unmapped Strava rows AFTER: {unmapped_after}")

    return {
        "unmapped_before": unmapped_before,
        "inserted_activities": inserted_activities,
        "inserted_sources": inserted_sources,
        "updated_tld": updated_tld,
        "unmapped_after": unmapped_after,
    }


if __name__ == "__main__":
    # CLI usage, uses DEFAULT_DB_PATH or SUPERTL2_DB_PATH
    backfill_new_strava()
