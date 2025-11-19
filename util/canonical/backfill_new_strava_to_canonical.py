#!/usr/bin/env python3
"""
Backfill *new* Strava activities into the canonical activity + activity_source tables.

Logic:
- Look at supertl2.db.StravaActivity (cloned from stats-for-strava).
- For any StravaActivity row that does NOT have an activity_source row with
  (source='strava', source_activity_id=activityId), create:
    - a new activity row
    - a new activity_source row pointing to that activity
    - update TrainingLogData.canonical_activity_id if there is a matching row

Assumptions:
- StravaActivity.startDateTime is stored in local time (America/Chicago).
- We convert it to UTC and store that in activity.start_time_utc (ISO8601 with 'Z').
"""

import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo  # Python 3.9+

DB_PATH = r"c:\git\supertl2\db\supertl2.db"  # adjust path if needed


def to_utc_iso(start_local: str) -> tuple[str, str]:
    """
    Convert a 'YYYY-MM-DD HH:MM:SS' local timestamp (America/Chicago)
    to:
      - UTC ISO8601 with 'Z' (for activity.start_time_utc / activity_source.start_time_utc)
      - local ISO8601 with offset (for activity_source.start_time_local)
    """
    local_tz = ZoneInfo("America/Chicago")
    dt_local = datetime.fromisoformat(start_local)  # naive
    dt_local = dt_local.replace(tzinfo=local_tz)
    dt_utc = dt_local.astimezone(ZoneInfo("UTC"))

    start_time_utc = dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    start_time_local = dt_local.isoformat()  # e.g. 2025-09-02T18:11:42-05:00
    return start_time_utc, start_time_local


def backfill_new_strava():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 1) Find StravaActivity rows that do not yet have an activity_source mapping
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

    if not rows:
        print("No unmapped Strava activities found. Nothing to do.")
        return

    print(f"Found {len(rows)} unmapped Strava activities to backfill.")

    inserted_activities = 0
    inserted_sources = 0
    updated_tld = 0

    try:
        for r in rows:
            activity_id_strava = r["activityId"]
            start_local = r["startDateTime"]        # 'YYYY-MM-DD HH:MM:SS'
            sport_type = r["sportType"]
            distance_m = r["distance"]
            moving_time_s = r["movingTimeInSeconds"]
            name = r["name"]

            # Convert to UTC + capture local
            start_time_utc, start_time_local = to_utc_iso(start_local)

            # For now, treat elapsed_time_s = moving_time_s.
            elapsed_time_s = moving_time_s

            # 2) Insert into activity
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
                ) VALUES (?, NULL, ?, ?, ?, ?, ?, 0)
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

            # 3) Insert into activity_source
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
                ) VALUES (
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

            # 4) Link TrainingLogData if present
            cur.execute("""
                UPDATE TrainingLogData
                   SET canonical_activity_id = ?
                 WHERE activityId = ?
            """, (canonical_activity_id, activity_id_strava))
            updated_tld += cur.rowcount

        conn.commit()

    except Exception as e:
        conn.rollback()
        print("Error during backfill, rolled back transaction:", e)
        raise

    finally:
        conn.close()

    print(f"Inserted {inserted_activities} new activity rows.")
    print(f"Inserted {inserted_sources} new activity_source rows.")
    print(f"Updated {updated_tld} TrainingLogData rows.")


if __name__ == "__main__":
    backfill_new_strava()
