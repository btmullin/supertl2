#!/usr/bin/env python3
from __future__ import annotations
import argparse
import hashlib
import re
import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

# ---------- helpers ----------

def ensure_activity_source_has_local(conn: sqlite3.Connection) -> None:
    cols = {c[1] for c in conn.execute("PRAGMA table_info(activity_source)")}
    if "start_time_local" not in cols:
        conn.execute("ALTER TABLE activity_source ADD COLUMN start_time_local TEXT")

def _try_strptime(s: str, fmts: list[str]) -> datetime | None:
    for fmt in fmts:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None

def _expand_mdy_ampm(s: str) -> str:
    """
    Normalize things like '7/4/21 1:05 PM' -> '07/04/2021 01:05 PM'
    and '7/4/2021 1:05 PM' -> '07/04/2021 01:05 PM'.
    """
    s = s.strip()
    # Split date/time on space before AM/PM
    m = re.match(r"^\s*(\d{1,2})/(\d{1,2})/(\d{2,4})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(AM|PM))?\s*$", s, re.I)
    if not m:
        return s
    mm, dd, yy, hh, mi, ss, ampm = m.groups()
    mm = f"{int(mm):02d}"
    dd = f"{int(dd):02d}"
    # Expand 2-digit year to 20xx (tweak if you have 1900s data)
    if len(yy) == 2:
        yy = f"20{yy}"
    if hh is None:
        # date only
        return f"{mm}/{dd}/{yy}"
    hh = f"{int(hh):02d}"
    mi = f"{int(mi):02d}"
    ss = f"{int(ss):02d}" if ss else None
    core = f"{mm}/{dd}/{yy} {hh}:{mi}"
    if ss:
        core += f":{ss}"
    return f"{core} {ampm.upper()}"

