#!/usr/bin/env python3
"""
find_overlapping_training_activities.py

Scan canonical activities that have TrainingLogData.isTraining = 1 and report
overlapping time intervals to help find duplicates.

Assumptions:
- activity.start_time_utc is ISO8601 UTC like '2025-08-29T19:24:52Z'
- activity.end_time_utc may be NULL
- if end_time_utc is NULL and elapsed_time_s is present, end = start + elapsed_time_s
- TrainingLogData.canonical_activity_id references activity.id
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Tuple, Dict, Set


ISO_Z = "%Y-%m-%dT%H:%M:%SZ"


def parse_utc_z(s: str) -> datetime:
    # Strict parse for the format you showed. If you have other formats, we can broaden this.
    return datetime.strptime(s, ISO_Z).replace(tzinfo=timezone.utc)


def fmt_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime(ISO_Z)


@dataclass(frozen=True)
class Interval:
    activity_id: int
    start: datetime
    end: datetime
    name: Optional[str]
    sport: Optional[str]
    distance_m: Optional[float]
    elapsed_s: Optional[int]
    source_quality: Optional[int]


def compute_end(start: datetime, end_time_utc: Optional[str], elapsed_time_s: Optional[int]) -> Optional[datetime]:
    if end_time_utc:
        try:
            return parse_utc_z(end_time_utc)
        except Exception:
            return None
    if elapsed_time_s is not None:
        return start + timedelta(seconds=int(elapsed_time_s))
    return None


def overlaps(a: Interval, b: Interval, *, tolerance_s: int = 0, min_overlap_s: int = 1) -> Tuple[bool, int]:
    """
    Returns (is_overlap, overlap_seconds).
    tolerance_s expands both intervals by that many seconds to catch "near overlaps".
    min_overlap_s is the minimum overlap duration to report.
    """
    ta0 = a.start - timedelta(seconds=tolerance_s)
    ta1 = a.end + timedelta(seconds=tolerance_s)
    tb0 = b.start - timedelta(seconds=tolerance_s)
    tb1 = b.end + timedelta(seconds=tolerance_s)

    latest_start = max(ta0, tb0)
    earliest_end = min(ta1, tb1)
    delta = (earliest_end - latest_start).total_seconds()
    if delta >= min_overlap_s:
        return True, int(delta)
    return False, 0


def fetch_training_intervals(conn: sqlite3.Connection) -> List[Interval]:
    """
    Pull canonical activities that have a TrainingLogData row with isTraining = 1
    and canonical_activity_id present.
    """
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT
            a.id,
            a.start_time_utc,
            a.end_time_utc,
            a.elapsed_time_s,
            a.distance_m,
            a.name,
            a.sport,
            a.source_quality
        FROM activity a
        JOIN TrainingLogData tld
          ON tld.canonical_activity_id = a.id
        WHERE tld.isTraining = 1
          AND a.start_time_utc IS NOT NULL
        ORDER BY a.start_time_utc ASC, a.id ASC
        """
    ).fetchall()

    out: List[Interval] = []
    skipped = 0
    for r in rows:
        try:
            start = parse_utc_z(r["start_time_utc"])
        except Exception:
            skipped += 1
            continue

        end = compute_end(start, r["end_time_utc"], r["elapsed_time_s"])
        if end is None:
            skipped += 1
            continue

        # Guard: occasionally data could be inverted; skip those too.
        if end <= start:
            skipped += 1
            continue

        out.append(
            Interval(
                activity_id=int(r["id"]),
                start=start,
                end=end,
                name=r["name"],
                sport=r["sport"],
                distance_m=r["distance_m"],
                elapsed_s=r["elapsed_time_s"],
                source_quality=r["source_quality"],
            )
        )

    if skipped:
        print(f"[note] Skipped {skipped} rows (bad/missing time interval).")
    return out


def find_overlapping_pairs(
    intervals: List[Interval],
    *,
    tolerance_s: int,
    min_overlap_s: int,
) -> List[Tuple[Interval, Interval, int]]:
    """
    Efficient sweep-line-ish scan since intervals are sorted by start.
    """
    pairs: List[Tuple[Interval, Interval, int]] = []

    # Active list stores indices of intervals whose end is >= current start (within tolerance).
    active: List[Interval] = []

    for cur in intervals:
        # Drop anything that cannot overlap cur (even with tolerance)
        cur_start_minus_tol = cur.start - timedelta(seconds=tolerance_s)
        active = [x for x in active if (x.end + timedelta(seconds=tolerance_s)) >= cur_start_minus_tol]

        # Compare against active set
        for prev in active:
            ok, ov_s = overlaps(prev, cur, tolerance_s=tolerance_s, min_overlap_s=min_overlap_s)
            if ok:
                pairs.append((prev, cur, ov_s))

        active.append(cur)

    return pairs


