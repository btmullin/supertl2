#!/usr/bin/env python3
"""
Find likely timezone-mismatched canonical activity pairs.

We look for pairs of canonical activities where:
  - One activity has ONLY a Strava source
  - One activity has ONLY a SportTracks source
  - Their start times are approximately a whole number of hours apart
    (1–12 hours), allowing a small tolerance in minutes.
  - Their distances are within a gross threshold (e.g. 1000 m)

This helps identify activities that should have matched but didn't due
to timezone skew (UTC/local issues, DST, seconds differences, etc.).
"""

import sqlite3
import csv
import sys
from pathlib import Path

# ---------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------

# Canonical tables
ACTIVITY_TABLE = "activity"
ACTIVITY_SOURCE_TABLE = "activity_source"

# Column holding the canonical activity start time
# Change this if your schema uses a different column
ACTIVITY_START_TIME_COL = "start_time_utc"

# Column holding the canonical activity distance in meters
# Change this if your schema uses a different column name
DISTANCE_COL = "distance_m"

# Hour window for matching
MAX_HOUR_DIFF = 12

# How close (in minutes) to a "clean" hour difference we accept
HOUR_TOLERANCE_MIN = 5  # e.g. ±5 minutes from N hours

# Max allowed absolute distance difference in meters
DISTANCE_DIFF_THRESHOLD_M = 1000.0  # <- your requested gross distance comparison

# Match strings in activity_source.source
STRAVA_NAME = "strava"
SPORTTRACKS_NAME = "sporttracks"

# CSV output
WRITE_CSV = True
DEFAULT_CSV_NAME = "suspect_timezone_pairs.csv"


# ---------------------------------------------------------------------

def find_timezone_pairs(conn):
    """
    Return a list of rows representing suspect timezone-offset pairs.
    Each row has:
      strava_activity_id,
      sporttracks_activity_id,
      strava_start_time,
      sporttracks_start_time,
      hour_diff          (rounded integer number of hours),
      strava_distance_m,
      sporttracks_distance_m
    """

    # diff_hours  = (JULIANDAY(t) - JULIANDAY(s)) * 24
    # n           = ROUND(diff_hours)
    # We require:
    #   1 <= |n| <= MAX_HOUR_DIFF
    #   ABS(diff_hours - n) <= HOUR_TOLERANCE_MIN / 60.0
    # And also:
    #   distance not NULL for both, and
    #   ABS(strava_distance - sporttracks_distance) <= DISTANCE_DIFF_THRESHOLD_M

    sql = f"""
    WITH source_flags AS (
        SELECT
            a.id AS activity_id,
            a.{ACTIVITY_START_TIME_COL} AS start_time,
            a.{DISTANCE_COL} AS distance_m,
            MAX(CASE
                    WHEN LOWER(s.source) LIKE ? THEN 1
                    ELSE 0
                END) AS has_strava,
            MAX(CASE
                    WHEN LOWER(s.source) LIKE ? THEN 1
                    ELSE 0
                END) AS has_sporttracks
        FROM {ACTIVITY_TABLE} a
        JOIN {ACTIVITY_SOURCE_TABLE} s
          ON s.activity_id = a.id
        GROUP BY a.id
    ),
    strava_only AS (
        SELECT activity_id, start_time, distance_m
        FROM source_flags
        WHERE has_strava = 1 AND has_sporttracks = 0
          AND start_time IS NOT NULL
    ),
    sporttracks_only AS (
        SELECT activity_id, start_time, distance_m
        FROM source_flags
        WHERE has_strava = 0 AND has_sporttracks = 1
          AND start_time IS NOT NULL
    ),
    paired AS (
        SELECT
            s.activity_id    AS strava_activity_id,
            t.activity_id    AS sporttracks_activity_id,
            s.start_time     AS strava_start_time,
            t.start_time     AS sporttracks_start_time,
            s.distance_m     AS strava_distance_m,
            t.distance_m     AS sporttracks_distance_m,
            -- raw difference in hours (may be non-integer)
            (JULIANDAY(t.start_time) - JULIANDAY(s.start_time)) * 24.0 AS diff_hours
        FROM strava_only s
        JOIN sporttracks_only t
          -- Hard bound: up to ±MAX_HOUR_DIFF hours apart
          ON ABS((JULIANDAY(t.start_time) - JULIANDAY(s.start_time)) * 24.0)
             <= ?
    )
    SELECT
        p.strava_activity_id,
        p.sporttracks_activity_id,
        p.strava_start_time,
        p.sporttracks_start_time,
        CAST(ROUND(p.diff_hours) AS INTEGER) AS hour_diff,
        p.strava_distance_m,
        p.sporttracks_distance_m
    FROM paired p
    WHERE
        -- Rounded difference in hours is between 1 and MAX_HOUR_DIFF
        ABS(ROUND(p.diff_hours)) BETWEEN 1 AND ?
        -- And the actual difference is within HOUR_TOLERANCE_MIN of that integer
        AND ABS(p.diff_hours - ROUND(p.diff_hours))
            <= (? / 60.0)
        -- Distance filter: both distances present and within threshold
        AND p.strava_distance_m IS NOT NULL
        AND p.sporttracks_distance_m IS NOT NULL
        AND ABS(p.strava_distance_m - p.sporttracks_distance_m) <= ?
    ORDER BY ABS(hour_diff), p.strava_start_time, p.sporttracks_start_time;
    """

    cur = conn.cursor()
    cur.execute(
        sql,
        (
            f"%{STRAVA_NAME}%",
            f"%{SPORTTRACKS_NAME}%",
            float(MAX_HOUR_DIFF),
            MAX_HOUR_DIFF,
            float(HOUR_TOLERANCE_MIN),
            float(DISTANCE_DIFF_THRESHOLD_M),
        ),
    )
    return cur.fetchall()


