#!/usr/bin/env python3
"""
check_db_integrity.py

Basic integrity & sanity checks for the canonical training DB.

Usage:
  python check_db_integrity.py /path/to/supertl2.db
"""

import argparse
import sqlite3
from sqlite3 import Row


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    )
    return cur.fetchone() is not None


def run_counts(conn: sqlite3.Connection):
    print("=== Table row counts ===")
    cur = conn.cursor()

    for table in ["activity", "activity_source", "TrainingLogData", "sporttracks_activity"]:
        if table_exists(conn, table):
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            (cnt,) = cur.fetchone()
            print(f"  {table:20s}: {cnt}")
        else:
            print(f"  {table:20s}: (missing)")

    print()


def check_activity_source_orphans(conn: sqlite3.Connection):
    print("=== Orphan activity_source rows (no matching activity) ===")
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COUNT(*)
        FROM activity_source src
        LEFT JOIN activity a
          ON a.id = src.activity_id
        WHERE a.id IS NULL
        """
    )
    (cnt,) = cur.fetchone()
    print(f"  Orphan activity_source rows: {cnt}")

    if cnt > 0:
        print("  Sample orphans (up to 10):")
        cur.execute(
            """
            SELECT src.id, src.activity_id, src.source, src.source_activity_id
            FROM activity_source src
            LEFT JOIN activity a
              ON a.id = src.activity_id
            WHERE a.id IS NULL
            LIMIT 10
            """
        )
        for row in cur.fetchall():
            print(f"    id={row[0]}, activity_id={row[1]}, source={row[2]}, source_activity_id={row[3]}")
    print()


def check_activity_without_sources(conn: sqlite3.Connection):
    print("=== Canonical activities with no sources ===")
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COUNT(*)
        FROM activity a
        LEFT JOIN activity_source src
          ON src.activity_id = a.id
        WHERE src.id IS NULL
        """
    )
    (cnt,) = cur.fetchone()
    print(f"  Activities with zero activity_source rows: {cnt}")

    if cnt > 0:
        print("  Sample (up to 10):")
        cur.execute(
            """
            SELECT a.id, a.start_time_utc, a.sport, a.name
            FROM activity a
            LEFT JOIN activity_source src
              ON src.activity_id = a.id
            WHERE src.id IS NULL
            ORDER BY a.start_time_utc
            LIMIT 10
            """
        )
        for row in cur.fetchall():
            aid, start_time, sport, name = row
            short_name = (name[:60] + "…") if name and len(name) > 60 else name
            print(f"    id={aid}, start={start_time}, sport={sport}, name={short_name!r}")
    print()


def check_tld_canonical_orphans(conn: sqlite3.Connection):
    if not table_exists(conn, "TrainingLogData"):
        print("=== TrainingLogData checks ===")
        print("  TrainingLogData table missing; skipping.\n")
        return

    print("=== TrainingLogData → activity linkage ===")
    cur = conn.cursor()

    # TLD rows with canonical_activity_id set but no matching activity
    cur.execute(
        """
        SELECT COUNT(*)
        FROM TrainingLogData tld
        LEFT JOIN activity a
          ON a.id = tld.canonical_activity_id
        WHERE tld.canonical_activity_id IS NOT NULL
          AND a.id IS NULL
        """
    )
    (cnt_orphan,) = cur.fetchone()
    print(f"  TLD rows with canonical_activity_id pointing to missing activity: {cnt_orphan}")

    if cnt_orphan > 0:
        print("  Sample orphans (up to 10):")
        cur.execute(
            """
            SELECT tld.activityId, tld.canonical_activity_id, tld.categoryId, tld.workoutTypeId
            FROM TrainingLogData tld
            LEFT JOIN activity a
              ON a.id = tld.canonical_activity_id
            WHERE tld.canonical_activity_id IS NOT NULL
              AND a.id IS NULL
            LIMIT 10
            """
        )
        for row in cur.fetchall():
            print(f"    activityId={row[0]}, canonical_activity_id={row[1]}, cat={row[2]}, wtype={row[3]}")

    # TLD rows with NULL canonical_activity_id
    cur.execute(
        """
        SELECT COUNT(*)
        FROM TrainingLogData
        WHERE canonical_activity_id IS NULL
        """
    )
    (cnt_null,) = cur.fetchone()
    print(f"  TLD rows with canonical_activity_id IS NULL: {cnt_null}")

    if cnt_null > 0:
        print("  Sample with NULL canonical_activity_id (up to 10):")
        cur.execute(
            """
            SELECT activityId, categoryId, workoutTypeId, isTraining
            FROM TrainingLogData
            WHERE canonical_activity_id IS NULL
            LIMIT 10
            """
        )
        for row in cur.fetchall():
            print(f"    activityId={row[0]}, cat={row[1]}, wtype={row[2]}, isTraining={row[3]}")

    print()


