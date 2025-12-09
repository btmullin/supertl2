#!/usr/bin/env python3
"""
Merge confirmed canonical activity pairs.
Use after identifying pairs with suspect_timezone_pairs.py

Given:
  - A SQLite database (supertl2.db)
  - A CSV file with columns: keep_id,drop_id

This script will, for each row:
  1. Reassign all activity_source rows from drop_id -> keep_id
  2. Reassign all TrainingLogData rows from drop_id -> keep_id (if table exists)
  3. Delete the activity row with id = drop_id
  4. Optionally run in dry-run mode (no DB modifications)

Usage:
  python merge_canonical_activity_pairs.py /path/to/supertl2.db /path/to/pairs.csv [--dry-run]
"""

import argparse
import csv
import sqlite3
from pathlib import Path
from typing import List, Tuple


# Tables / columns – adjust if your schema names differ
ACTIVITY_TABLE = "activity"
ACTIVITY_SOURCE_TABLE = "activity_source"
ACTIVITY_SOURCE_ACTIVITY_FK_COL = "activity_id"

TRAINING_LOG_TABLE = "TrainingLogData"      # optional; script checks existence
TRAINING_LOG_ACTIVITY_FK_COL = "canonical_activity_id"


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    )
    return cur.fetchone() is not None


def load_pairs(csv_path: Path) -> List[Tuple[int, int]]:
    pairs: List[Tuple[int, int]] = []
    with csv_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if "keep_id" not in reader.fieldnames or "drop_id" not in reader.fieldnames:
            raise SystemExit(
                f"CSV {csv_path} must have columns 'keep_id' and 'drop_id'. "
                f"Found columns: {reader.fieldnames}"
            )
        for row in reader:
            try:
                keep_id = int(row["keep_id"])
                drop_id = int(row["drop_id"])
            except (TypeError, ValueError):
                print(f"Skipping row with invalid IDs: {row}")
                continue
            if keep_id == drop_id:
                print(f"Skipping row where keep_id == drop_id ({keep_id})")
                continue
            pairs.append((keep_id, drop_id))
    return pairs


def merge_pair(
    conn: sqlite3.Connection,
    keep_id: int,
    drop_id: int,
    has_training_log: bool,
    dry_run: bool = True,
) -> None:
    """
    Merge drop_id into keep_id.

    - Move activity_source rows to keep_id
    - Move TrainingLogData rows (if table exists)
    - Delete drop_id from activity
    """
    cur = conn.cursor()

    # Simple sanity check: both IDs exist in activity
    cur.execute(f"SELECT COUNT(*) FROM {ACTIVITY_TABLE} WHERE id = ?", (keep_id,))
    keep_exists = cur.fetchone()[0] == 1
    cur.execute(f"SELECT COUNT(*) FROM {ACTIVITY_TABLE} WHERE id = ?", (drop_id,))
    drop_exists = cur.fetchone()[0] == 1

    if not keep_exists or not drop_exists:
        print(
            f"  !! Skipping pair keep={keep_id}, drop={drop_id} "
            f"(keep_exists={keep_exists}, drop_exists={drop_exists})"
        )
        return

    print(f"  Merging drop_id={drop_id} into keep_id={keep_id}...")

    if dry_run:
        # Just show what we *would* do
        cur.execute(
            f"SELECT COUNT(*) FROM {ACTIVITY_SOURCE_TABLE} "
            f"WHERE {ACTIVITY_SOURCE_ACTIVITY_FK_COL} = ?",
            (drop_id,),
        )
        src_count = cur.fetchone()[0]
        print(f"    Would move {src_count} activity_source rows from {drop_id} -> {keep_id}")

        if has_training_log:
            cur.execute(
                f"SELECT COUNT(*) FROM {TRAINING_LOG_TABLE} "
                f"WHERE {TRAINING_LOG_ACTIVITY_FK_COL} = ?",
                (drop_id,),
            )
            tl_count = cur.fetchone()[0]
            print(f"    Would move {tl_count} TrainingLogData rows from {drop_id} -> {keep_id}")

        print(f"    Would delete activity id={drop_id} from {ACTIVITY_TABLE}")
        return

    # Real merge – wrap in a transaction for each pair
    try:
        conn.execute("BEGIN")

        # 1. Move activity_source rows
        conn.execute(
            f"""
            UPDATE {ACTIVITY_SOURCE_TABLE}
            SET {ACTIVITY_SOURCE_ACTIVITY_FK_COL} = ?
            WHERE {ACTIVITY_SOURCE_ACTIVITY_FK_COL} = ?
            """,
            (keep_id, drop_id),
        )

        # 2. Move TrainingLogData rows (if present)
        if has_training_log:
            conn.execute(
                f"""
                UPDATE {TRAINING_LOG_TABLE}
                SET {TRAINING_LOG_ACTIVITY_FK_COL} = ?
                WHERE {TRAINING_LOG_ACTIVITY_FK_COL} = ?
                """,
                (keep_id, drop_id),
            )

        # 3. Delete the drop activity
        conn.execute(
            f"DELETE FROM {ACTIVITY_TABLE} WHERE id = ?",
            (drop_id,),
        )

        conn.commit()
        print("    Merge committed.")
    except Exception as e:
        conn.rollback()
        print(f"    !! Error merging pair keep={keep_id}, drop={drop_id}: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Merge confirmed canonical activity pairs."
    )
    parser.add_argument("db_path", help="Path to SQLite DB (e.g., supertl2.db)")
    parser.add_argument("pairs_csv", help="CSV with keep_id,drop_id columns")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed but do not modify the database",
    )
    args = parser.parse_args()

    db_path = Path(args.db_path)
    csv_path = Path(args.pairs_csv)

    if not db_path.exists():
        raise SystemExit(f"DB file does not exist: {db_path}")
    if not csv_path.exists():
        raise SystemExit(f"CSV file does not exist: {csv_path}")

    pairs = load_pairs(csv_path)
    if not pairs:
        raise SystemExit("No valid pairs found in CSV.")

    conn = sqlite3.connect(db_path)
    has_training_log = table_exists(conn, TRAINING_LOG_TABLE)

    print(f"Loaded {len(pairs)} pairs from {csv_path}")
    print(f"TrainingLogData table present: {has_training_log}")
    print(f"Dry run: {args.dry_run}")
    print()

    for keep_id, drop_id in pairs:
        merge_pair(conn, keep_id, drop_id, has_training_log, dry_run=args.dry_run)
        print()

    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
