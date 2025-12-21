from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional, List, Dict, Any
from collections import defaultdict

from sqlalchemy import func, text

# adjust imports to your project
from ..db.base import sqla_db
from ..models.activity import Activity
from ..models.traininglogdata import TrainingLogData
from ..models.category import Category


from datetime import datetime

def _coerce_to_datetime(ts):
    """
    Coerce a DB value into a Python datetime.

    Handles:
      - datetime already
      - ISO-ish strings: 'YYYY-MM-DD HH:MM:SS', 'YYYY-MM-DDTHH:MM:SS', with/without fractions
      - trailing 'Z'
      - timezone offsets (best effort)
    """
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts
    if isinstance(ts, str):
        s = ts.strip()
        if s.endswith("Z"):
            s = s[:-1]
        # Normalize common format variants
        s = s.replace(" ", "T")
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            # Last-ditch: try without 'T' if it wasn't actually ISO
            try:
                return datetime.fromisoformat(s.replace("T", " "))
            except ValueError:
                return None
    return None

def _today_local_date() -> date:
    # Your timezone per project instructions
    return datetime.now(ZoneInfo("America/Chicago")).date()

def _as_datetime_start(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 0, 0, 0)

def _as_datetime_end_exclusive(d: date) -> datetime:
    # end is inclusive at the season level, but easier to query as < next day
    nd = d + timedelta(days=1)
    return datetime(nd.year, nd.month, nd.day, 0, 0, 0)

def _daterange_weeks(start: date, end: date, week_start: int = 0):
    ws = _week_start(start, week_start)
    we = _week_start(end, week_start)
    out = []
    cur = ws
    while cur <= we:
        out.append(cur)
        cur = cur + timedelta(days=7)
    return out

def _week_start(dt: date, week_start: int = 0) -> date:
    """
    Return the date for the start of the week containing dt.
    week_start: 0=Monday, 6=Sunday
    """
    # Python weekday(): Monday=0..Sunday=6
    delta = (dt.weekday() - week_start) % 7
    return dt - timedelta(days=delta)

def _daterange_weeks(start: date, end: date, week_start: int = 0) -> List[date]:
    """
    List of week-start dates covering [start, end] inclusive.
    """
    ws = _week_start(start, week_start)
    we = _week_start(end, week_start)
    out = []
    cur = ws
    while cur <= we:
        out.append(cur)
        cur = cur + timedelta(days=7)
    return out


def get_season_summary(season_start: date, season_end: date, use_local: bool = True) -> Dict[str, Any]:
    """
    For in-progress seasons, weeks + avg/week are computed TO-DATE (through today),
    not through the configured season_end.

    Returns:
      total_hours: float
      sessions: int
      weeks: int (count of week buckets touched)
      avg_hours_per_week: float
    """
    today = _today_local_date()
    effective_end = min(season_end, today)
    is_in_progress = effective_end < season_end
    start_dt = _as_datetime_start(season_start)
    end_dt_excl = _as_datetime_end_exclusive(season_end)

    # Pick the timestamp column to filter by.
    # Change these if your model fields differ.
    ts_col = Activity.start_time_local if use_local and hasattr(Activity, "start_time_local") else Activity.start_time_utc

    total_seconds, sessions = (
        sqla_db.session.query(
            func.coalesce(func.sum(Activity.moving_time_s), 0),
            func.count(Activity.id),
        )
        .join(
            TrainingLogData,
            TrainingLogData.canonical_activity_id == Activity.id,
        )
        .filter(
            TrainingLogData.isTraining == 1,
            ts_col >= start_dt,
            ts_col < end_dt_excl,
        )
        .one()
    )

    total_seconds = int(total_seconds or 0)
    sessions = int(sessions or 0)

    week_starts = _daterange_weeks(season_start, effective_end, week_start=0)  # Monday start
    weeks = len(week_starts)
    total_hours = total_seconds / 3600.0
    avg_hours_per_week = (total_hours / weeks) if weeks else 0.0

    return {
        "total_hours": total_hours,
        "sessions": sessions,
        "weeks": weeks,
        "avg_hours_per_week": avg_hours_per_week,
        "effective_end": effective_end.isoformat(),
        "is_in_progress": is_in_progress,
    }