def check_sporttracks_orphans(conn: sqlite3.Connection):
    if not table_exists(conn, "sporttracks_activity"):
        print("=== sporttracks_activity linkage ===")
        print("  sporttracks_activity missing; skipping.\n")
        return

    print("=== sporttracks_activity linkage ===")
    cur = conn.cursor()

    # sporttracks_activity rows not referenced by any activity_source
    cur.execute(
        """
        SELECT COUNT(*)
        FROM sporttracks_activity sa
        LEFT JOIN activity_source src
          ON src.source = 'sporttracks'
         AND src.source_activity_id = sa.activity_id
        WHERE src.id IS NULL
        """
    )
    (cnt_unlinked,) = cur.fetchone()
    print(f"  sporttracks_activity rows with no activity_source link: {cnt_unlinked}")

    if cnt_unlinked > 0:
        print("  Sample (up to 10):")
        cur.execute(
            """
            SELECT sa.activity_id, sa.start_date, sa.category, sa.name
            FROM sporttracks_activity sa
            LEFT JOIN activity_source src
              ON src.source = 'sporttracks'
             AND src.source_activity_id = sa.activity_id
            WHERE src.id IS NULL
            ORDER BY sa.start_date
            LIMIT 10
            """
        )
        for row in cur.fetchall():
            aid, start_date, cat, name = row
            short_name = (name[:40] + "…") if name and len(name) > 40 else name
            print(f"    st_id={aid}, date={start_date}, cat={cat}, name={short_name!r}")
    print()


def check_activity_source_uniqueness(conn: sqlite3.Connection):
    print("=== activity_source uniqueness (source, source_activity_id) ===")
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COUNT(*)
        FROM (
          SELECT source, source_activity_id, COUNT(*) AS cnt
          FROM activity_source
          GROUP BY source, source_activity_id
          HAVING COUNT(*) > 1
        )
        """
    )
    (cnt_dups,) = cur.fetchone()
    print(f"  Duplicate (source, source_activity_id) groups: {cnt_dups}")

    if cnt_dups > 0:
        print("  Sample duplicate keys (up to 10 groups):")
        cur.execute(
            """
            SELECT source, source_activity_id, COUNT(*) AS cnt
            FROM activity_source
            GROUP BY source, source_activity_id
            HAVING COUNT(*) > 1
            ORDER BY cnt DESC
            LIMIT 10
            """
        )
        for row in cur.fetchall():
            print(f"    source={row[0]}, source_activity_id={row[1]}, rows={row[2]}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Basic integrity checks for canonical DB.")
    parser.add_argument("db_path", help="Path to supertl2.db")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db_path)
    conn.row_factory = Row

    try:
        run_counts(conn)
        check_activity_source_orphans(conn)
        check_activity_without_sources(conn)
        check_tld_canonical_orphans(conn)
        check_sporttracks_orphans(conn)
        check_activity_source_uniqueness(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
