#!/usr/bin/env python3
import argparse, hashlib, os, subprocess, sys
from datetime import datetime
import sqlite3
from pathlib import Path

def git_hash():
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "no-git"

def backup_one(src_path: Path, dst_path: Path):
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f"file:{src_path}?mode=ro", uri=True) as src, \
         sqlite3.connect(dst_path) as dst:
        src.backup(dst)  # consistent snapshot using SQLite backup API

def main():
    p = argparse.ArgumentParser(description="Snapshot SQLite DBs consistently.")
    p.add_argument("--db-dir", default="app/db", help="Directory containing *.db files")
    p.add_argument("--out-root", default="db_backups", help="Root folder for snapshots")
    args = p.parse_args()

    db_dir = Path(args.db_dir)
    out_root = Path(args.out_root)

    commit = git_hash()
    ts = datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    # Collect DB files
    dbs = sorted(db_dir.glob("*.db"))
    if not dbs:
        print(f"No .db files found in {db_dir}", file=sys.stderr)
        sys.exit(1)

    # Folder named with timestamp + commit
    batch_dir = out_root / f"{ts}_{commit}"
    batch_dir.mkdir(parents=True, exist_ok=True)

    manifest_lines = []
    for db in dbs:
        out = batch_dir / db.name
        backup_one(db, out)

        # Make a tiny checksum for integrity
        h = hashlib.sha256(out.read_bytes()).hexdigest()[:16]
        manifest_lines.append(f"{db.name},sha256:{h}")

    # Write manifest
    (batch_dir / "MANIFEST.txt").write_text(
        "commit=" + commit + "\n"
        "timestamp=" + ts + "Z\n"
        + "\n".join(manifest_lines) + "\n",
        encoding="utf-8"
    )

    print(f"Backed up {len(dbs)} DB(s) to {batch_dir}")

if __name__ == "__main__":
    main()