def get_season_weekly_series(season_start: date, season_end: date, use_local: bool = True) -> Dict[str, Any]:
    """
    Returns a dict ready to chart:

    {
      "weeks": [
        {"week_start": "2024-05-06", "hours": 12.3, "label": "May 06"},
        ...
      ]
    }

    This intentionally does NOT stack by category yet — just total hours per week.
    """
    start_dt = _as_datetime_start(season_start)
    end_dt_excl = _as_datetime_end_exclusive(season_end)

    ts_col = Activity.start_time_local if use_local and hasattr(Activity, "start_time_local") else Activity.start_time_utc

    # Fetch all activities in range (id + date + seconds) and bucket in Python.
    # This avoids SQLite timezone/date quirks and keeps “week starts Monday” consistent.
    rows = (
        sqla_db.session.query(ts_col, Activity.moving_time_s)
        .join(
            TrainingLogData,
            TrainingLogData.canonical_activity_id == Activity.id,
        )
        .filter(
            TrainingLogData.isTraining == 1,
            ts_col >= start_dt,
            ts_col < end_dt_excl,
        )
        .all()
    )

    buckets: Dict[date, int] = {}
    for ts, secs in rows:
        dt = _coerce_to_datetime(ts)
        if dt is None:
            continue
        d = dt.date()
        ws = _week_start(d, week_start=0)
        buckets[ws] = buckets.get(ws, 0) + int(secs or 0)

    week_starts = _daterange_weeks(season_start, season_end, week_start=0)
    weeks_out = []
    for ws in week_starts:
        sec = buckets.get(ws, 0)
        hours = sec / 3600.0
        weeks_out.append({
            "week_start": ws.isoformat(),
            "hours": hours,
            "label": ws.strftime("%b %d"),
        })

    return {"weeks": weeks_out}

def _build_category_full_paths() -> dict[int, str]:
    """
    Returns {category_id: "Root : Child : Leaf"} for ALL categories.
    Mirrors the recursive CTE you already use in views.py.
    """
    rows = sqla_db.session.execute(text("""
        WITH RECURSIVE category_path(id, name, parent_id, full_path, depth) AS (
            SELECT id, name, parent_id, name, 0
            FROM Category
            WHERE parent_id IS NULL
            UNION ALL
            SELECT c.id, c.name, c.parent_id, cp.full_path || ' : ' || c.name, cp.depth + 1
            FROM Category c
            JOIN category_path cp ON c.parent_id = cp.id
        )
        SELECT id, full_path, depth FROM category_path
    """)).fetchall()

    full_path = {}
    depth_map = {}
    for r in rows:
        full_path[int(r.id)] = r.full_path
        depth_map[int(r.id)] = int(r.depth)
    return full_path, depth_map


def _build_category_parent_map() -> dict[int, int | None]:
    rows = sqla_db.session.query(Category.id, Category.parent_id).all()
    return {int(cid): (int(pid) if pid is not None else None) for cid, pid in rows}


def _ancestor_at_depth(cat_id: int, target_depth: int, parent_map: dict[int, int | None], depth_map: dict[int, int]) -> int:
    """
    Walk up parents until reaching the node whose depth == target_depth.
    If cat is shallower than target_depth, return the original.
    """
    cur = cat_id
    while cur in depth_map and depth_map[cur] > target_depth:
        cur = parent_map.get(cur)
        if cur is None:
            break
    return cur if cur is not None else cat_id


