#!/usr/bin/env python3
"""
Audit activities where stored tz_name does not match timezone inferred
from Strava start_latlng.

This script is READ-ONLY. It prints suspicious activities for review.

Requirements:
  pip install timezonefinder
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from typing import Optional

from timezonefinder import TimezoneFinder


tf = TimezoneFinder()


def is_virtual_strava_activity(data: dict) -> bool:
    """
    Returns True if the Strava JSON indicates a virtual/trainer activity.
    Handles Zwift VirtualRide + VirtualRun and trainer workouts.
    """
    # Common, reliable flag
    if data.get("trainer") is True:
        return True

    # Some exports include these strings
    # Your JSON has both "type" and "sport_type"
    t = (data.get("type") or "").lower()
    st = (data.get("sport_type") or "").lower()
    at = (data.get("activity_type") or data.get("activityType") or "").lower()

    # Catch common virtual markers
    virtual_markers = {"virtualride", "virtualrun"}
    if t in virtual_markers or st in virtual_markers or at in virtual_markers:
        return True

    # Some systems label zwift explicitly
    # (device_name is often "Zwift" but not always)
    device = (data.get("device_name") or "").lower()
    if "zwift" in device:
        # Not always virtual, but practically yes for tz purposes
        return True

    return False

def infer_tz_from_latlon(lat: float, lon: float) -> Optional[str]:
    try:
        return tf.timezone_at(lat=lat, lng=lon)
    except Exception:
        return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Audit activity timezone vs GPS mismatch")
    ap.add_argument("db_path", help="Path to supertl2.db")
    ap.add_argument("--limit", type=int, default=100, help="Max rows to print")
    ap.add_argument("--only-strava", action="store_true",
                    help="Only check activities with Strava sources")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db_path)
    conn.row_factory = sqlite3.Row

    sql = """
    SELECT
      a.id                AS activity_id,
      a.start_time_utc,
      a.tz_name,
      a.tz_source,
      sa.data             AS strava_data_json
    FROM activity a
    JOIN activity_source s
      ON s.activity_id = a.id AND s.source = 'strava'
    JOIN StravaActivity sa
      ON sa.activityId = s.source_activity_id
    WHERE a.tz_name IS NOT NULL
    ORDER BY a.id;
    """

    rows = conn.execute(sql).fetchall()

    mismatches = []

    for r in rows:
        try:
            data = json.loads(r["strava_data_json"])
        except Exception:
            continue

        # Skip virtual / trainer activities (Zwift, VirtualRide, VirtualRun)
        if is_virtual_strava_activity(data):
            continue

        if data.get("trainer") is True:
            continue
        # optionally also skip if marked virtual
        if data.get("workout_type") == "VirtualRide" or data.get("type") in ("VirtualRide",):
            continue

        start_latlng = data.get("start_latlng")
        if not start_latlng or len(start_latlng) != 2:
            continue

        lat, lon = start_latlng
        inferred_tz = infer_tz_from_latlon(lat, lon)
        if inferred_tz is None:
            continue

        stored_tz = r["tz_name"]

        if inferred_tz != stored_tz:
            mismatches.append({
                "activity_id": r["activity_id"],
                "start_time_utc": r["start_time_utc"],
                "stored_tz": stored_tz,
                "inferred_tz": inferred_tz,
                "tz_source": r["tz_source"],
                "lat": lat,
                "lon": lon,
            })

        if args.limit and len(mismatches) >= args.limit:
            break

    print(f"\nFound {len(mismatches)} timezone mismatches (showing up to {args.limit}):\n")

    for m in mismatches:
        print(
            f"id={m['activity_id']} "
            f"utc={m['start_time_utc']} "
            f"stored={m['stored_tz']} "
            f"inferred={m['inferred_tz']} "
            f"source={m['tz_source']} "
            f"lat={m['lat']:.5f} lon={m['lon']:.5f}"
        )


if __name__ == "__main__":
    main()
