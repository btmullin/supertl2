#!/usr/bin/env python3
"""
One-time SportTracks import:
- Read activity IDs from ids.txt
- Login once with Playwright
- For each ID: scrape JSON from /activity/{id}, download TCX, upsert into sporttracks.db

Usage examples:
  python import_sporttracks.py --email you@example.com --password 'secret'
  SPORTTRACKS_EMAIL=you@example.com SPORTTRACKS_PASSWORD=secret python import_sporttracks.py --headful
"""

import argparse
import os
import re
import sys
import json
import time
import sqlite3
import requests
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from datetime import datetime

BASE = "https://sporttracks.mobi"

# ---------------------------
# Helpers
# ---------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="One-time SportTracks import to SQLite + TCX download")
    p.add_argument("--email", default=os.getenv("SPORTTRACKS_EMAIL"), help="Login (or set SPORTTRACKS_EMAIL)")
    p.add_argument("--password", default=os.getenv("SPORTTRACKS_PASSWORD"), help="Password (or set SPORTTRACKS_PASSWORD)")
    p.add_argument("--ids", default="ids.txt", help="Path to ids.txt (one activity id per line)")
    p.add_argument("--db", default="sporttracks.db", help="SQLite DB path (default: sporttracks.db)")
    p.add_argument("--outdir", default="st_tcx", help="TCX download directory (default: st_tcx)")
    p.add_argument("--rate", type=float, default=0.2, help="Seconds to sleep between activities (default: 0.2)")
    p.add_argument("--headful", action="store_true", help="Run browser visible (default headless)")
    p.add_argument("--max", type=int, default=0, help="Max activities to process (0 = all)")
    return p.parse_args()

def fail_if_missing_creds(email: Optional[str], password: Optional[str]) -> Tuple[str, str]:
    if not email or not password:
        print("ERROR: provide credentials via --email/--password or SPORTTRACKS_EMAIL/SPORTTRACKS_PASSWORD.", file=sys.stderr)
        sys.exit(2)
    return email, password

def read_ids(path: str) -> List[str]:
    ids: List[str] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s and s.isdigit():
                ids.append(s)
    # de-dup, numeric-sort
    ids = sorted(set(ids), key=lambda x: int(x))
    return ids

