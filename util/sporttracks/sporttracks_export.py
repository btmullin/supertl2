#!/usr/bin/env python3
"""
Export SportTracks.mobi activities (TCX) using a real login session.

Credentials:
- CLI flags: --email and --password
- or env vars: SPORTTRACKS_EMAIL, SPORTTRACKS_PASSWORD
- otherwise you'll be prompted (password hidden)

Usage examples:
  python sporttracks_export.py --outdir st_tcx
  python sporttracks_export.py --email you@example.com --outdir st_tcx --max 200
  SPORTTRACKS_EMAIL=you@example.com SPORTTRACKS_PASSWORD=secret \
    python sporttracks_export.py --headful
"""

import argparse
import os
import re
import sys
import time
import getpass
from typing import Dict, Iterable, List, Set, Tuple

import requests

try:
    # Optional: support .env without making it a hard dependency
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass

BASE = "https://sporttracks.mobi"

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Export SportTracks.mobi activities (TCX).")
    p.add_argument("--email", "--user", dest="email", default=os.getenv("SPORTTRACKS_EMAIL"),
                   help="SportTracks email/username (or set SPORTTRACKS_EMAIL)")
    p.add_argument("--password", dest="password", default=os.getenv("SPORTTRACKS_PASSWORD"),
                   help="SportTracks password (or set SPORTTRACKS_PASSWORD)")
    p.add_argument("--outdir", default=os.getenv("SPORTTRACKS_OUTDIR", "st_tcx"),
                   help="Directory to save TCX files (default: st_tcx)")
    p.add_argument("--rate", type=float, default=float(os.getenv("SPORTTRACKS_RATE", "0.3")),
                   help="Seconds to sleep between downloads (default: 0.3)")
    p.add_argument("--max", type=int, default=int(os.getenv("SPORTTRACKS_MAX", "0")),
                   help="Max activities to download (0 = no limit)")
    p.add_argument("--headful", action="store_true",
                   help="Run browser non-headless for debugging (default: headless)")
    p.add_argument("--relogin", action="store_true",
                   help="Force a fresh login even if cookies.json exists")
    return p.parse_args()

def ensure_creds(email: str | None, password: str | None) -> Tuple[str, str]:
    if not email:
        email = input("SportTracks email/username: ").strip()
    if not password:
        password = getpass.getpass("SportTracks password (hidden): ").strip()
    if not email or not password:
        print("Email and password are required.", file=sys.stderr)
        sys.exit(2)
    return email, password

