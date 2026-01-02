# app/services/analytics.py
from __future__ import annotations
from dataclasses import dataclass, asdict
from math import fsum
from typing import Iterable, Optional, Any, Callable, Dict, List, Tuple, Any as _Any
from collections import defaultdict, Counter
from collections import OrderedDict
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from .timezones import utc_text_to_local_date, parse_utc_iso, HOME_TZ_NAME

UTC_TZ = ZoneInfo("UTC")

def _get_distance_m(a: _Any) -> Optional[float]:
    """
    Distance in meters, from either:
      - canonical Activity.distance_m
      - StravaActivity.distance
    """
    if hasattr(a, "distance_m"):
        return getattr(a, "distance_m", None)
    return getattr(a, "distance", None)

def _get_moving_s(a: _Any) -> Optional[float]:
    """
    Moving time in seconds, from either:
      - canonical Activity.moving_time_s
      - StravaActivity.movingTimeInSeconds
    """
    if hasattr(a, "moving_time_s"):
        return getattr(a, "moving_time_s", None)
    return getattr(a, "movingTimeInSeconds", None)

def _get_sport(a: _Any) -> str:
    """
    Sport name, from:
      - canonical Activity.sport
      - StravaActivity.sportType
    """
    if hasattr(a, "sport"):
        return getattr(a, "sport") or "Unknown"
    return getattr(a, "sportType", None) or "Unknown"

def get_primary_training_log(a: _Any):
    """
    Return the most relevant TrainingLogData for an activity-like object.

    Works for:
      - StravaActivity with .training_log (1:1)
      - canonical Activity with .training_logs (0..N)
    """
    # StravaActivity-style
    tl = getattr(a, "training_log", None)
    if tl is not None:
        return tl

    # Canonical Activity-style
    tls = getattr(a, "training_logs", None)
    if tls:
        # Prefer one with a category or explicit isTraining flag
        for candidate in tls:
            if getattr(candidate, "categoryId", None) is not None:
                return candidate
            if getattr(candidate, "isTraining", None) in (0, 1):
                return candidate
        # Fallback: first one
        return tls[0]

    return None

def get_local_date_for_activity(a):
    """
    Activity-local calendar date for the activity's start time.

    Canonical Activity: uses start_time_utc + tz_name (fallback HOME_TZ_NAME)
    StravaActivity (legacy): uses startDateTime assumed UTC, converted to HOME_TZ_NAME
    """
    # Canonical Activity path
    utc_text = getattr(a, "start_time_utc", None)
    if utc_text:
        tz_name = getattr(a, "tz_name", None) or HOME_TZ_NAME
        return utc_text_to_local_date(utc_text, tz_name)

    # StravaActivity path (legacy)
    dt = getattr(a, "startDateTime", None)
    if isinstance(dt, datetime):
        # Treat naive as UTC (legacy behavior)
        dt_utc = dt if dt.tzinfo else dt.replace(tzinfo=UTC_TZ)
        # Reuse helper to keep behavior consistent
        # Convert dt_utc back to the same UTC text format your helper expects
        utc_text = dt_utc.astimezone(UTC_TZ).strftime("%Y-%m-%dT%H:%M:%SZ")
        return utc_text_to_local_date(utc_text, HOME_TZ_NAME)

    return None

def get_start_datetime(a: _Any) -> Optional[datetime]:
    """
    Start time as a datetime (naive, typically UTC).

    For StravaActivity: use startDateTime (already a datetime).
    For canonical Activity: parse start_time_utc ISO8601 string
      like '2025-08-29T19:24:52Z'.
    """
    dt = getattr(a, "startDateTime", None)
    if isinstance(dt, datetime):
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC_TZ)

    # canonical case: start_time_utc is a TEXT ISO string
    text = getattr(a, "start_time_utc", None)
    if text:
        try:
            return parse_utc_iso(text)  # returns aware UTC datetime
        except Exception:
            return None


    return None

@dataclass
class ActivitySummary:
    count: int
    total_distance: int
    total_moving_s: int
    total_elevation_m: float
    total_calories: float
    # Averages (unweighted per-activity unless noted)
    avg_distance_m: float
    avg_moving_s: float
    mean_hr_bpm: Optional[float]                 # simple mean of averageHeartRate
    time_weighted_hr_bpm: Optional[float]        # weighted by movingTimeInSeconds
    mean_power_w: Optional[float]                # simple mean of averagePower
    # Maximums
    max_hr_bpm: Optional[int]
    # Counts
    by_sport: Dict[str, int]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

def _safe(values: Iterable[Optional[float]]) -> List[float]:
    return [v for v in values if v is not None]

