# app/analytics/calendar.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from calendar import monthrange

from sqlalchemy import func
from ..db.base import sqla_db
from ..models import Activity, TrainingLogData
from ..services.dates import start_of_week, week_offset_for_date


def _local_day_expr_from_offset_minutes(utc_text_col, offset_minutes_col):
    """
    SQLite: date(datetime(start_time_utc, printf('%+d minutes', utc_offset_minutes)))
    Returns a 'YYYY-MM-DD' string.
    """
    offset = func.coalesce(offset_minutes_col, 0)
    return func.date(func.datetime(utc_text_col, func.printf("%+d minutes", offset)))

def _to_utc_iso(dt: datetime) -> str:
    """
    Convert aware datetime to your canonical text format: YYYY-MM-DDTHH:MM:SSZ
    """
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc_bounds_for_local_date_range(
    start_local: date,
    end_local_inclusive: date,
) -> tuple[str, str]:
    """
    Return a conservative UTC bounding box [start_utc, end_utc_excl) that
    definitely contains all activities whose *local* date is in [start_local, end_local].

    We do not know per-row timezone in SQL, so we widen bounds by ~1 day on both ends.
    """
    # Conservative: include any possible tz shift.
    # start_local at 00:00 local could be as late as UTC+14 -> subtract 14h => previous UTC day
    # end_local at 23:59 local could be as early as UTC-12 -> add 12h => next UTC day
    start_utc = datetime.combine(start_local, datetime.min.time(), tzinfo=timezone.utc) - timedelta(days=1)
    end_utc_excl = datetime.combine(end_local_inclusive + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc) + timedelta(days=1)
    return _to_utc_iso(start_utc), _to_utc_iso(end_utc_excl)

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
    day_expr = _local_day_expr_from_offset_minutes(Activity.start_time_utc, Activity.utc_offset_minutes)

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
            day_expr >= f"{year:04d}-01-01",
            day_expr <= f"{year:04d}-12-31",
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

def get_calendar_month_overview(year: int, month: int, use_local: bool = True):
    # Bounds for the month
    days_in_month = monthrange(year, month)[1]
    month_start = date(year, month, 1)
    month_end = date(year, month, days_in_month)

    # Month grid starts Monday of the week containing the 1st
    grid_start = start_of_week(month_start)
    # Grid ends Sunday of the week containing the last day
    grid_end = start_of_week(month_end) + timedelta(days=6)

    # Aggregate activities by local day within the grid range
    # We filter by UTC timestamps broadly (string compare works with your ISOZ)
    start_utc = f"{grid_start.isoformat()}T00:00:00Z"
    end_utc_excl = f"{(grid_end + timedelta(days=1)).isoformat()}T00:00:00Z"

    day_expr = _local_day_expr_from_offset_minutes(Activity.start_time_utc, Activity.utc_offset_minutes)

    rows = (
        sqla_db.session.query(
            day_expr.label("day"),
            func.coalesce(func.sum(Activity.moving_time_s), 0).label("moving_time_s"),
            func.coalesce(func.sum(Activity.distance_m), 0).label("distance_m"),
            func.count(Activity.id).label("activities"),
        )
        .join(TrainingLogData, TrainingLogData.canonical_activity_id == Activity.id)
        .filter(
            TrainingLogData.isTraining == 1,
            day_expr >= grid_start.isoformat(),
            day_expr <= grid_end.isoformat(),
        )
        .group_by(day_expr)
        .all()
    )

    by_day = {}
    for r in rows:
        d = date.fromisoformat(r.day)  # 'YYYY-MM-DD'
        by_day[d] = {
            "moving_time_s": int(r.moving_time_s or 0),
            "distance_m": float(r.distance_m or 0.0),
            "activities": int(r.activities or 0),
        }

    # Build weeks (each week: 7 days)
    weeks = []
    cur = grid_start
    while cur <= grid_end:
        week_start = cur
        days = []
        for i in range(7):
            d = week_start + timedelta(days=i)
            agg = by_day.get(d, None)
            hours = (agg["moving_time_s"] / 3600.0) if agg else 0.0
            dist_m = agg["distance_m"] if agg else 0.0
            acts = agg["activities"] if agg else 0

            days.append({
                "date": d,
                "iso": d.isoformat(),
                "day": d.day,
                "in_month": (d.month == month),
                "hours": round(hours, 1),
                "distance_m": dist_m,
                "activities": acts,
            })

        week_hours = sum(d["hours"] for d in days)
        week_dist_m = sum(d["distance_m"] for d in days)
        week_acts = sum(d["activities"] for d in days)

        week_label = week_start.strftime("%b %-d")

        weeks.append({
            "week_start": week_start,
            "week_offset": week_offset_for_date(week_start),
            "week_label": week_label,
            "days": days,
            "week_totals": {
                "hours": round(week_hours, 1),
                "distance_m": week_dist_m,
                "activities": week_acts,
            },
        })
        cur += timedelta(days=7)

    # Totals for the month (only days in month)
    month_hours = 0.0
    month_dist_m = 0.0
    month_acts = 0
    for d in (month_start + timedelta(days=i) for i in range(days_in_month)):
        agg = by_day.get(d)
        if agg:
            month_hours += agg["moving_time_s"] / 3600.0
            month_dist_m += agg["distance_m"]
            month_acts += agg["activities"]

    month_labels = ["January","February","March","April","May","June","July","August","September","October","November","December"]

    return {
        "year": year,
        "month": month,
        "month_label": month_labels[month - 1],
        "month_totals": {
            "hours": round(month_hours, 1),
            "distance_m": month_dist_m,
            "activities": month_acts,
        },
        "weeks": weeks,
    }