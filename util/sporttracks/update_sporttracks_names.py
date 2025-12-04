#!/usr/bin/env python3
"""
update_sporttracks_names.py

Log into sporttracks.mobi, loop over all SportTracks activities that already
exist in the sporttracks_activity table in supertl2.db, fetch the activity
page JSON ("SportTracks = {...}") and update the `name` column for each row.

Usage example:

    export ST_EMAIL="you@example.com"
    export ST_PASSWORD="yourpassword"

    python update_sporttracks_names.py \
        --db path/to/supertl2.db

By default this only touches rows where `name IS NULL`. Use --include-existing
if you want to overwrite non-NULL names as well.
"""

import argparse
import json
import os
import sqlite3
import sys
import time
from typing import Any, Dict

BASE = "https://sporttracks.mobi"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--db", required=True, help="Path to supertl2.db")
    p.add_argument(
        "--email",
        help="SportTracks login email (or set ST_EMAIL env var)",
    )
    p.add_argument(
        "--password",
        help="SportTracks login password (or set ST_PASSWORD env var)",
    )
    p.add_argument(
        "--headful",
        action="store_true",
        help="Run browser non-headless (for debugging)",
    )
    p.add_argument(
        "--rate",
        type=float,
        default=1.0,
        help="Seconds to sleep between page loads (politeness delay)",
    )
    p.add_argument(
        "--include-existing",
        action="store_true",
        help="Also update rows where name is already non-NULL",
    )
    return p.parse_args()


def get_credentials(args: argparse.Namespace) -> tuple[str, str]:
    email = args.email or os.environ.get("ST_EMAIL")
    password = args.password or os.environ.get("ST_PASSWORD")
    if not email or not password:
        print(
            "You must provide SportTracks credentials via "
            "--email/--password or ST_EMAIL/ST_PASSWORD env vars.",
            file=sys.stderr,
        )
        sys.exit(1)
    return email, password


def fetch_activity_ids(conn: sqlite3.Connection, include_existing: bool) -> list[str]:
    cur = conn.cursor()
    if include_existing:
        cur.execute(
            "SELECT activity_id FROM sporttracks_activity ORDER BY activity_id"
        )
    else:
        cur.execute(
            "SELECT activity_id FROM sporttracks_activity "
            "WHERE name IS NULL ORDER BY activity_id"
        )
    rows = [r[0] for r in cur.fetchall()]
    cur.close()
    return rows


def extract_state_json(html: str) -> Dict[str, Any]:
    """
    Pull out the SportTracks = {...}; JSON blob from the HTML using
    simple brace-matching.
    """
    marker = "SportTracks="
    idx = html.find(marker)
    if idx == -1:
        raise ValueError("SportTracks= JSON blob not found in activity page")

    # Find the first '{' after the marker
    start = html.find("{", idx)
    if start == -1:
        raise ValueError("Could not find opening '{' for SportTracks JSON")

    depth = 0
    end = None
    for i, ch in enumerate(html[start:], start=start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    if end is None:
        raise ValueError("Failed to find matching '}' for SportTracks JSON")

    json_str = html[start:end]
    return json.loads(json_str)


def extract_name_from_state(state: Dict[str, Any]) -> str | None:
    """
    Try a couple of likely places for the activity name.
    """
    activity = state.get("activity") or {}
    name = activity.get("name")
    if name:
        return str(name).strip()

    workout = state.get("workout") or {}
    name = workout.get("name")
    if name:
        return str(name).strip()

    return None


def main() -> None:
    args = parse_args()
    email, password = get_credentials(args)

    conn = sqlite3.connect(args.db)

    # Make sure the table and column are present (we won't create the table).
    try:
        conn.execute("SELECT name FROM sporttracks_activity LIMIT 1")
    except sqlite3.OperationalError:
        print(
            "Error: sporttracks_activity.name column not found. "
            "Run this first inside sqlite3:\n"
            "    ALTER TABLE sporttracks_activity ADD COLUMN name TEXT;",
            file=sys.stderr,
        )
        raise

    ids = fetch_activity_ids(conn, include_existing=args.include_existing)
    if not ids:
        print("No sporttracks_activity rows found needing a name update.")
        return

    print(f"Will process {len(ids)} activities")

    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError  # type: ignore

    processed = 0
    updated = 0
    skipped = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headful)
        ctx = browser.new_context()
        page = ctx.new_page()

        # Login once
        print("Logging into SportTracks…")
        page.goto(f"{BASE}/user/login", wait_until="load")
        page.fill('input[name="name"]', email)
        page.fill('input[name="pass"]', password)
        page.click('input[type="submit"]')
        # Give it a moment and sanity-check that we're logged in
        page.wait_for_timeout(2000)

        for aid in ids:
            processed += 1
            url = f"{BASE}/activity/{aid}"
            try:
                page.goto(url, wait_until="load")
                # Small delay to ensure the script tag is present
                page.wait_for_timeout(1000)
                html = page.content()
                state = extract_state_json(html)
                name = extract_name_from_state(state)

                if not name:
                    print(f"[warn] {aid}: no name found in JSON; skipping")
                    skipped += 1
                    continue

                try:
                    conn.execute(
                        "UPDATE sporttracks_activity SET name = ? WHERE activity_id = ?",
                        (name, aid),
                    )
                    updated += 1
                except sqlite3.Error as db_err:
                    print(f"[error] {aid}: failed to update DB: {db_err}")
                    skipped += 1

            except PWTimeoutError:
                print(f"[timeout] {aid}: page load timed out")
                skipped += 1
            except Exception as e:
                print(f"[error] {aid}: unexpected error {e}")
                skipped += 1

            if processed % 25 == 0:
                conn.commit()
                print(
                    f"[info] processed {processed}/{len(ids)}; "
                    f"updated={updated}, skipped={skipped}"
                )

            # Polite delay between requests
            time.sleep(max(0.0, args.rate))

        conn.commit()
        browser.close()

    print(
        f"[done] processed={processed}, updated={updated}, skipped={skipped} "
        f"→ DB: {args.db}"
    )


if __name__ == "__main__":
    main()
