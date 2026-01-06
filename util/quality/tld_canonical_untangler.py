#!/usr/bin/env python3
"""
tld_canonical_untangler.py

Find canonical activities that have multiple TrainingLogData rows linked,
summarize what's happening, and recommend which TrainingLogData row to keep.

Optionally apply the recommendation by unlinking the other rows:
    UPDATE TrainingLogData SET canonical_activity_id=NULL WHERE activityId=...

Usage:
  python tld_canonical_untangler.py /path/to/supertl2.db
  python tld_canonical_untangler.py /path/to/supertl2.db --limit 50
  python tld_canonical_untangler.py /path/to/supertl2.db --canonical 2408
  python tld_canonical_untangler.py /path/to/supertl2.db --apply
"""

from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple


def normalize_source_id(source: str, source_activity_id: str) -> str:
    """
    Normalizes activity_source.source_activity_id into a comparable form.

    In your DB, Strava source_activity_id appears to sometimes be stored as
    'activity-<id>' (not just '<id>'). Normalize to the bare id.
    """
    if source == "strava":
        if source_activity_id.startswith("activity-"):
            return source_activity_id[len("activity-") :]
        return source_activity_id
    # sporttracks are already bare numeric strings in your examples
    return source_activity_id

# ---------- Parsing helpers for your TrainingLogData.activityId format ----------

def parse_tld_activity_id(activity_id: str) -> Tuple[str, Optional[str]]:
    """
    Returns (kind, raw_id)
    kind: 'strava', 'sporttracks', or 'unknown'
    raw_id: the id portion (e.g., '2728865217' from 'activity-2728865217')
    """
    if activity_id.startswith("activity-"):
        return "strava", activity_id[len("activity-") :]
    if activity_id.startswith("st-"):
        return "sporttracks", activity_id[len("st-") :]
    return "unknown", None


# ---------- Data containers ----------

@dataclass
class CanonicalIssue:
    canonical_id: int
    tld_activity_ids: List[str]
    sources: Dict[str, List[str]]  # source -> [source_activity_id]


# ---------- DB helpers ----------

def connect_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    # For safety + speed
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def fetch_problem_canonicals(conn: sqlite3.Connection, canonical: Optional[int], limit: Optional[int]) -> List[int]:
    if canonical is not None:
        # Only include it if it's actually problematic
        row = conn.execute(
            """
            SELECT canonical_activity_id, COUNT(*) AS n
            FROM TrainingLogData
            WHERE canonical_activity_id = ?
            GROUP BY canonical_activity_id
            HAVING COUNT(*) > 1
            """,
            (canonical,),
        ).fetchone()
        return [canonical] if row else []

    sql = """
    SELECT canonical_activity_id
    FROM TrainingLogData
    WHERE canonical_activity_id IS NOT NULL
    GROUP BY canonical_activity_id
    HAVING COUNT(*) > 1
    ORDER BY COUNT(*) DESC, canonical_activity_id ASC
    """
    if limit:
        sql += " LIMIT ?"
        rows = conn.execute(sql, (limit,)).fetchall()
    else:
        rows = conn.execute(sql).fetchall()

    return [int(r["canonical_activity_id"]) for r in rows]


def fetch_issue_details(conn: sqlite3.Connection, canonical_id: int) -> CanonicalIssue:
    tld_rows = conn.execute(
        """
        SELECT activityId
        FROM TrainingLogData
        WHERE canonical_activity_id = ?
        ORDER BY activityId
        """,
        (canonical_id,),
    ).fetchall()
    tld_ids = [r["activityId"] for r in tld_rows]

    src_rows = conn.execute(
        """
        SELECT source, source_activity_id
        FROM activity_source
        WHERE activity_id = ?
        ORDER BY source, source_activity_id
        """,
        (canonical_id,),
    ).fetchall()

    sources: Dict[str, List[str]] = {}
    for r in src_rows:
        src = r["source"]
        sid = normalize_source_id(src, r["source_activity_id"])
        sources.setdefault(src, []).append(sid)


    return CanonicalIssue(canonical_id=canonical_id, tld_activity_ids=tld_ids, sources=sources)


# ---------- Recommendation logic ----------

@dataclass
class Recommendation:
    canonical_id: int
    keep_activity_id: Optional[str]
    unlink_activity_ids: List[str]
    reason: str


