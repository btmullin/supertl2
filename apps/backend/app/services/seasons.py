from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional, List, Dict, Any

from sqlalchemy import func

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

def get_season_traininglog_category_breakdown(season_start_dt, season_end_dt_excl, use_local=True):
    """
    Breakdown of hours by TrainingLogData.categoryId (Category.name),
    summed using Activity.moving_time_s.

    Includes an 'Uncategorized' bucket for activities missing TrainingLogData
    or missing categoryId.
    """
    ts_col = Activity.start_time_local if use_local and hasattr(Activity, "start_time_local") else Activity.start_time_utc

    rows = (
        sqla_db.session.query(
            Category.name.label("label"),
            func.coalesce(func.sum(Activity.moving_time_s), 0).label("seconds"),
        )
        .join(
            TrainingLogData,
            TrainingLogData.canonical_activity_id == Activity.id,
        )
        .join(
            Category,
            Category.id == TrainingLogData.categoryId,
        )
        .filter(
            TrainingLogData.isTraining == 1,
            ts_col >= season_start_dt,
            ts_col < season_end_dt_excl,
        )
        .group_by(Category.name)
        .order_by(func.sum(Activity.moving_time_s).desc())
        .all()
    )

    total_seconds = sum(int(r.seconds or 0) for r in rows) or 0

    items = []
    for r in rows:
        sec = int(r.seconds or 0)
        hours = sec / 3600.0
        pct = (sec / total_seconds * 100.0) if total_seconds else 0.0
        items.append({"label": r.label, "hours": hours, "percent": pct})

    return {"total_hours": total_seconds / 3600.0, "items": items}