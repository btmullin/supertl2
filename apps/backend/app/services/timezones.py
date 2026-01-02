# app/services/timezones.py
from __future__ import annotations

from datetime import datetime, date, timezone
from zoneinfo import ZoneInfo

HOME_TZ_NAME = "America/Chicago"  # fallback / viewer default

def parse_utc_iso(utc_text: str) -> datetime:
    """
    Parse '2025-08-29T19:24:52Z' (or with +00:00) -> aware UTC datetime.
    """
    s = (utc_text or "").strip()
    if not s:
        raise ValueError("empty utc_text")
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def utc_dt_to_tz(dt_utc: datetime, tz_name: str) -> datetime:
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    return dt_utc.astimezone(ZoneInfo(tz_name))

def utc_text_to_local_dt(utc_text: str, tz_name: str | None) -> datetime:
    tz = (tz_name or HOME_TZ_NAME).strip() or HOME_TZ_NAME
    return utc_dt_to_tz(parse_utc_iso(utc_text), tz)

def utc_text_to_local_date(utc_text: str, tz_name: str | None) -> date:
    return utc_text_to_local_dt(utc_text, tz_name).date()

def get_activity_tz_name(activity) -> str:
    """
    Best-effort tz name for canonical Activity-like objects.
    """
    tz = getattr(activity, "tz_name", None)
    if tz and str(tz).strip():
        return str(tz)
    return HOME_TZ_NAME

def activity_local_date(activity) -> date | None:
    """
    Canonical Activity -> local date using activity.tz_name (fallback HOME_TZ_NAME).
    """
    utc_text = getattr(activity, "start_time_utc", None)
    if not utc_text:
        return None
    return utc_text_to_local_date(utc_text, get_activity_tz_name(activity))

def activity_local_dt(activity) -> datetime | None:
    utc_text = getattr(activity, "start_time_utc", None)
    if not utc_text:
        return None
    return utc_text_to_local_dt(utc_text, get_activity_tz_name(activity))