def _time_weighted_avg(values: Iterable[Optional[float]], weights: Iterable[Optional[float]]) -> Optional[float]:
    v = []
    w = []
    for val, wt in zip(values, weights):
        if val is not None and wt:
            v.append(val)
            w.append(wt)
    if not v or not w or fsum(w) == 0:
        return None
    return fsum(val * wt for val, wt in zip(v, w)) / fsum(w)

def summarize_activities(activities: Iterable[Any]) -> ActivitySummary:
    acts = list(activities)
    n = len(acts)

    # Distances / time: support canonical and Strava
    distances = _safe(_get_distance_m(a) for a in acts)        # meters
    movings   = _safe(_get_moving_s(a) for a in acts)          # seconds

    # These still come from StravaActivity only (canonical doesn't have them yet)
    elevs     = _safe(getattr(a, "elevation", None) for a in acts)   # meters
    calories  = _safe(getattr(a, "calories", None) for a in acts)
    avg_hr    = [getattr(a, "averageHeartRate", None) for a in acts]
    max_hr    = _safe(getattr(a, "maxHeartRate", None) for a in acts)
    avg_power = _safe(getattr(a, "averagePower", None) for a in acts)

    sports    = [_get_sport(a) for a in acts]

    total_distance = sum(distances)
    total_moving   = sum(movings)
    total_elev     = fsum(elevs)
    total_cals     = fsum(calories)

    avg_distance = (total_distance / n) if n else 0.0
    avg_moving   = (total_moving / n) if n else 0.0

    mean_hr = None
    hr_vals = _safe(avg_hr)
    if hr_vals:
        mean_hr = fsum(hr_vals) / len(hr_vals)

    tw_hr = _time_weighted_avg(avg_hr, (_get_moving_s(a) for a in acts))

    mean_pwr = None
    if avg_power:
        mean_pwr = fsum(avg_power) / len(avg_power)

    max_of_max_hr = max(max_hr) if max_hr else None

    by_sport = dict(Counter(sports))

    return ActivitySummary(
        count=n,
        total_distance=total_distance,
        total_moving_s=total_moving,
        total_elevation_m=total_elev,
        total_calories=total_cals,
        avg_distance_m=avg_distance,
        avg_moving_s=avg_moving,
        mean_hr_bpm=mean_hr,
        time_weighted_hr_bpm=tw_hr,
        mean_power_w=mean_pwr,
        max_hr_bpm=max_of_max_hr,
        by_sport=by_sport,
    )

def summarize_by(
    activities: Iterable[Any],
    key: Callable[[Any], Any],
    aggregator: Callable[[Iterable[Any]], ActivitySummary] = summarize_activities,
) -> Dict[Any, ActivitySummary]:
    groups: Dict[Any, List[Any]] = defaultdict(list)
    for a in activities:
        groups[key(a)].append(a)
    return {k: aggregator(v) for k, v in groups.items()}

# Convenience: common grouping keys
def group_by_sport(a: Any) -> str:
    return getattr(a, "sportType", None) or "Unknown"

def group_by_category_id(a: Any) -> Optional[int]:
    tl = get_primary_training_log(a)
    return getattr(tl, "categoryId", None) if tl else None

def group_by_workout_type_id(a: Any) -> Optional[int]:
    tl = get_primary_training_log(a)
    return getattr(tl, "workoutTypeId", None) if tl else None

# Simple humanizers you can use in Jinja
def humanize_duration(seconds: float) -> str:
    return str(timedelta(seconds=int(round(seconds))))

def humanize_km(meters: float, ndigits: int = 1) -> str:
    return f"{round(meters / 1000.0, ndigits)} km"


def _as_date(dt: datetime) -> date:
    if isinstance(dt, datetime):
        return dt.date()
    raise ValueError("startDateTime must be a datetime")

def _week_start(d: date, week_start: int = 0) -> date:
    """
    Return the date of the week's start for `d`.
    week_start=0 => Monday (ISO). week_start=6 => Sunday.
    """
    # Convert Sunday-start to Python's Mon=0..Sun=6
    delta = (d.weekday() - week_start) % 7
    return d - timedelta(days=delta)

def _month_start(d: date) -> date:
    return d.replace(day=1)

def _month_add(d: date, months: int) -> date:
    # add months preserving year rollovers
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    return date(y, m, 1)

def _iter_days(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)

def _iter_weeks(start: date, end: date, week_start: int):
    cur = _week_start(start, week_start)
    stop = _week_start(end, week_start)
    while cur <= stop:
        yield cur
        cur += timedelta(days=7)

def _iter_months(start: date, end: date):
    cur = _month_start(start)
    stop = _month_start(end)
    while cur <= stop:
        yield cur
        cur = _month_add(cur, 1)