def collect_ids_and_cookies(email: str, password: str, headless: bool) -> tuple[list[str], dict[str, str]]:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError  # type: ignore
    import json
    import re
    import urllib.parse
    import requests
    from pathlib import Path

    activities_req_url: str | None = None  # the first activities JSON URL we see
    user_id: str | None = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx = browser.new_context()
        page = ctx.new_page()

        # --- Login ---
        page.goto(f"{BASE}/user/login", wait_until="load")
        page.fill('input[name="name"]', email)
        page.fill('input[name="pass"]', password)
        try:
            page.click('button:has-text("Log in"), input[type="submit"][value*="Log in"]', timeout=2000)
        except PWTimeoutError:
            page.keyboard.press("Enter")
        page.wait_for_load_state("networkidle")

        # --- Sniff JSON to capture the activities endpoint & user id ---
        def on_response(resp):
            nonlocal activities_req_url, user_id
            url = resp.url
            if "/api/ajax/users/" in url and "/activities" in url:
                # record the first matching URL (has query params we can reuse)
                if activities_req_url is None:
                    activities_req_url = url
                # pull user id
                m = re.search(r"/api/ajax/users/(\d+)/activities", url)
                if m:
                    user_id = m.group(1)

        page.on("response", on_response)

        # Trigger the workouts view (which fires the JSON request)
        page.goto(f"{BASE}/workouts", wait_until="networkidle")
        page.wait_for_timeout(1500)  # give time for XHR(s)

        # Grab cookies for later requests
        cookies = {c["name"]: c["value"] for c in ctx.cookies()}
        browser.close()

    # --- Safety checks ---
    if not user_id or not activities_req_url:
        print("[error] Could not detect activities endpoint or user id. Try running with --headful and confirm you can see workouts.")
        return [], cookies

    # --- Build a template for pagination using the captured URL's query ---
    parsed = urllib.parse.urlsplit(activities_req_url)
    q = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    # normalize paging params
    q["page"] = "1"
    q.setdefault("count", "100")  # bump page size if allowed
    # Reconstruct a base URL we can tweak per page
    base_activities_url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))

    # --- Use requests + cookies to fetch pages 1..N until empty ---
    s = requests.Session()
    for k, v in cookies.items():
        s.cookies.set(k, v, domain="sporttracks.mobi")

    ids: list[str] = []
    outdir = Path("st_tcx")
    outdir.mkdir(parents=True, exist_ok=True)

    def extract_id(item: dict) -> str | None:
        # Try common ID keys
        for key in ("id", "activityId", "activity_id", "workout_id"):
            if key in item and isinstance(item[key], (int, str)):
                try:
                    return str(int(item[key]))
                except Exception:
                    pass
        # Fallback: look for any int-like field named '*id'
        for k, v in item.items():
            if k.lower().endswith("id"):
                try:
                    return str(int(v))
                except Exception:
                    continue
        return None

    page_no = 1
    total_found = 0
    while True:
        q["page"] = str(page_no)
        url = base_activities_url + "?" + urllib.parse.urlencode(q, doseq=True)
        r = s.get(url, timeout=60)
        if r.status_code != 200:
            print(f"[warn] page {page_no}: HTTP {r.status_code}; stopping.")
            break
        try:
            data = r.json()
        except Exception:
            # Save bad body for inspection
            (outdir / f"activities_page{page_no}.error.html").write_bytes(r.content)
            print(f"[warn] page {page_no}: non-JSON; saved .error.html; stopping.")
            break

        # Save the first page for you to inspect structure
        if page_no == 1:
            (outdir / "activities_page1.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
            print("[info] wrote st_tcx/activities_page1.json (inspect keys/shape)")

        # Find the collection; try common keys
        items = None
        for key in ("items", "data", "results", "activities", "workouts"):
            if isinstance(data, dict) and key in data and isinstance(data[key], list):
                items = data[key]
                break
        if items is None:
            # Sometimes the payload is a list at top level
            if isinstance(data, list):
                items = data
        if not items:
            print(f"[info] page {page_no}: no items; stopping.")
            break

        page_ids = []
        for it in items:
            if isinstance(it, dict):
                aid = extract_id(it)
                if aid:
                    page_ids.append(aid)

        if not page_ids:
            print(f"[info] page {page_no}: no extractable ids; stopping.")
            break

        ids.extend(page_ids)
        total_found += len(page_ids)
        print(f"[info] page {page_no}: +{len(page_ids)} ids (total {total_found})")

        # Stop if we got fewer than requested (likely last page)
        if len(items) < int(q.get("count", "100")):
            break

        page_no += 1

    # de-dup / numeric-sort
    ids = sorted(set(ids), key=lambda x: int(x))
    return ids, cookies

def download_tcx(ids: Iterable[str], cookies: Dict[str, str], outdir: str, rate: float, max_count: int) -> int:
    os.makedirs(outdir, exist_ok=True)
    s = requests.Session()
    # Scope cookie domain to site
    for k, v in cookies.items():
        s.cookies.set(k, v, domain="sporttracks.mobi")

    count = 0
    for aid in ids:
        if max_count and count >= max_count:
            break
        path = os.path.join(outdir, f"{aid}.tcx")
        if os.path.exists(path):
            # Skip already-downloaded files
            count += 1
            continue
        url = f"{BASE}/activity/{aid}/export?type=tcx"
        r = s.get(url, timeout=60)
        if r.ok and r.text.lstrip().startswith("<?xml"):
            with open(path, "w", encoding="utf-8") as f:
                f.write(r.text)
            count += 1
        else:
            # Save error for debugging
            with open(os.path.join(outdir, f"{aid}.error.html"), "wb") as f:
                f.write(r.content)
            print(f"[warn] Unexpected response for activity {aid} (status {r.status_code}); saved .error.html")
        time.sleep(max(rate, 0.0))
    return count

def main() -> None:
    args = parse_args()
    email, password = ensure_creds(args.email, args.password)

    # Optionally reuse cookies between runs (simple file cache)
    cookie_cache = os.path.join(args.outdir, "cookies.txt")
    ids_cache = os.path.join(args.outdir, "ids.txt")

    cookies: Dict[str, str] = {}
    ids: List[str] = []

    if not args.relogin and os.path.exists(cookie_cache) and os.path.exists(ids_cache):
        # Use cached ids + cookies
        os.makedirs(args.outdir, exist_ok=True)
        with open(ids_cache, "r", encoding="utf-8") as f:
            ids = [line.strip() for line in f if line.strip().isdigit()]
        with open(cookie_cache, "r", encoding="utf-8") as f:
            for line in f:
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    cookies[k] = v
        print(f"[info] Reusing cached cookies and {len(ids)} ids…")
    else:
        os.makedirs(args.outdir, exist_ok=True)
        ids, cookies = collect_ids_and_cookies(email, password, headless=not args.headful)
        # Persist simple cookie/ids cache (plain text; do NOT commit this)
        with open(ids_cache, "w", encoding="utf-8") as f:
            f.write("\n".join(ids))
        with open(cookie_cache, "w", encoding="utf-8") as f:
            for k, v in cookies.items():
                f.write(f"{k}={v}\n")
        print(f"[info] Collected {len(ids)} activity ids.")

    downloaded = download_tcx(ids, cookies, args.outdir, args.rate, args.max)
    print(f"[done] Downloaded {downloaded} TCX file(s) to {args.outdir}")

if __name__ == "__main__":
    main()
