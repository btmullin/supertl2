#!/usr/bin/env python3
"""
check_db_coverage.py

Coverage / quality checks for canonical DB.

- Coverage of Strava vs SportTracks sources
- TrainingLogData coverage
- Simple "weird value" checks on distance / duration
- Optional per-year breakdown

Usage:
  python check_db_coverage.py /path/to/supertl2.db
"""

import argparse
import sqlite3
from sqlite3 import Row


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    cur = conn.cursor
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone() is not None


def overall_coverage(conn: sqlite3.Connection):
    print("=== Overall coverage ===")
    cur = conn.cursor()

    # Total canonical activities
    cur.execute("SELECT COUNT(*) FROM activity")
    (total_activities,) = cur.fetchone()

    # Activities with at least one Strava source
    cur.execute(
        """
        SELECT COUNT(DISTINCT a.id)
        FROM activity a
        JOIN activity_source src
          ON src.activity_id = a.id
         AND src.source = 'strava'
        """
    )
    (with_strava,) = cur.fetchone()

    # Activities with at least one SportTracks source
    cur.execute(
        """
        SELECT COUNT(DISTINCT a.id)
        FROM activity a
        JOIN activity_source src
          ON src.activity_id = a.id
         AND src.source = 'sporttracks'
        """
    )
    (with_st,) = cur.fetchone()

    # Activities with both
    cur.execute(
        """
        SELECT COUNT(*)
        FROM (
            SELECT activity_id
            FROM activity_source
            GROUP BY activity_id
            HAVING SUM(CASE WHEN source='strava' THEN 1 ELSE 0 END) > 0
               AND SUM(CASE WHEN source='sporttracks' THEN 1 ELSE 0 END) > 0
        ) x
        """
    )
    (with_both,) = cur.fetchone()

    # TrainingLogData coverage
    if table_exists(conn, "TrainingLogData"):
        cur.execute(
            """
            SELECT COUNT(DISTINCT tld.canonical_activity_id)
            FROM TrainingLogData tld
            WHERE tld.canonical_activity_id IS NOT NULL
            """
        )
        (with_tld,) = cur.fetchone()
    else:
        with_tld = 0

    print(f"  Total canonical activities: {total_activities}")
    print(f"  With Strava source:        {with_strava} ({with_strava/total_activities:.1%} of total)")
    print(f"  With SportTracks source:   {with_st} ({with_st/total_activities:.1%} of total)")
    print(f"  With BOTH sources:         {with_both} ({with_both/total_activities:.1%} of total)")
    if table_exists(conn, "TrainingLogData"):
        print(f"  With TrainingLogData:      {with_tld} ({with_tld/total_activities:.1%} of total)")
    else:
        print("  TrainingLogData table missing; coverage not computed.")
    print()


def per_year_coverage(conn: sqlite3.Connection):
    print("=== Per-year canonical coverage (by start_time_utc year) ===")
    cur = conn.cursor()

    # Get distinct years
    cur.execute(
        """
        SELECT DISTINCT substr(start_time_utc, 1, 4) AS year
        FROM activity
        WHERE start_time_utc IS NOT NULL
        ORDER BY year
        """
    )
    years = [row[0] for row in cur.fetchall() if row[0] is not None]

    for year in years:
        print(f"  Year {year}:")
        cur.execute(
            """
            SELECT COUNT(*)
            FROM activity
            WHERE substr(start_time_utc, 1, 4) = ?
            """,
            (year,),
        )
        (total,) = cur.fetchone()

        cur.execute(
            """
            SELECT COUNT(DISTINCT a.id)
            FROM activity a
            JOIN activity_source src
              ON src.activity_id = a.id
             AND src.source = 'strava'
            WHERE substr(a.start_time_utc, 1, 4) = ?
            """,
            (year,),
        )
        (with_strava,) = cur.fetchone()

        cur.execute(
            """
            SELECT COUNT(DISTINCT a.id)
            FROM activity a
            JOIN activity_source src
              ON src.activity_id = a.id
             AND src.source = 'sporttracks'
            WHERE substr(a.start_time_utc, 1, 4) = ?
            """,
            (year,),
        )
        (with_st,) = cur.fetchone()

        if table_exists(conn, "TrainingLogData"):
            cur.execute(
                """
                SELECT COUNT(DISTINCT a.id)
                FROM activity a
                JOIN TrainingLogData tld
                  ON tld.canonical_activity_id = a.id
                WHERE substr(a.start_time_utc, 1, 4) = ?
                """,
                (year,),
            )
            (with_tld,) = cur.fetchone()
        else:
            with_tld = 0

        print(f"    Total:          {total}")
        print(f"    With Strava:    {with_strava} ({with_strava/total:.1%} of year)")
        print(f"    With SportTracks:{with_st} ({with_st/total:.1%} of year)")
        if table_exists(conn, "TrainingLogData"):
            print(f"    With TLD:       {with_tld} ({with_tld/total:.1%} of year)")
        print()
    print()


def weird_values_checks(conn: sqlite3.Connection):
    print("=== Weird value checks on activity ===")
    cur = conn.cursor()

    # Negative or zero elapsed_time_s with non-zero distance
    cur.execute(
        """
        SELECT COUNT(*)
        FROM activity
        WHERE (elapsed_time_s IS NOT NULL AND elapsed_time_s <= 0)
          AND (distance_m IS NOT NULL AND distance_m > 0)
        """
    )
    (cnt_bad_time,) = cur.fetchone()
    print(f"  Activities with non-positive elapsed_time_s and positive distance: {cnt_bad_time}")

    if cnt_bad_time > 0:
        print("  Sample (up to 10):")
        cur.execute(
            """
            SELECT id, start_time_utc, elapsed_time_s, distance_m, sport
            FROM activity
            WHERE (elapsed_time_s IS NOT NULL AND elapsed_time_s <= 0)
              AND (distance_m IS NOT NULL AND distance_m > 0)
            LIMIT 10
            """
        )
        for row in cur.fetchall():
            print(f"    id={row[0]}, start={row[1]}, elapsed={row[2]}, dist_m={row[3]}, sport={row[4]}")

    # Very long activities (e.g., > 24h) – adjust threshold if you like
    cur.execute(
        """
        SELECT COUNT(*)
        FROM activity
        WHERE elapsed_time_s IS NOT NULL
          AND elapsed_time_s > 24*3600
        """
    )
    (cnt_very_long,) = cur.fetchone()
    print(f"  Activities with elapsed_time_s > 24h: {cnt_very_long}")

    if cnt_very_long > 0:
        print("  Sample (up to 10):")
        cur.execute(
            """
            SELECT id, start_time_utc, elapsed_time_s, distance_m, sport, name
            FROM activity
            WHERE elapsed_time_s IS NOT NULL
              AND elapsed_time_s > 24*3600
            ORDER BY elapsed_time_s DESC
            LIMIT 10
            """
        )
        for row in cur.fetchall():
            aid, start, elapsed, dist, sport, name = row
            short_name = (name[:40] + "…") if name and len(name) > 40 else name
            print(
                f"    id={aid}, start={start}, elapsed_s={elapsed}, "
                f"dist_m={dist}, sport={sport}, name={short_name!r}"
            )

    print()


def main():
    parser = argparse.ArgumentParser(description="Coverage / quality checks for canonical DB.")
    parser.add_argument("db_path", help="Path to supertl2.db")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db_path)
    conn.row_factory = Row

    try:
        overall_coverage(conn)
        per_year_coverage(conn)
        weird_values_checks(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
