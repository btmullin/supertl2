#!/usr/bin/env python3
from __future__ import annotations
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
import argparse, hashlib

DB_PATH = Path("app/db/supertl2.db")

def parse_local_to_utc(dt_str: str, local_tz: ZoneInfo) -> tuple[str, str]:
    """
    Parse a naive local-time string from StravaActivity.startDateTime and return:
      (start_time_local, start_time_utc)
    as ISO strings, e.g., '2025-08-29T06:00:00' and '2025-08-29T11:00:00Z'.
    """
    s = dt_str.strip().replace("/", "-")
    base = s.split(".")[0]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M"):
        try:
            naive = datetime.strptime(base, fmt)
            aware_local = naive.replace(tzinfo=local_tz)
            utc = aware_local.astimezone(timezone.utc)
            return (
                aware_local.strftime("%Y-%m-%dT%H:%M:%S"),   # local wall time, no 'Z'
                utc.strftime("%Y-%m-%dT%H:%M:%SZ"),         # UTC with 'Z'
            )
        except ValueError:
            continue
    if s.endswith("Z"):
        # Already UTC—treat local==UTC for lack of better info
        return (s[:-1], s)
    raise ValueError(f"Unrecognized datetime format: {dt_str!r}")

def ensure_schema_bits(conn: sqlite3.Connection) -> None:
    conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='activity'")
    conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='activity_source'")
    # add start_time_local if missing
    cols = {r[1] for r in conn.execute("PRAGMA table_info(activity_source)")}
    if "start_time_local" not in cols:
        conn.execute("ALTER TABLE activity_source ADD COLUMN start_time_local TEXT")

def upsert_activity_and_source(conn: sqlite3.Connection, local_tz: ZoneInfo) -> dict:
    cur = conn.cursor()
    cur.execute("""
        SELECT s.activityId,
               s.startDateTime,
               s.sportType,
               s.name,
               s.distance,
               s.movingTimeInSeconds
        FROM StravaActivity s
        LEFT JOIN activity_source asrc
          ON asrc.source='strava' AND asrc.source_activity_id = s.activityId
        WHERE asrc.id IS NULL
        ORDER BY s.startDateTime ASC
    """)
    rows = cur.fetchall()

    created_activity = 0
    created_source = 0

    for (act_id, start_dt, sport, name, distance, moving_s) in rows:
        start_local, start_utc = parse_local_to_utc(start_dt, local_tz)
        distance_f = float(distance) if distance is not None else None
        moving_i = int(moving_s) if moving_s is not None else None

        # Canonical master: store UTC
        c = conn.execute("""
            INSERT INTO activity (
                start_time_utc, end_time_utc, elapsed_time_s, moving_time_s,
                distance_m, name, sport
            )
            VALUES (?, NULL, ?, ?, ?, ?, ?)
        """, (start_utc, moving_i, moving_i, distance_f, name, sport))
        new_activity_id = c.lastrowid  # <-- get lastrowid from THIS cursor

        basis = f"{act_id}|{start_local}|{start_utc}|{sport}|{name}|{distance}|{moving_s}".encode("utf-8")
        payload_hash = hashlib.sha256(basis).hexdigest()

        # Source link: cache both local and UTC
        conn.execute("""
            INSERT INTO activity_source (
                activity_id, source, source_activity_id,
                start_time_local, start_time_utc,
                elapsed_time_s, distance_m, sport,
                payload_hash, match_confidence
            ) VALUES (?, 'strava', ?, ?, ?, ?, ?, ?, ?, 'A')
        """, (new_activity_id, act_id, start_local, start_utc, moving_i, distance_f, sport, payload_hash))
        created_source += 1

    return {"created_activity": created_activity, "created_source": created_source}

def main():
    ap = argparse.ArgumentParser(description="Backfill canonical activities from StravaActivity (keep local + UTC).")
    ap.add_argument("--db", default=str(DB_PATH), help="Path to supertl2.db")
    ap.add_argument("--local-tz", default="America/Chicago", help="IANA tz name of the stored local times")
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"DB not found: {db_path}")

    local_tz = ZoneInfo(args.local_tz)

    with closing(sqlite3.connect(db_path)) as conn:
        conn.isolation_level = None  # manual transactions
        conn.execute("PRAGMA foreign_keys = ON;")
        ensure_schema_bits(conn)
        try:
            conn.execute("BEGIN;")
            stats = upsert_activity_and_source(conn, local_tz)
            conn.execute("COMMIT;")
        except Exception:
            conn.execute("ROLLBACK;")
            raise

    print(f"Backfill complete: {stats}")

if __name__ == "__main__":
    main()
