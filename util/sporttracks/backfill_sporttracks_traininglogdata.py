#!/usr/bin/env python3
"""
Backfill TrainingLogData from SportTracks-only canonical activities.

For each canonical activity that:
  - has ONLY SportTracks sources
  - has NO TrainingLogData row yet (by canonical_activity_id)
  - has a SportTracks category in CATEGORY_MAP

We create a TrainingLogData row with:
  - activityId            = "st-" + sporttracks_activity_id   (synthetic key)
  - canonical_activity_id = activity.id
  - workoutTypeId         = 1   (General)
  - categoryId            = mapped from SportTracks category
  - isTraining            = 1   (yes)

Notes/tags are left NULL.

Run with --dry-run first to check what it will do.
"""

import argparse
import sqlite3
from typing import Dict


# ---------------------------------------------------------------------------
# 1. Configure your SportTracks → Category.id mapping here
#    Keys: sporttracks_activity.category (leaf labels like "XC Skate", "Strength", etc.)
#    Values: Category.id in your new system
# ---------------------------------------------------------------------------
CATEGORY_MAP: Dict[str, int] = {
    # Example placeholders – replace with your real mapping:
    # "XC Skate":   10,
    # "XC Classic": 11,
    "Roller":     3,
    "Strength":   15,
    "Trail":      10,
    "Mountain":   14,
    "Running":    8,
    "Trainer":    18,
    "Nordic":     16,
    "Treadmill":   24,
    "Road":        12,
    "Speed":       8,
    "XC Skate":   4,
    "XC Classic": 5,
}


def get_candidate_activities(conn: sqlite3.Connection):
    """
    Return all canonical activities that:
      - only have SportTracks sources
      - have no TrainingLogData row yet (canonical_activity_id is NULL for this activity)

    We *do not* filter by CATEGORY_MAP here on purpose so that in dry-run we can
    also see categories that are currently unmapped.
    """
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    sql = """
    SELECT DISTINCT
        a.id           AS activity_id,
        sa.activity_id AS st_activity_id,
        sa.category    AS st_category,
        sa.start_date  AS start_date
    FROM activity a
    JOIN activity_source src
      ON src.activity_id = a.id
     AND src.source = 'sporttracks'
    JOIN sporttracks_activity sa
      ON sa.activity_id = src.source_activity_id
    -- Ensure ONLY SportTracks for this canonical activity
    WHERE NOT EXISTS (
        SELECT 1
        FROM TrainingLogData tld
        WHERE tld.canonical_activity_id = a.id
    )
    ORDER BY a.id;
    """

    cur.execute(sql)
    return cur.fetchall()


def backfill(conn: sqlite3.Connection, dry_run: bool = False):
    cur = conn.cursor()

    rows = get_candidate_activities(conn)
    total = len(rows)
    print(f"Found {total} candidate activities.")

    created = 0
    would_map = 0
    skipped_missing_map = 0

    # For dry-run reporting: which categories we *didn't* map
    unmapped_categories: Dict[str, int] = {}

    for idx, row in enumerate(rows, start=1):
        activity_id = row["activity_id"]         # canonical activity.id
        st_activity_id = row["st_activity_id"]   # sporttracks_activity.activity_id (TEXT)
        st_cat = row["st_category"]
        start_date = row["start_date"]

        if st_cat not in CATEGORY_MAP:
            print(
                f"[warn] canonical {activity_id}: category '{st_cat}' "
                f"not in CATEGORY_MAP; skipping."
            )
            skipped_missing_map += 1
            unmapped_categories[st_cat] = unmapped_categories.get(st_cat, 0) + 1
            continue

        category_id = CATEGORY_MAP[st_cat]

        # Synthetic primary key for TrainingLogData.activityId
        # This avoids collisions with Strava activity IDs.
        tld_activity_id = f"st-{st_activity_id}"

        if dry_run:
            print(
                f"[dry-run] would insert TrainingLogData("
                f"activityId='{tld_activity_id}', canonical_activity_id={activity_id}, "
                f"workoutTypeId=1, categoryId={category_id}, isTraining=1, "
                f"st_category='{st_cat}') "
                f"on {start_date}"
            )
            would_map += 1
        else:
            cur.execute(
                """
                INSERT INTO TrainingLogData (
                    activityId,
                    workoutTypeId,
                    categoryId,
                    isTraining,
                    canonical_activity_id
                )
                VALUES (?, 1, ?, 1, ?)
                """,
                (tld_activity_id, category_id, activity_id),
            )
            created += 1

        if idx % 25 == 0:
            print(f"Processed {idx}/{total} candidates...")

    if not dry_run:
        conn.commit()

    print("Done.")
    print(f"  TrainingLogData rows created: {created}")
    print(f"  Skipped (category not in map): {skipped_missing_map}")
    print(f"  Would create (dry-run, mapped categories): {would_map}")

    # Extra summary in dry-run: list unmapped categories
    if dry_run and unmapped_categories:
        print("\nUnmapped SportTracks categories encountered (category: count):")
        for cat in sorted(unmapped_categories.keys(), key=lambda c: (c is None, str(c))):
            count = unmapped_categories[cat]
            print(f"  {repr(cat)}: {count}")

        print(
            "\nHint: add any categories you want to map to CATEGORY_MAP at the top "
            "of this script and re-run the dry-run."
        )

    if dry_run:
        print("\nNo changes were committed (dry-run mode).")


def main():
    parser = argparse.ArgumentParser(
        description="Backfill TrainingLogData from SportTracks-only canonical activities."
    )
    parser.add_argument(
        "db_path",
        help="Path to supertl2.db (or your canonical database file).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not write anything; just show what would be done.",
    )
    args = parser.parse_args()

    conn = sqlite3.connect(args.db_path)
    try:
        backfill(conn, dry_run=args.dry_run)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