def recommend_for_issue(issue: CanonicalIssue) -> Recommendation:
    # Build matching sets based on activity_source
    strava_source_ids = set(issue.sources.get("strava", []))
    st_source_ids = set(issue.sources.get("sporttracks", []))

    # Identify which TLD rows match which source id
    matches_strava: List[str] = []
    matches_st: List[str] = []
    unknowns: List[str] = []

    for tld_id in issue.tld_activity_ids:
        kind, raw = parse_tld_activity_id(tld_id)
        if kind == "strava" and raw is not None and raw in strava_source_ids:
            matches_strava.append(tld_id)
        elif kind == "sporttracks" and raw is not None and raw in st_source_ids:
            matches_st.append(tld_id)
        elif kind == "unknown":
            unknowns.append(tld_id)

    # Decision tree:
    # 0) If we have one strava match and one sporttracks match, prefer keeping strava.
    if len(matches_strava) == 1 and len(matches_st) == 1:
        keep = matches_strava[0]
        unlink = [x for x in issue.tld_activity_ids if x != keep]
        return Recommendation(
            canonical_id=issue.canonical_id,
            keep_activity_id=keep,
            unlink_activity_ids=unlink,
            reason="Both Strava and SportTracks TLD rows match canonical sources; preferred Strava as canonical owner.",
        )

    # 1) If exactly one matches Strava, keep it.
    if len(matches_strava) == 1:
        keep = matches_strava[0]
        unlink = [x for x in issue.tld_activity_ids if x != keep]
        return Recommendation(
            canonical_id=issue.canonical_id,
            keep_activity_id=keep,
            unlink_activity_ids=unlink,
            reason="Kept the only TrainingLogData row that matches canonical Strava source_activity_id.",
        )

    # 2) Else if exactly one matches SportTracks, keep it.
    if len(matches_st) == 1:
        keep = matches_st[0]
        unlink = [x for x in issue.tld_activity_ids if x != keep]
        return Recommendation(
            canonical_id=issue.canonical_id,
            keep_activity_id=keep,
            unlink_activity_ids=unlink,
            reason="Kept the only TrainingLogData row that matches canonical SportTracks source_activity_id.",
        )

    # 3) If multiple match strava, pick a deterministic one (lexicographically smallest).
    if len(matches_strava) > 1:
        keep = sorted(matches_strava)[0]
        unlink = [x for x in issue.tld_activity_ids if x != keep]
        return Recommendation(
            canonical_id=issue.canonical_id,
            keep_activity_id=keep,
            unlink_activity_ids=unlink,
            reason="Multiple TrainingLogData rows match Strava source; chose deterministic smallest. Review recommended.",
        )

    # 4) If multiple match sporttracks, pick deterministic one.
    if len(matches_st) > 1:
        keep = sorted(matches_st)[0]
        unlink = [x for x in issue.tld_activity_ids if x != keep]
        return Recommendation(
            canonical_id=issue.canonical_id,
            keep_activity_id=keep,
            unlink_activity_ids=unlink,
            reason="Multiple TrainingLogData rows match SportTracks source; chose deterministic smallest. Review recommended.",
        )

    # 5) No matches at all — fall back:
    # Prefer activity-* (strava-ish), then st-*, then unknown, then lexicographic
    def fallback_rank(tld_id: str) -> Tuple[int, str]:
        if tld_id.startswith("activity-"):
            return (0, tld_id)
        if tld_id.startswith("st-"):
            return (1, tld_id)
        return (2, tld_id)

    keep = sorted(issue.tld_activity_ids, key=fallback_rank)[0] if issue.tld_activity_ids else None
    unlink = [x for x in issue.tld_activity_ids if x != keep] if keep else []
    return Recommendation(
        canonical_id=issue.canonical_id,
        keep_activity_id=keep,
        unlink_activity_ids=unlink,
        reason="No TrainingLogData row matched canonical sources; used fallback preference (activity- > st- > other). Review recommended.",
    )


# ---------- Reporting ----------

def fmt_table(rows: List[List[str]], headers: List[str]) -> str:
    # Simple table formatter (no external deps)
    col_widths = [len(h) for h in headers]
    for r in rows:
        for i, v in enumerate(r):
            col_widths[i] = max(col_widths[i], len(v))

    def fmt_row(r: List[str]) -> str:
        return " | ".join(v.ljust(col_widths[i]) for i, v in enumerate(r))

    sep = "-+-".join("-" * w for w in col_widths)
    out = [fmt_row(headers), sep]
    out += [fmt_row(r) for r in rows]
    return "\n".join(out)