def main():
    # -----------------------------------------------------------------
    # Parse args
    # -----------------------------------------------------------------
    if len(sys.argv) != 2:
        print("Usage: find_timezone_mismatch_pairs.py <path/to/supertl2.db>")
        sys.exit(1)

    db_path = Path(sys.argv[1])
    if not db_path.exists():
        sys.exit(f"Error: DB file does not exist: {db_path}")

    csv_path = db_path.parent / DEFAULT_CSV_NAME

    # -----------------------------------------------------------------
    # Run query
    # -----------------------------------------------------------------
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    rows = find_timezone_pairs(conn)

    print(f"Found {len(rows)} suspect Strava-only / SportTracks-only pairs.\n")

    # Print table header
    header = [
        "strava_activity_id",
        "sporttracks_activity_id",
        "strava_start_time",
        "sporttracks_start_time",
        "hour_diff",
        "strava_distance_m",
        "sporttracks_distance_m",
    ]
    print("\t".join(header))

    for r in rows:
        print(
            f"{r['strava_activity_id']}\t"
            f"{r['sporttracks_activity_id']}\t"
            f"{r['strava_start_time']}\t"
            f"{r['sporttracks_start_time']}\t"
            f"{r['hour_diff']}\t"
            f"{r['strava_distance_m']}\t"
            f"{r['sporttracks_distance_m']}"
        )

    # -----------------------------------------------------------------
    # Optional CSV output
    # -----------------------------------------------------------------
    if WRITE_CSV:
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            for r in rows:
                writer.writerow(
                    [
                        r["strava_activity_id"],
                        r["sporttracks_activity_id"],
                        r["strava_start_time"],
                        r["sporttracks_start_time"],
                        r["hour_diff"],
                        r["strava_distance_m"],
                        r["sporttracks_distance_m"],
                    ]
                )
        print(f"\nWrote CSV to: {csv_path}")


if __name__ == "__main__":
    main()