def parse_st_local_to_local_and_utc(date_s: str | None, time_s: str | None, tz: ZoneInfo) -> tuple[str, str]:
    """
    Accepts either:
      - date_s='YYYY-MM-DD', time_s='HH:MM[:SS]'
      - date_s='M/D/YY HH:MM [AM|PM]' (time_s empty/None)
      - date_s='M/D/YYYY HH:MM [AM|PM]' (time_s empty/None)
      - date_s='YYYY-MM-DDTHH:MM[:SS]' (time_s empty/None)
      - date_s='YYYY-MM-DD' (time_s empty/None) -> assumes 00:00:00
    Returns (local_iso_noZ, utc_iso_Z).
    """
    ds = (date_s or "").strip()
    ts = (time_s or "").strip()

    if ds and ts:
        combo = f"{ds} {ts}"
    else:
        combo = ds

    combo = combo.strip()
    # Fast paths for ISO-ish formats
    # 1) ISO with T
    dt = _try_strptime(combo, ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"])
    if dt:
        aware = dt.replace(tzinfo=tz)
        utc = aware.astimezone(timezone.utc)
        return aware.strftime("%Y-%m-%dT%H:%M:%S"), utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    # 2) ISO with space
    dt = _try_strptime(combo, ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"])
    if dt:
        aware = dt.replace(tzinfo=tz)
        utc = aware.astimezone(timezone.utc)
        return aware.strftime("%Y-%m-%dT%H:%M:%S"), utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    # 3) MDY AM/PM variants
    norm = _expand_mdy_ampm(combo)
    dt = _try_strptime(norm, ["%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %I:%M %p"])
    if dt:
        aware = dt.replace(tzinfo=tz)
        utc = aware.astimezone(timezone.utc)
        return aware.strftime("%Y-%m-%dT%H:%M:%S"), utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    # 4) Date-only
    dt = _try_strptime(combo, ["%Y-%m-%d"])
    if dt:
        aware = dt.replace(tzinfo=tz)
        utc = aware.astimezone(timezone.utc)
        return aware.strftime("%Y-%m-%dT%H:%M:%S"), utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    # 5) MDY date-only
    norm = _expand_mdy_ampm(combo)
    dt = _try_strptime(norm, ["%m/%d/%Y"])
    if dt:
        aware = dt.replace(tzinfo=tz)
        utc = aware.astimezone(timezone.utc)
        return aware.strftime("%Y-%m-%dT%H:%M:%S"), utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    raise ValueError(f"Unrecognized datetime: {combo!r}")

def rel_close(a: float | None, b: float | None, tol: float) -> bool:
    if a is None or b is None or a == 0 or b == 0:
        return False
    return abs(a - b) / max(a, b) <= tol

def parse_float(x):
    if x is None:
        return None
    try:
        return float(x)
    except Exception:
        return None

def parse_int(x):
    if x is None:
        return None
    try:
        return int(float(x))
    except Exception:
        return None

def parse_utc_z(s: str) -> datetime:
    # s like 'YYYY-MM-DDTHH:MM:SSZ'
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")

def find_candidate(conn: sqlite3.Connection, utc_iso: str,
                   sport: str | None, distance_m: float | None, duration_s: float | None):
    cur = conn.execute(
        """
        SELECT id, start_time_utc, distance_m, elapsed_time_s, sport
        FROM activity
        WHERE start_time_utc BETWEEN datetime(?, '-15 minutes') AND datetime(?, '+15 minutes')
        ORDER BY ABS(strftime('%s', start_time_utc) - strftime('%s', ?)) ASC
        """,
        (utc_iso, utc_iso, utc_iso),
    )
    rows = cur.fetchall()
    if not rows:
        return None, None

    utc_target = parse_utc_z(utc_iso)

    # Tier A: ±5 min + metrics within 10%
    for (aid, s_utc, dist, dur, sp) in rows:
        dt_sec = abs((parse_utc_z(s_utc) - utc_target).total_seconds())
        if dt_sec <= 5 * 60 and (rel_close(dist, distance_m, 0.10) or rel_close(dur, duration_s, 0.10)):
            return aid, "A"

    # Tier B: ±15 min + metrics within 15%
    for (aid, s_utc, dist, dur, sp) in rows:
        dt_sec = abs((parse_utc_z(s_utc) - utc_target).total_seconds())
        if dt_sec <= 15 * 60 and (rel_close(dist, distance_m, 0.15) or rel_close(dur, duration_s, 0.15)):
            return aid, "B"

    return None, None

# ---------- main ----------

def main():
    ap = argparse.ArgumentParser(description="Backfill SportTracks into canonical activity/activity_source (local+UTC, robust datetime parsing).")
    ap.add_argument("--db", default="db/supertl2.db", help="Path to supertl2.db (canonical lives here)")
    ap.add_argument("--local-tz", default="America/Chicago", help="IANA tz name of SportTracks local times")
    args = ap.parse_args()

    # tz setup (fallback alias for Windows without tzdata)
    try:
        tz = ZoneInfo(args.local_tz)
    except Exception:
        tz = ZoneInfo("US/Central")

    dbp = Path(args.db)
    if not dbp.exists():
        raise SystemExit(f"DB not found: {dbp}")

    with sqlite3.connect(dbp.as_posix()) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")
        ensure_activity_source_has_local(conn)

        cur = conn.execute(
            """
            SELECT s.activity_id,
                   s.start_date,
                   s.start_time,
                   s.distance_m,
                   s.duration_s,
                   s.category,
                   s.notes
            FROM sporttracks_activity s
            LEFT JOIN activity_source asrc
              ON asrc.source='sporttracks' AND asrc.source_activity_id = s.activity_id
            WHERE asrc.id IS NULL
            ORDER BY s.start_date, s.start_time
            """
        )
        rows = cur.fetchall()

        created_activity = 0
        created_source = 0
        linked_existing = 0
        skipped_bad_dt = 0

        for (st_id, start_date, start_time, dist, dur, category, notes) in rows:
            try:
                start_local, start_utc = parse_st_local_to_local_and_utc(start_date, start_time, tz)
            except Exception as e:
                skipped_bad_dt += 1
                print(f"Skip ST {st_id}: bad date/time ({start_date} {start_time}) -> {e}")
                continue

            dist_f = parse_float(dist)
            dur_i = parse_int(dur)
            sport = category or None  # you can later map categories -> normalized sport
            name = (notes or "").strip() or (category or "SportTracks activity")

            # Try to match existing canonical
            aid, tier = find_candidate(conn, start_utc, sport, dist_f, dur_i)
            if aid is None:
                # Create new canonical activity
                c = conn.execute(
                    """
                    INSERT INTO activity (
                        start_time_utc, end_time_utc, elapsed_time_s, moving_time_s,
                        distance_m, name, sport
                    )
                    VALUES (?, NULL, ?, ?, ?, ?, ?)
                    """,
                    (start_utc, dur_i, dur_i, dist_f, name, sport),
                )
                aid = c.lastrowid
                created_activity += 1
                tier = "A"
            else:
                linked_existing += 1

            # Link the source with both timestamps
            payload = f"{st_id}|{start_local}|{start_utc}|{sport}|{name}|{dist_f}|{dur_i}".encode("utf-8")
            payload_hash = hashlib.sha256(payload).hexdigest()

            conn.execute(
                """
                INSERT INTO activity_source (
                  activity_id, source, source_activity_id,
                  start_time_local, start_time_utc,
                  elapsed_time_s, distance_m, sport,
                  payload_hash, match_confidence
                ) VALUES (?, 'sporttracks', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (aid, st_id, start_local, start_utc, dur_i, dist_f, sport, payload_hash, tier),
            )
            created_source += 1

        print({
            "processed": len(rows),
            "created_activity": created_activity,
            "created_source": created_source,
            "linked_existing": linked_existing,
            "skipped_bad_datetime": skipped_bad_dt,
        })

if __name__ == "__main__":
    main()