def summarize_issue(issue: CanonicalIssue, rec: Recommendation) -> str:
    # Summarize per canonical, showing TLD rows and whether they match sources
    src_str = []
    for s, ids in issue.sources.items():
        src_str.append(f"{s}=[{', '.join(ids)}]")
    sources_line = "; ".join(src_str) if src_str else "(no activity_source rows)"

    rows: List[List[str]] = []
    for tld_id in issue.tld_activity_ids:
        kind, raw = parse_tld_activity_id(tld_id)
        match = ""
        if kind == "strava" and raw and raw in set(issue.sources.get("strava", [])):
            match = "matches strava source"
        elif kind == "sporttracks" and raw and raw in set(issue.sources.get("sporttracks", [])):
            match = "matches sporttracks source"
        else:
            match = "no source match"

        rows.append([
            str(issue.canonical_id),
            tld_id,
            kind,
            raw or "",
            match,
            "KEEP" if tld_id == rec.keep_activity_id else ("UNLINK" if tld_id in rec.unlink_activity_ids else ""),
        ])

    hdr = ["canonical_id", "TrainingLogData.activityId", "kind", "raw_id", "match", "action"]
    block = []
    block.append(f"Canonical {issue.canonical_id} sources: {sources_line}")
    block.append(fmt_table(rows, hdr))
    block.append(f"Recommendation: keep={rec.keep_activity_id} unlink={rec.unlink_activity_ids}")
    block.append(f"Reason: {rec.reason}")
    return "\n".join(block)


# ---------- Apply changes ----------

def apply_recommendation(conn: sqlite3.Connection, rec: Recommendation) -> int:
    """
    Unlink the recommended extra rows by setting canonical_activity_id=NULL.
    Returns number of rows updated.
    """
    if not rec.unlink_activity_ids:
        return 0

    # Use a parameterized IN list
    placeholders = ",".join("?" for _ in rec.unlink_activity_ids)
    sql = f"""
    UPDATE TrainingLogData
    SET canonical_activity_id = NULL
    WHERE canonical_activity_id = ?
      AND activityId IN ({placeholders})
    """
    params = [rec.canonical_id] + rec.unlink_activity_ids
    cur = conn.execute(sql, params)
    return cur.rowcount


# ---------- Main ----------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("db", help="Path to supertl2 sqlite db file (the one your app uses)")
    ap.add_argument("--canonical", type=int, help="Analyze only a single canonical activity id")
    ap.add_argument("--limit", type=int, default=None, help="Limit number of canonicals to process")
    ap.add_argument("--apply", action="store_true", help="Apply recommendations (unlink extras)")
    ap.add_argument("--no-commit", action="store_true", help="If --apply, run updates but rollback (test mode)")
    args = ap.parse_args()

    conn = connect_db(args.db)

    canonicals = fetch_problem_canonicals(conn, args.canonical, args.limit)
    if not canonicals:
        print("No canonical activities found with multiple TrainingLogData rows linked.")
        return 0

    all_summary_rows: List[List[str]] = []
    # Summary table across all issues
    # canonical_id | tld_count | sources | keep | unlink_count | reason_short
    for cid in canonicals:
        issue = fetch_issue_details(conn, cid)
        rec = recommend_for_issue(issue)

        sources_compact = ",".join(
            f"{src}:{len(ids)}" for src, ids in sorted(issue.sources.items())
        ) or "none"

        reason_short = rec.reason.replace("TrainingLogData row", "TLD row")
        if len(reason_short) > 70:
            reason_short = reason_short[:67] + "..."

        all_summary_rows.append([
            str(cid),
            str(len(issue.tld_activity_ids)),
            sources_compact,
            rec.keep_activity_id or "",
            str(len(rec.unlink_activity_ids)),
            reason_short,
        ])

    print("\n=== High-level summary (all problematic canonicals) ===")
    print(fmt_table(
        all_summary_rows,
        ["canonical_id", "tld_rows", "sources(count)", "keep", "unlink", "reason"]
    ))

    print("\n=== Detailed per-canonical breakdown ===")
    total_to_unlink = 0
    for cid in canonicals:
        issue = fetch_issue_details(conn, cid)
        rec = recommend_for_issue(issue)
        print("\n" + "=" * 110)
        print(summarize_issue(issue, rec))
        total_to_unlink += len(rec.unlink_activity_ids)

    if args.apply:
        print("\n=== APPLY MODE ===")
        print("This will set TrainingLogData.canonical_activity_id = NULL for the recommended UNLINK rows.")
        updated_total = 0
        try:
            for cid in canonicals:
                issue = fetch_issue_details(conn, cid)
                rec = recommend_for_issue(issue)
                n = apply_recommendation(conn, rec)
                updated_total += n

            if args.no_commit:
                conn.rollback()
                print(f"Rolled back (test mode). Would have updated {updated_total} row(s).")
            else:
                conn.commit()
                print(f"Committed. Updated {updated_total} row(s).")

        except Exception as e:
            conn.rollback()
            raise

    else:
        print("\n=== DRY RUN (no changes made) ===")
        print("Re-run with --apply to unlink the recommended extras.")
        print("Tip: run once with --apply --no-commit to validate behavior, then run again without --no-commit.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