def ensure_table(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS sporttracks_activity_staging (
      activity_id       TEXT PRIMARY KEY,
      start_date        TEXT,
      start_time        TEXT,
      distance_m        REAL,
      duration_s        REAL,
      avg_pace_s_per_km REAL,
      elev_gain_m       REAL,
      avg_heartrate_bpm REAL,
      avg_power_w       REAL,
      calories_kcal     REAL,
      category          TEXT,
      notes             TEXT,
      has_tcx           INTEGER NOT NULL DEFAULT 0 CHECK (has_tcx IN (0,1))
    );
    """)
    conn.commit()

def upsert_row(conn: sqlite3.Connection, row: Dict[str, Any]) -> None:
    cols = ["activity_id","start_date","start_time","distance_m","duration_s",
            "avg_pace_s_per_km","elev_gain_m","avg_heartrate_bpm","avg_power_w",
            "calories_kcal","category","notes","has_tcx"]
    placeholders = ",".join("?" for _ in cols)
    sql = f"""
    INSERT INTO sporttracks_activity_staging ({",".join(cols)})
    VALUES ({placeholders})
    ON CONFLICT(activity_id) DO UPDATE SET
      start_date=excluded.start_date,
      start_time=excluded.start_time,
      distance_m=excluded.distance_m,
      duration_s=excluded.duration_s,
      avg_pace_s_per_km=excluded.avg_pace_s_per_km,
      elev_gain_m=excluded.elev_gain_m,
      avg_heartrate_bpm=excluded.avg_heartrate_bpm,
      avg_power_w=excluded.avg_power_w,
      calories_kcal=excluded.calories_kcal,
      category=excluded.category,
      notes=excluded.notes,
      has_tcx=excluded.has_tcx;
    """
    vals = [row.get(c) for c in cols]
    conn.execute(sql, vals)

def commit(conn: sqlite3.Connection) -> None:
    conn.commit()

def nget(d: Dict[str, Any], *paths, default=None):
    """Try multiple key paths like ('workout','distance') and return the first that exists."""
    for path in paths:
        cur: Any = d
        ok = True
        for k in path:
            if isinstance(cur, dict) and k in cur:
                cur = cur[k]
            else:
                ok = False
                break
        if ok:
            return cur
    return default

def search_key(d: Any, key: str):
    """Depth-first search for a key anywhere in nested dict/list."""
    stack = [d]
    while stack:
        v = stack.pop()
        if isinstance(v, dict):
            for k, val in v.items():
                if k == key:
                    return val
                stack.append(val)
        elif isinstance(v, list):
            stack.extend(v)
    return None

def iso_to_local_date_time(iso: str) -> Tuple[Optional[str], Optional[str]]:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M:%S")
    except Exception:
        return None, None

def compute_pace_s_per_km(distance_m: Optional[float], duration_s: Optional[float], fallback: Optional[float]) -> Optional[float]:
    if distance_m and duration_s and distance_m > 0 and duration_s > 0:
        return duration_s / (distance_m / 1000.0)
    return fallback

def coerce_float(x: Any) -> Optional[float]:
    if x is None: return None
    try:
        return float(x)
    except Exception:
        return None

def extract_fields_from_state(st: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize fields from the embedded JSON (be liberal with key paths).
    All numeric units are metric: meters, seconds, watts, kcal.
    """
    # Core numeric
    distance_m = coerce_float(nget(st, ("workout","distance"), ("activity","distance"), ("workoutSummary","distance"), ("distance",)))
    duration_s = coerce_float(nget(st, ("workout","time"), ("activity","time"), ("workoutSummary","time"), ("time",)))
    elev_gain_m = coerce_float(nget(st, ("workout","elevGain"), ("activity","elevGain"), ("workoutSummary","elevGain"), ("elevGain",)))
    avg_hr = coerce_float(nget(st, ("workout","avgHeartrate"), ("activity","avgHeartrate"), ("workoutSummary","avgHeartrate"), ("avgHeartrate",)))
    avg_power = coerce_float(nget(st, ("workout","avgPower"), ("activity","avgPower"), ("workoutSummary","avgPower"), ("avgPower",)))
    calories = coerce_float(nget(st, ("workout","calories"), ("activity","calories"), ("workoutSummary","calories"), ("calories",)))

    # Pace: prefer numeric seconds; otherwise compute
    pace_val = nget(st, ("workout","avgPace"), ("activity","avgPace"), ("workoutSummary","avgPace"), ("avgPace",))
    pace_s_per_km = None
    # If avgPace looks numeric (already seconds/km), use it; else compute
    if isinstance(pace_val, (int, float)):
        pace_s_per_km = float(pace_val)
    else:
        pace_s_per_km = compute_pace_s_per_km(distance_m, duration_s, None)

    # Category, Notes
    category = nget(st, ("workout","categoryName"), ("activity","categoryName"), ("workoutSummary","categoryName"), ("categoryName",))
    if category is None:
        # sometimes nested object
        category = nget(st, ("workout","category","name"), ("activity","category","name"), ("workoutSummary","category","name"))
    notes = nget(st, ("workout","notes"), ("activity","notes"), ("workoutSummary","notes"), ("notes",))

    # Start date/time
    start_date = nget(st, ("workout","startDate"), ("activity","startDate"), ("workoutSummary","startDate"), ("startDate",))
    start_time = nget(st, ("workout","startTime"), ("activity","startTime"), ("workoutSummary","startTime"), ("startTime",))
    if not (start_date and start_time):
        # try an ISO "start"
        start_iso = nget(st, ("workout","start"), ("activity","start"), ("workoutSummary","start"), ("start",))
        if isinstance(start_iso, str):
            d, t = iso_to_local_date_time(start_iso)
            start_date = start_date or d
            start_time = start_time or t

    return {
        "start_date": start_date,
        "start_time": start_time,
        "distance_m": distance_m,
        "duration_s": duration_s,
        "avg_pace_s_per_km": pace_s_per_km,
        "elev_gain_m": elev_gain_m,
        "avg_heartrate_bpm": avg_hr,
        "avg_power_w": avg_power,
        "calories_kcal": calories,
        "category": category,
        "notes": notes,
    }

def tcx_download(session: requests.Session, aid: str, outdir: Path) -> bool:
    outdir.mkdir(parents=True, exist_ok=True)
    url = f"{BASE}/activity/{aid}/export?type=tcx"
    path = outdir / f"{aid}.tcx"
    r = session.get(url, timeout=60)
    if r.ok and r.content.strip().startswith(b"<?xml"):
        path.write_bytes(r.content)
        return True
    # save error for diagnostics
    (outdir / f"{aid}.error.html").write_bytes(r.content)
    return False

# ---------------------------
# Main
# ---------------------------

def main() -> None:
    args = parse_args()
    email, password = fail_if_missing_creds(args.email, args.password)
    ids = read_ids(args.ids)
    if args.max:
        ids = ids[:args.max]

    # DB setup
    conn = sqlite3.connect(args.db)
    ensure_table(conn)

    # Login once
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError  # type: ignore
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headful)
        ctx = browser.new_context()
        page = ctx.new_page()

        page.goto(f"{BASE}/user/login", wait_until="load")
        page.fill('input[name="name"]', email)
        page.fill('input[name="pass"]', password)
        try:
            page.click('button:has-text("Log in"), input[type="submit"][value*="Log in"]', timeout=2000)
        except PWTimeoutError:
            page.keyboard.press("Enter")
        page.wait_for_load_state("networkidle")

        # Build a requests session with the same cookies
        s = requests.Session()
        for c in ctx.cookies():
            # scope to site
            s.cookies.set(c["name"], c["value"], domain="sporttracks.mobi")

        outdir = Path(args.outdir)
        processed = 0
        ok_rows = 0
        tcx_ok = 0

        for aid in ids:
            processed += 1
            url = f"{BASE}/activity/{aid}"
            # Load activity page
            try:
                page.goto(url, wait_until="networkidle")
            except Exception:
                page.goto(url)
                page.wait_for_timeout(1500)

            # Try to get embedded JSON
            state: Optional[Dict[str, Any]] = None
            for js in ("() => window.SportTracks || null",
                       "() => (window.Drupal && Drupal.settings) || null"):
                try:
                    state = page.evaluate(js)
                except Exception:
                    state = None
                if isinstance(state, dict):
                    break

            if not isinstance(state, dict):
                print(f"[warn] {aid}: no embedded JSON detected; skipping insert but will try TCX.")
                fields = {k: None for k in ("start_date","start_time","distance_m","duration_s","avg_pace_s_per_km",
                                            "elev_gain_m","avg_heartrate_bpm","avg_power_w","calories_kcal","category","notes")}
            else:
                fields = extract_fields_from_state(state)

            # Download TCX
            has_tcx = tcx_download(s, aid, outdir)
            if has_tcx:
                tcx_ok += 1

            # Upsert row
            row = {
                "activity_id": aid,
                **fields,
                "has_tcx": 1 if has_tcx else 0,
            }
            try:
                upsert_row(conn, row)
                ok_rows += 1
            except Exception as e:
                print(f"[error] {aid}: DB upsert failed: {e}")

            # polite delay
            time.sleep(max(0.0, args.rate))

            if processed % 25 == 0:
                commit(conn)
                print(f"[info] processed {processed}/{len(ids)} (rows {ok_rows}, tcx {tcx_ok})")

        commit(conn)
        browser.close()

    print(f"[done] processed={processed}, inserted/updated rows={ok_rows}, tcx_downloaded={tcx_ok} → DB: {args.db}, TCX dir: {args.outdir}")

if __name__ == "__main__":
    main()
