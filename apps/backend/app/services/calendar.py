# app/analytics/calendar.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from ..db.base import sqla_db
from ..models import Activity, TrainingLogData


@dataclass(frozen=True)
class DayTotals:
    day: date
    hours: float
    distance: float
    activities: int


def _daterange(start: date, end_inclusive: date):
    d = start
    while d <= end_inclusive:
        yield d
        d += timedelta(days=1)


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)
    return start, end


def get_calendar_year_overview(year: int, use_local: bool = True) -> Dict[str, Any]:
    """
    Returns data for a server-rendered "Year Overview" calendar page.

    Output shape:
    {
      "year": 2025,
      "year_totals": {"hours": 123.4, "distance": 567.8, "activities": 210, "training_days": 160},
      "months": [
        {
          "month": 1,
          "label": "JAN",
          "hours": 10.2,
          "distance": 45.6,
          "activities": 12,
          "days": [{"day": 1, "hours": 0.5}, ...],   # daily spark values
        },
        ...
      ]
    }
    """
    # Pick timestamp column for grouping.
    ts_col = None
    if use_local and hasattr(Activity, "start_time_local"):
        ts_col = Activity.start_time_local
    else:
        ts_col = Activity.start_time_utc

    # Distance column can vary by schema. Try a few common names.
    distance_col = None
    for attr in ("distance_m", "distance", "distanceMeters", "distance_meters"):
        if hasattr(Activity, attr):
            distance_col = getattr(Activity, attr)
            break

    # Build aggregation query: group by local date.
    day_expr = func.date(func.datetime(Activity.start_time_utc, "-6 hours"))

    cols = [
        day_expr.label("day"),
        func.coalesce(func.sum(Activity.moving_time_s), 0).label("moving_time_s"),
        func.count(Activity.id).label("activities"),
    ]
    if distance_col is not None:
        cols.append(func.coalesce(func.sum(distance_col), 0).label("distance_sum"))
    else:
        cols.append(func.literal(0).label("distance_sum"))

    rows = (
        sqla_db.session.query(*cols)
        .join(TrainingLogData, TrainingLogData.canonical_activity_id == Activity.id)
        .filter(
            TrainingLogData.isTraining == 1,
            ts_col >= datetime(year, 1, 1),
            ts_col < datetime(year + 1, 1, 1),
        )
        .group_by(day_expr)
        .all()
    )

    # Map date -> totals
    by_day: Dict[date, DayTotals] = {}
    for r in rows:
        # r.day is 'YYYY-MM-DD' string in SQLite
        d = date.fromisoformat(r.day)
        hours = float(r.moving_time_s) / 3600.0
        distance = float(getattr(r, "distance_sum", 0) or 0)

        by_day[d] = DayTotals(
            day=d,
            hours=hours,
            distance=distance,
            activities=int(r.activities),
        )

    # Year totals
    year_hours = sum(dt.hours for dt in by_day.values())
    year_distance = sum(dt.distance for dt in by_day.values())
    year_activities = sum(dt.activities for dt in by_day.values())
    training_days = sum(1 for dt in by_day.values() if dt.hours > 0)

    # Month tiles with daily spark values
    months: List[Dict[str, Any]] = []
    month_labels = ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"]

    for m in range(1, 13):
        ms, me = _month_bounds(year, m)
        days = []
        mh = md = ma = 0.0

        for d in _daterange(ms, me):
            dt = by_day.get(d)
            h = dt.hours if dt else 0.0
            days.append({
                "day": d.day,
                "date": d.isoformat(),
                "hours": h
                })
            if dt:
                mh += dt.hours
                md += dt.distance
                ma += dt.activities

        months.append({
            "month": m,
            "label": month_labels[m - 1],
            "hours": round(mh, 1),
            "distance": round(md, 1),
            "activities": int(ma),
            "days": days,  # 28–31 bars
        })

    return {
        "year": year,
        "year_totals": {
            "hours": round(year_hours, 1),
            "distance": round(year_distance, 1),
            "activities": int(year_activities),
            "training_days": int(training_days),
        },
        "months": months,
    }
