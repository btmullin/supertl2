from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo


HOME_TZ = "America/Chicago"


def parse_utc_iso(s: str) -> datetime:
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
    return int(off.total_seconds() // 60) if off else 0


def extract_iana_from_strava_timezone(tz_str: Optional[str]) -> Optional[str]:
    if not tz_str:
        return None
    tz_str = tz_str.strip()

    # "(GMT-06:00) America/Chicago"
    if ")" in tz_str:
        tail = tz_str.split(")", 1)[1].strip()
        if "/" in tail:
            return tail

    # Already IANA
    if "/" in tz_str and "GMT" not in tz_str:
        return tz_str

    return None


def _str_lower(x: Optional[str]) -> str:
    return (x or "").strip().lower()


def is_no_gps_strava(data: dict) -> bool:
    """
    Heuristic: no GPS if there is no polyline AND no start lat/lng.
    Covers common Strava shapes and stats-for-strava JSON.
    """
    # Map polyline
    poly = None
    m = data.get("map")
    if isinstance(m, dict):
        poly = m.get("summary_polyline") or m.get("polyline")

    # Various lat/lng forms
    start_latlng = data.get("start_latlng")
    has_start_latlng = isinstance(start_latlng, (list, tuple)) and len(start_latlng) == 2 and all(v is not None for v in start_latlng)

    has_start_lat = data.get("start_latitude") is not None
    has_start_lng = data.get("start_longitude") is not None

    # Sometimes "has_latlng" exists
    has_latlng_flag = data.get("has_latlng")
    if has_latlng_flag is False:
        return True

    return (not poly) and (not has_start_latlng) and (not has_start_lat) and (not has_start_lng)


def is_trainer_or_virtual_or_zwift(data: dict, sport: Optional[str]) -> bool:
    """
    "Trainer" / "virtual" flags are typical in Strava API JSON.
    Zwift detection is best-effort via device/app/name strings.
    """
    if bool(data.get("trainer")):
        return True
    if bool(data.get("virtual")):
        return True

    # Some imports may use sport/type naming
    s = _str_lower(sport)
    if "virtual" in s:
        return True
    if "trainer" in s:
        return True

    device = _str_lower(data.get("device_name"))
    app = _str_lower(data.get("external_id"))  # sometimes contains app-ish IDs
    name = _str_lower(data.get("name"))

    if "zwift" in device or "zwift" in app or "zwift" in name:
        return True

    return False


def ensure_activity_tz_columns(conn: sqlite3.Connection) -> None:
    cols = [r[1] for r in conn.execute("PRAGMA table_info(activity);").fetchall()]
    needed = {"tz_name", "utc_offset_minutes", "tz_source"}
    missing = sorted(list(needed - set(cols)))
    if missing:
        raise RuntimeError(
            f"activity table missing columns: {missing}. "
            "Did you add tz_name/utc_offset_minutes/tz_source?"
        )


@dataclass
class Row:
    activity_id: int
    start_time_utc: str
    sport: Optional[str]
    strava_activity_id: Optional[str]
    strava_data_json: Optional[str]


def load_activity_rows_for_tz_backfill(conn: sqlite3.Connection, only_missing: bool) -> list[Row]:
    """
    Pull canonical activities + optional Strava JSON.

    Note: Cast Strava IDs to TEXT on joins to avoid TEXT/INTEGER mismatches.
    """
    where = ""
    if only_missing:
        where = "WHERE (a.tz_name IS NULL OR trim(a.tz_name) = '')"

    sql = f"""
    SELECT
      a.id,
      a.start_time_utc,
      a.sport,
      sas.source_activity_id AS strava_activity_id,
      sa.data AS strava_data_json
    FROM activity a
    LEFT JOIN activity_source sas
      ON sas.activity_id = a.id AND sas.source = 'strava'
    LEFT JOIN StravaActivity sa
      ON CAST(sa.activityId AS TEXT) = sas.source_activity_id
    {where}
    ORDER BY a.id;
    """
    out: list[Row] = []
    for r in conn.execute(sql).fetchall():
        out.append(Row(r[0], r[1], r[2], r[3], r[4]))
    return out


def backfill_activity_timezones(
    db_path: str,
    assumed_tz: str = HOME_TZ,
    force: bool = False,
    dry_run: bool = False,
    limit: int = 0,
) -> dict:
    """
    Call after your Strava->canonical backfill to populate activity.tz_* fields.

    Rule additions:
      - If Strava JSON indicates (no GPS) AND (trainer or virtual or zwift),
        force tz to assumed_tz (default America/Chicago), tz_source='manual_home_no_gps'
    """
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.row_factory = sqlite3.Row

    ensure_activity_tz_columns(conn)

    rows = load_activity_rows_for_tz_backfill(conn, only_missing=not force)

    updates: list[tuple[Optional[str], Optional[int], Optional[str], int]] = []
    for row in rows:
        tz_name: str
        tz_source: str
        offset_min: Optional[int] = None

        data = None
        if row.strava_activity_id and row.strava_data_json:
            try:
                data = json.loads(row.strava_data_json)
            except Exception:
                data = None

        # --- New override rule ---
        if isinstance(data, dict) and is_no_gps_strava(data) and is_trainer_or_virtual_or_zwift(data, row.sport):
            tz_name = assumed_tz
            tz_source = "manual_home_no_gps"
        else:
            # Normal strategy: try Strava tz first, else fallback
            if isinstance(data, dict):
                tz_name_extracted = extract_iana_from_strava_timezone(data.get("timezone"))
                if tz_name_extracted:
                    tz_name = tz_name_extracted
                    tz_source = "strava"
                else:
                    tz_name = assumed_tz
                    tz_source = "strava_fallback"
            else:
                tz_name = assumed_tz
                tz_source = "assumed_home"

        # Compute offset
        try:
            offset_min = compute_offset_minutes(row.start_time_utc, tz_name)
        except Exception:
            offset_min = None  # leave NULL if ZoneInfo fails

        updates.append((tz_name, offset_min, tz_source, row.activity_id))

        if limit and len(updates) >= limit:
            break

    if dry_run:
        conn.close()
        return {
            "mode": "dry-run",
            "would_update": len(updates),
            "sample": updates[:25],
        }

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

    conn.close()
    return {
        "mode": "apply",
        "updated": len(updates),
    }
