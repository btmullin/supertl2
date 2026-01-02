#!/usr/bin/env python3
"""
Backfill timezone fields on canonical activity rows in supertl2.db.

Your activity schema includes:
  activity.tz_name TEXT
  activity.utc_offset_minutes INTEGER
  activity.tz_source TEXT

Backfill strategy (matches what you described):
  1) If a canonical activity has a Strava source (activity_source.source='strava'):
       - Load StravaActivity.data JSON
       - Extract IANA tz from data["timezone"] like "(GMT-06:00) America/Chicago"
       - Set tz_name=<IANA>, tz_source='strava'
       - Compute utc_offset_minutes from tz_name + activity.start_time_utc (DST-aware)
     If Strava exists but JSON is missing/unparseable timezone:
       - Fallback to assumed tz, tz_source='strava_fallback'

  2) If no Strava source row exists:
       - Set tz_name=<assumed tz>, tz_source='assumed_home'
       - Compute utc_offset_minutes from tz_name + start_time_utc

Safety / re-runs:
  - By default updates only rows where tz_name is NULL/empty.
  - Use --force to overwrite existing tz_name/offset/source.
  - Use --dry-run to preview changes.

Examples:
  Dry run:
    python backfill_activity_timezones.py ../../db/supertl2.db --dry-run

  Apply:
    python backfill_activity_timezones.py ../../db/supertl2.db

  Overwrite everything (rare):
    python backfill_activity_timezones.py ../../db/supertl2.db --force
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo
from collections import Counter


ALLOWED_TZ = {
    # US (standard)
    "America/New_York",      # Eastern
    "America/Chicago",       # Central
    "America/Denver",        # Mountain
    "America/Los_Angeles",   # Pacific
    "America/Phoenix",       # Arizona (no DST)
    "America/Anchorage",     # Alaska
    "Pacific/Honolulu",      # Hawaii

    # Allowed non-US
    "Australia/Melbourne",
}

def parse_utc_iso(s: str) -> datetime:
    """
    Parse ISO8601 UTC timestamps like:
      2025-08-29T19:24:52Z
    Also tolerates fractional seconds and explicit offsets.
    Returns an aware datetime in UTC.
    """
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def compute_offset_minutes(start_time_utc: str, tz_name: str) -> int:
    """
    Compute the UTC offset (minutes) at start_time_utc in tz_name (DST-aware).
    """
    dt_utc = parse_utc_iso(start_time_utc)
    dt_local = dt_utc.astimezone(ZoneInfo(tz_name))
    off = dt_local.utcoffset()
    if off is None:
        return 0
    return int(off.total_seconds() // 60)


def extract_iana_from_strava_timezone(tz_str: Optional[str]) -> Optional[str]:
    """
    Extract IANA tz name from Strava's timezone string.

    Common format (as in your example):
      "(GMT-06:00) America/Chicago"

    Stats-for-strava stores StravaActivity.data as JSON; after json.loads
    the string will look like "America/Chicago" (slashes unescaped).

    Returns:
      e.g. "America/Chicago" or None
    """
    if not tz_str:
        return None
    tz_str = tz_str.strip()

    # Most common: "(GMT-06:00) America/Chicago"
    if ")" in tz_str:
        tail = tz_str.split(")", 1)[1].strip()
        if "/" in tail:
            return tail

    # Sometimes already an IANA name
    if "/" in tz_str and "GMT" not in tz_str:
        return tz_str

    return None

def classify_strava_tz(tz_name: str) -> str:
    """
    Return tz_source label based on whether tz_name is in an allowlist.
    """
    return "strava" if tz_name in ALLOWED_TZ else "strava_suspect"

@dataclass
class Row:
    activity_id: int
    start_time_utc: str
    strava_activity_id: Optional[str]
    strava_data_json: Optional[str]


def ensure_columns_exist(conn: sqlite3.Connection) -> None:
    """
    Defensive: verify tz columns exist so the script fails fast with a helpful message.
    """
    cols = [r[1] for r in conn.execute("PRAGMA table_info(activity);").fetchall()]
    needed = {"tz_name", "utc_offset_minutes", "tz_source"}
    missing = sorted(list(needed - set(cols)))
    if missing:
        raise RuntimeError(
            f"activity table missing columns: {missing}. "
            "Did you run ALTER TABLE to add tz_name/utc_offset_minutes/tz_source?"
        )


def load_rows(conn: sqlite3.Connection, only_missing: bool) -> list[Row]:
    where = ""
    if only_missing:
        where = "WHERE (a.tz_name IS NULL OR trim(a.tz_name) = '')"

    sql = f"""
    SELECT
      a.id,
      a.start_time_utc,
      sas.source_activity_id AS strava_activity_id,
      sa.data AS strava_data_json
    FROM activity a
    LEFT JOIN activity_source sas
      ON sas.activity_id = a.id AND sas.source = 'strava'
    LEFT JOIN StravaActivity sa
      ON sa.activityId = sas.source_activity_id
    {where}
    ORDER BY a.id;
    """
    out: list[Row] = []
    for r in conn.execute(sql).fetchall():
        out.append(Row(r[0], r[1], r[2], r[3]))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Backfill activity timezone fields")
    ap.add_argument("db_path", help="Path to supertl2.db")
    ap.add_argument("--assumed-tz", default="America/Chicago", help="Fallback IANA tz for non-Strava activities")
    ap.add_argument("--dry-run", action="store_true", help="Preview updates without writing")
    ap.add_argument("--force", action="store_true", help="Overwrite existing tz fields (default only fills missing)")
    ap.add_argument("--limit", type=int, default=0, help="Limit number of rows processed (0=all)")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db_path)
    conn.execute("PRAGMA foreign_keys=ON;")

    ensure_columns_exist(conn)

    rows = load_rows(conn, only_missing=not args.force)

    updates: list[tuple[Optional[str], Optional[int], Optional[str], int]] = []
    skipped_no_change = 0

    for row in rows:
        tz_name: str
        tz_source: str

        if row.strava_activity_id and row.strava_data_json:
            try:
                data = json.loads(row.strava_data_json)
                tz_name_extracted = extract_iana_from_strava_timezone(data.get("timezone"))
                if tz_name_extracted:
                    tz_name = tz_name_extracted
                    tz_source = classify_strava_tz(tz_name)
                else:
                    tz_name = args.assumed_tz
                    tz_source = "strava_fallback"
            except Exception:
                tz_name = args.assumed_tz
                tz_source = "strava_bad_json"
        else:
            tz_name = args.assumed_tz
            tz_source = "assumed_home"

        # Compute DST-aware offset
        offset_min: Optional[int]
        try:
            offset_min = compute_offset_minutes(row.start_time_utc, tz_name)
        except Exception:
            # Keep tz_name/source but leave offset NULL if ZoneInfo fails
            offset_min = None

        updates.append((tz_name, offset_min, tz_source, row.activity_id))

        if args.limit and len(updates) >= args.limit:
            break

    if args.dry_run:
        print(f"Would update {len(updates)} activities.")

        # --- Summary counts (dry-run) ---
        tz_counts = Counter(tz_name for tz_name, _, _, _ in updates if tz_name)
        src_counts = Counter(tz_source for _, _, tz_source, _ in updates if tz_source)

        print("\nDry-run summary: by tz_name")
        for tz, n in tz_counts.most_common():
            print(f"  {tz}: {n}")

        print("\nDry-run summary: by tz_source")
        for src, n in src_counts.most_common():
            print(f"  {src}: {n}")

        # --- Sample of individual updates ---
        print("\nSample updates:")
        for tz_name, offset_min, tz_source, activity_id in updates[:50]:
            print(f"  id={activity_id}: tz_name={tz_name}, utc_offset_minutes={offset_min}, tz_source={tz_source}")
        if len(updates) > 50:
            print(f"  ... ({len(updates) - 50} more)")
        return

    with conn:
        conn.executemany(
            """
            UPDATE activity
               SET tz_name = ?,
                   utc_offset_minutes = ?,
                   tz_source = ?
             WHERE id = ?;
            """,
            updates,
        )

    print(f"Updated {len(updates)} activities.")

    # Sanity summary
    print("\nBreakdown by tz_source:")
    for tz_source, n in conn.execute(
        """
        SELECT COALESCE(tz_source,'<NULL>') AS tz_source, COUNT(*) AS n
        FROM activity
        GROUP BY COALESCE(tz_source,'<NULL>')
        ORDER BY n DESC;
        """
    ).fetchall():
        print(f"  {tz_source}: {n}")

    missing = conn.execute(
        "SELECT COUNT(*) FROM activity WHERE tz_name IS NULL OR trim(tz_name)='';"
    ).fetchone()[0]
    print(f"\nMissing tz_name after run: {missing}")


if __name__ == "__main__":
    main()