def build_overlap_graph(pairs: List[Tuple[Interval, Interval, int]]) -> Dict[int, Set[int]]:
    g: Dict[int, Set[int]] = {}
    for a, b, _ov in pairs:
        g.setdefault(a.activity_id, set()).add(b.activity_id)
        g.setdefault(b.activity_id, set()).add(a.activity_id)
    return g


def connected_components(nodes: List[int], graph: Dict[int, Set[int]]) -> List[List[int]]:
    seen: Set[int] = set()
    comps: List[List[int]] = []
    node_set = set(nodes)

    for n in nodes:
        if n in seen:
            continue
        if n not in graph:
            # singleton, no overlaps
            seen.add(n)
            continue

        stack = [n]
        comp: List[int] = []
        seen.add(n)

        while stack:
            u = stack.pop()
            comp.append(u)
            for v in graph.get(u, set()):
                if v in node_set and v not in seen:
                    seen.add(v)
                    stack.append(v)

        comps.append(sorted(comp))
    return sorted(comps, key=len, reverse=True)


def interval_by_id(intervals: List[Interval]) -> Dict[int, Interval]:
    return {it.activity_id: it for it in intervals}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("db", help="Path to your sqlite database (e.g., supertl2.db)")
    ap.add_argument("--tolerance-s", type=int, default=0,
                    help="Expand intervals by this many seconds on both ends (helps catch near-duplicates). Default 0.")
    ap.add_argument("--min-overlap-s", type=int, default=60,
                    help="Only report overlaps >= this many seconds. Default 60.")
    ap.add_argument("--limit", type=int, default=200,
                    help="Max pair rows to print (still computes all). Default 200.")
    ap.add_argument("--csv", default=None,
                    help="Optional path to write overlapping pairs as CSV.")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    intervals = fetch_training_intervals(conn)
    if not intervals:
        print("No training-linked canonical activities found (TrainingLogData.isTraining=1).")
        return 0

    pairs = find_overlapping_pairs(intervals, tolerance_s=args.tolerance_s, min_overlap_s=args.min_overlap_s)

    print(f"Training-linked canonical activities: {len(intervals)}")
    print(f"Overlapping pairs (>= {args.min_overlap_s}s, tol={args.tolerance_s}s): {len(pairs)}")

    # Sort pairs: biggest overlap first, then earlier start
    pairs_sorted = sorted(pairs, key=lambda t: (-t[2], t[0].start, t[1].start, t[0].activity_id, t[1].activity_id))

    # Print a nice report
    def brief(it: Interval) -> str:
        dist_km = (it.distance_m / 1000.0) if it.distance_m is not None else None
        dist = f"{dist_km:.2f}km" if dist_km is not None else "n/a"
        nm = (it.name or "").strip()
        nm = nm if nm else "—"
        sp = it.sport or "—"
        return f"id={it.activity_id} {sp} {dist} '{nm}'"

    print("\n=== Top overlapping pairs ===")
    to_print = pairs_sorted[: max(0, args.limit)]
    for a, b, ov_s in to_print:
        print(f"- overlap={ov_s:5d}s | {fmt_utc(a.start)} .. {fmt_utc(a.end)} | {brief(a)}")
        print(f"                 {fmt_utc(b.start)} .. {fmt_utc(b.end)} | {brief(b)}")

    # CSV output
    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([
                "overlap_seconds",
                "a_id", "a_start_utc", "a_end_utc", "a_sport", "a_distance_m", "a_name",
                "b_id", "b_start_utc", "b_end_utc", "b_sport", "b_distance_m", "b_name",
            ])
            for a, b, ov_s in pairs_sorted:
                w.writerow([
                    ov_s,
                    a.activity_id, fmt_utc(a.start), fmt_utc(a.end), a.sport, a.distance_m, a.name,
                    b.activity_id, fmt_utc(b.start), fmt_utc(b.end), b.sport, b.distance_m, b.name,
                ])
        print(f"\nWrote CSV: {args.csv}")

    # Grouping (connected components)
    g = build_overlap_graph(pairs)
    ids = [it.activity_id for it in intervals]
    comps = connected_components(ids, g)

    print("\n=== Overlap groups (potential duplicate clusters) ===")
    id_map = interval_by_id(intervals)
    shown = 0
    for comp in comps:
        if len(comp) <= 1:
            continue
        shown += 1
        print(f"\nGroup size {len(comp)}: {comp}")
        # show members sorted by start time
        members = sorted((id_map[i] for i in comp), key=lambda x: x.start)
        for it in members:
            print(f"  {fmt_utc(it.start)} .. {fmt_utc(it.end)} | {brief(it)}")

    if shown == 0:
        print("(No multi-activity overlap groups found.)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
