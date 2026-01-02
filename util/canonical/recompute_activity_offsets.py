#!/usr/bin/env python3
"""
Recompute activity.utc_offset_minutes from activity.start_time_utc + activity.tz_name.

Why: SQLite can't do DST-aware timezone offsets correctly; Python zoneinfo can.

By default, updates rows where:
  - tz_name is not null/blank, AND
  - utc_offset_minutes is NULL

Options:
  --where "..."   Apply any additional SQL condition (without the WHERE keyword)
  --force         Recompute for all rows that match filters (even if offset already set)
  --dry-run       Print changes but do not update
  --limit N       Limit rows processed (0 = all)

Examples:
  Dry run for only "assumed_home_no_gps" rows:
    python recompute_activity_offsets.py path/to/supertl2.db --dry-run --where "tz_source='assumed_home_no_gps'"

  Apply for all rows with tz_name set (force recompute):
    python recompute_activity_offsets.py path/to/supertl2.db --force

  Apply only for a specific tz_name:
    python recompute_activity_offsets.py path/to/supertl2.db --where "tz_name='America/Chicago'"
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def parse_utc_iso(s: str) -> datetime:
    """
    Parse ISO8601 like 2025-08-29T19:24:52Z (or with +00:00).
    Returns aware datetime in UTC.
    """
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def compute_offset_minutes(start_time_utc: str, tz_name: str) -> int:
    dt_utc = parse_utc_iso(start_time_utc)
    dt_local = dt_utc.astimezone(ZoneInfo(tz_name))
    off = dt_local.utcoffset()
    if off is None:
        return 0
    return int(off.total_seconds() // 60)


def main() -> None:
    ap = argparse.ArgumentParser(description="Recompute utc_offset_minutes for activities")
    ap.add_argument("db_path", help="Path to supertl2.db")
    ap.add_argument("--where", default="", help="Additional SQL condition (without 'WHERE')")
    ap.add_argument("--force", action="store_true", help="Recompute even if utc_offset_minutes already set")
    ap.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    ap.add_argument("--limit", type=int, default=0, help="Limit rows processed (0=all)")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db_path)
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.row_factory = sqlite3.Row

    base_cond = [
        "tz_name IS NOT NULL",
        "trim(tz_name) <> ''",
    ]
    if not args.force:
        base_cond.append("utc_offset_minutes IS NULL")

    if args.where.strip():
        base_cond.append(f"({args.where.strip()})")

    where_sql = " AND ".join(base_cond)

    print(f"Applying to rows where: {where_sql}")

    sql = f"""
    SELECT id, start_time_utc, tz_name, utc_offset_minutes
    FROM activity
    WHERE {where_sql}
    ORDER BY id
    """

    rows = conn.execute(sql).fetchall()

    updates = []
    errors = 0

    for r in rows:
        try:
            new_off = compute_offset_minutes(r["start_time_utc"], r["tz_name"])
        except Exception:
            errors += 1
            continue

        old_off = r["utc_offset_minutes"]
        if (old_off is None) or (int(old_off) != int(new_off)) or args.force:
            updates.append((new_off, r["id"], old_off, r["tz_name"], r["start_time_utc"]))

        if args.limit and len(updates) >= args.limit:
            break

    print(f"Matched rows: {len(rows)}")
    print(f"Would update: {len(updates)}")
    if errors:
        print(f"Skipped due to errors: {errors}")

    if args.dry_run:
        print("\nSample changes:")
        for new_off, aid, old_off, tz_name, start_utc in updates[:50]:
            print(f"  id={aid} tz={tz_name} start_utc={start_utc} offset {old_off} -> {new_off}")
        if len(updates) > 50:
            print(f"  ... ({len(updates)-50} more)")
        return

    with conn:
        conn.executemany(
            "UPDATE activity SET utc_offset_minutes = ? WHERE id = ?",
            [(new_off, aid) for (new_off, aid, *_rest) in updates],
        )

    print("Done.")


if __name__ == "__main__":
    main()