def get_season_traininglog_category_breakdown(
    season_start_dt,
    season_end_dt_excl,
    use_local=True,
    rollup_depth: int | None = 2,   # <-- set None to keep full leaf level
    min_percent: float = 2.0        # <-- collapse tiny slices into "Other"
):
    """
    Training-only category distribution using TrainingLogData.categoryId.

    - Groups by categoryId (unique), NOT by Category.name.
    - Uses full_path labels for disambiguation.
    - Optionally rolls up deep categories to a chosen depth (default depth=2).
    - Optionally collapses tiny slices into "Other".
    """
    ts_col = Activity.start_time_local if use_local and hasattr(Activity, "start_time_local") else Activity.start_time_utc

    # 1) Sum seconds by *leaf* categoryId (unique key)
    rows = (
        sqla_db.session.query(
            TrainingLogData.categoryId.label("category_id"),
            func.coalesce(func.sum(Activity.moving_time_s), 0).label("seconds"),
        )
        .join(TrainingLogData, TrainingLogData.canonical_activity_id == Activity.id)
        .filter(
            TrainingLogData.isTraining == 1,
            TrainingLogData.categoryId.isnot(None),
            ts_col >= season_start_dt,
            ts_col < season_end_dt_excl,
        )
        .group_by(TrainingLogData.categoryId)
        .all()
    )

    totals_by_leaf = {int(r.category_id): int(r.seconds or 0) for r in rows}
    total_seconds = sum(totals_by_leaf.values()) or 0

    # 2) Build category display paths + parents/depths
    full_paths, depth_map = _build_category_full_paths()
    parent_map = _build_category_parent_map()

    # 3) Optional rollup
    totals_by_bucket: dict[int, int] = defaultdict(int)
    for leaf_id, sec in totals_by_leaf.items():
        if rollup_depth is None:
            bucket_id = leaf_id
        else:
            bucket_id = _ancestor_at_depth(leaf_id, rollup_depth, parent_map, depth_map)
        totals_by_bucket[bucket_id] += sec

    # 4) Build items and optionally collapse small slices into "Other"
    items = []
    for cid, sec in totals_by_bucket.items():
        label = full_paths.get(cid) or f"Category {cid}"
        items.append({"category_id": cid, "label": label, "seconds": sec})

    items.sort(key=lambda x: x["seconds"], reverse=True)

    if min_percent and total_seconds:
        keep = []
        other_seconds = 0
        for it in items:
            pct = (it["seconds"] / total_seconds) * 100.0
            if pct < min_percent:
                other_seconds += it["seconds"]
            else:
                keep.append(it)
        if other_seconds > 0:
            keep.append({"category_id": -1, "label": "Other", "seconds": other_seconds})
        items = keep

    # 5) Final shape for template/chart
    out = []
    for it in items:
        sec = int(it["seconds"])
        hours = sec / 3600.0
        pct = (sec / total_seconds * 100.0) if total_seconds else 0.0
        out.append({
            "category_id": it["category_id"],
            "label": it["label"],
            "hours": hours,
            "percent": pct,
        })

    return {"total_hours": total_seconds / 3600.0, "items": out}

def get_season_comparison_rows(seasons) -> List[Dict[str, Any]]:
    """
    Returns rows suitable for a comparison table.
    Uses the same definition of "training" as the dashboard:
    TrainingLogData.isTraining == 1. :contentReference[oaicite:3]{index=3}
    """
    rows = []
    for s in seasons:
        summary = get_season_summary(s.start_date, s.end_date, use_local=True)

        # (Optional) add one “headline category” at a rolled-up depth:
        # If you don’t want this yet, delete this block.
        start_dt = _as_datetime_start(s.start_date)
        end_dt_excl = _as_datetime_end_exclusive(s.end_date)
        breakdown = get_season_traininglog_category_breakdown(
            start_dt, end_dt_excl, use_local=True, rollup_depth=1, min_percent=0.0
        )
        top_cat = None
        if breakdown and breakdown.get("items"):
            top_cat = breakdown["items"][0]["label"]

        rows.append({
            "id": s.id,
            "name": s.name,
            "start_date": s.start_date,
            "end_date": s.end_date,
            "is_active": bool(getattr(s, "is_active", False)),
            "is_in_progress": bool(summary.get("is_in_progress")),
            "total_hours": float(summary.get("total_hours", 0.0)),
            "sessions": int(summary.get("sessions", 0)),
            "weeks": int(summary.get("weeks", 0)),
            "avg_hours_per_week": float(summary.get("avg_hours_per_week", 0.0)),
            "effective_end": summary.get("effective_end"),
            "top_category": top_cat,
        })

    return rows

def build_cumulative_from_weekly(weekly: dict) -> dict:
    """
    weekly: {"weeks": [{"hours": float, ...}, ...]}
    returns: {"weeks": [{"week_index": 1, "weekly_hours": x, "cumulative_hours": y}, ...]}
    """
    weeks = weekly.get("weeks") or []
    out = []
    cum = 0.0
    for i, w in enumerate(weeks, start=1):
        wh = float(w.get("hours") or 0.0)
        cum += wh
        out.append({
            "week_index": i,
            "weekly_hours": wh,
            "cumulative_hours": cum,
        })
    return {"weeks": out}

def get_season_cumulative_series(season, use_local=True) -> dict:
    weekly = get_season_weekly_series(season.start_date, season.end_date, use_local=use_local)
    cum = build_cumulative_from_weekly(weekly)
    return {
        "season_id": season.id,
        "label": season.name,
        "weeks": cum["weeks"],
    }