def _period_bounds_for_activities(
    activities: Iterable[Any],
    period: str,
    week_start: int,
) -> Optional[Tuple[date, date]]:
    dates = []
    for a in activities:
        d = get_local_date_for_activity(a)
        if isinstance(d, date):
            dates.append(d)

    if not dates:
        return None
    dmin, dmax = min(dates), max(dates)
    if period == "day":
        return (dmin, dmax)
    if period == "week":
        return (_week_start(dmin, week_start), _week_start(dmax, week_start))
    if period == "month":
        return (_month_start(dmin), _month_start(dmax))
    raise ValueError("period must be 'day', 'week', or 'month'")

def _empty_summary() -> ActivitySummary:
    return ActivitySummary(
        count=0,
        total_distance=0,
        total_moving_s=0,
        total_elevation_m=0.0,
        total_calories=0.0,
        avg_distance_m=0.0,
        avg_moving_s=0.0,
        mean_hr_bpm=None,
        time_weighted_hr_bpm=None,
        mean_power_w=None,
        max_hr_bpm=None,
        by_sport={},
    )

def _summarize_grouped(groups: Dict[Any, list]) -> "OrderedDict[Any, ActivitySummary]":
    out: "OrderedDict[Any, ActivitySummary]" = OrderedDict()
    for k in sorted(groups.keys()):
        out[k] = summarize_activities(groups[k])
    return out

def bucket_daily(
    activities: Iterable[Any],
    *,
    start: Optional[date] = None,
    end: Optional[date] = None,
    fill_missing: bool = False,
) -> "OrderedDict[date, ActivitySummary]":
    """Group activities by calendar day (local date of startDateTime)."""
    groups: Dict[date, list] = defaultdict(list)
    for a in activities:
        d = get_local_date_for_activity(a)
        if isinstance(d, date):
            groups[d].append(a)


    # Determine bounds if requested
    if fill_missing:
        bounds = _period_bounds_for_activities(activities, "day", week_start=0)
        if bounds:
            dmin, dmax = bounds
            start = start or dmin
            end = end or dmax

    out = _summarize_grouped(groups)

    if fill_missing and start and end:
        # Fill gaps with zero summaries
        full: "OrderedDict[date, ActivitySummary]" = OrderedDict()
        for d in _iter_days(start, end):
            full[d] = out.get(d, _empty_summary())
        return full

    return out

def bucket_weekly(
    activities: Iterable[Any],
    *,
    week_start: int = 0,          # 0=Mon (ISO), 6=Sun (US-style)
    start: Optional[date] = None, # interpreted as the week's start date
    end: Optional[date] = None,   # interpreted as the week's start date
    fill_missing: bool = False,
) -> "OrderedDict[date, ActivitySummary]":
    """Group activities by week; key is the date of the week's start."""
    groups: Dict[date, list] = defaultdict(list)
    for a in activities:
        d = get_local_date_for_activity(a)
        if isinstance(d, date):
            k = _week_start(d, week_start)
            groups[k].append(a)

    if fill_missing:
        bounds = _period_bounds_for_activities(activities, "week", week_start)
        if bounds:
            wmin, wmax = bounds
            start = start or wmin
            end = end or wmax

    out = _summarize_grouped(groups)

    if fill_missing and start and end:
        full: "OrderedDict[date, ActivitySummary]" = OrderedDict()
        for w in _iter_weeks(start, end, week_start):
            full[w] = out.get(w, _empty_summary())
        return full

    return out

def bucket_monthly(
    activities: Iterable[Any],
    *,
    start: Optional[date] = None, # interpreted as the first of the month
    end: Optional[date] = None,   # interpreted as the first of the month
    fill_missing: bool = False,
) -> "OrderedDict[date, ActivitySummary]":
    """Group activities by calendar month; key is the first day of that month."""
    groups: Dict[date, list] = defaultdict(list)
    for a in activities:
        d = get_local_date_for_activity(a)
        if isinstance(d, date):
            k = _month_start(d)
            groups[k].append(a)

    if fill_missing:
        bounds = _period_bounds_for_activities(activities, "month", week_start=0)
        if bounds:
            mmin, mmax = bounds
            start = start or mmin
            end = end or mmax

    out = _summarize_grouped(groups)

    if fill_missing and start and end:
        full: "OrderedDict[date, ActivitySummary]" = OrderedDict()
        for m in _iter_months(start, end):
            full[m] = out.get(m, _empty_summary())
        return full

    return out

# Optional: label helpers for Jinja/UI
def label_day(d: date) -> str:
    return d.strftime("%Y-%m-%d")

def label_week(start_of_week: date) -> str:
    end = start_of_week + timedelta(days=6)
    return f"{start_of_week:%Y-%m-%d}–{end:%Y-%m-%d}"

def label_month(first_of_month: date) -> str:
    return first_of_month.strftime("%Y-%m")
