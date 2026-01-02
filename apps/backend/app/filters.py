""" This module provides utility functions for formatting durations, datetime strings, 
time-only strings, and distances in a human-readable format. Additionally, it includes 
a function to register these formatting utilities as Jinja2 filters for use in a Flask 
application.

Functions:
    - format_duration(seconds): Converts a duration in seconds into a formatted string 
      in the format HH:MM:SS or MM:SS.

    - format_datetime_pretty(value): Formats a datetime string into a more human-readable 
      format, e.g., "Jun 19, 2025 9:01 PM".

    - format_timeonly(value): Extracts and formats the time portion of a datetime string 
      into a time-only representation, e.g., "9:01 PM".

    - format_kilometers(meters): Converts a distance in meters to kilometers and formats 
      it as a string with two decimal places, followed by " km".

    - register_filters(app): Registers the above utility functions as Jinja2 filters 
      in a Flask application's Jinja environment.
"""

from flask import g
from .services.category_paths import build_category_cache, category_full_path_from_id
from .services.analytics import get_primary_training_log
from .models.category import Category
from .db.base import sqla_db
from .services.timezones import (
    HOME_TZ_NAME,
    utc_text_to_local_dt,
    get_activity_tz_name,
)

def utc_to_local(utc_text):
    """
    Backwards-compatible filter:
    Converts a UTC ISO8601 string into a datetime in HOME_TZ_NAME.
    (Does NOT use activity tz_name because it only receives a string.)
    """
    if not utc_text:
        return None
    return utc_text_to_local_dt(utc_text, HOME_TZ_NAME)

def activity_localtime(activity):
    """
    New preferred filter:
    Accepts a canonical Activity (or anything with start_time_utc + tz_name)
    and converts start_time_utc into the activity's local timezone.
    """
    if activity is None:
        return None

    utc_text = getattr(activity, "start_time_utc", None)
    if not utc_text:
        return None

    tz_name = get_activity_tz_name(activity)
    return utc_text_to_local_dt(utc_text, tz_name)

def _get_category_cache():
    cache = getattr(g, "_category_cache", None)
    if cache is None:
        cache = g._category_cache = build_category_cache(sqla_db.session)
    return cache

def format_duration(seconds):
    """
    Converts a duration in seconds into a formatted string in the format HH:MM:SS or MM:SS.

    Args:
        seconds (int): The duration in seconds to format.

    Returns:
        str: A string representing the formatted duration. If the duration is less than an hour,
             the format will be MM:SS. Otherwise, the format will be HH:MM:SS.
    """
    try:
        seconds = int(float(seconds))
    except (TypeError, ValueError):
        raise TypeError("Parameter seconds must be int-convertible")
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours == 0:
        return f"{minutes:02}:{secs:02}"

    return f"{hours}:{minutes:02}:{secs:02}"

def format_datetime_pretty(value):
    """
    Formats a datetime object into a human-readable string.

    Args:
        value (datetime): A datetime object.

    Returns:
        str: The formatted datetime string in the format "MMM DD, YYYY h:mm AM/PM",
             e.g., "Jun 19, 2025 9:01 PM". If the input is not a datetime object,
             the original value is returned with an 'err' prefix.
    """
    try:
        return value.strftime("%b %d, %Y %-I:%M %p")  # e.g., Jun 19, 2025 9:01 PM
    except (AttributeError, ValueError, TypeError):
        return value  # Fallback if something goes wrong

def format_timeonly(value):
    """
    Formats a datetime string into a time-only representation.

    Args:
        value (datetime): A datetime object.

    Returns:
        str: A formatted string representing the time in the format "%-I:%M %p" 
             (e.g., "9:01 PM"). If the input is invalid or an error occurs, 
             the original value is returned as a fallback.
    """
    try:
        return value.strftime("%-I:%M %p")  # e.g., Jun 19, 2025 09:01 PM
    except (ValueError, TypeError):
        return value  # Fallback if something goes wrong

def format_kilometers(meters, decimals=2):
    """
    Converts a distance in meters to a formatted string in kilometers.

    Args:
        meters (int or float): The distance in meters to be converted.

    Returns:
        str: A string representing the distance in kilometers with two decimal places,
             followed by " km". If the input is 0, returns "--". If the input is invalid
             (e.g., not a number), returns the original input.
    """
    try:
        if meters == 0:
            return "--"
        km = float(meters) / 1000
        return f"{km:.{decimals}f}"
    except (ValueError, TypeError):
        return meters

def describe_object(obj):
    out = f"<p>Object: {type(obj).__name__}</p>"
    out += f"<p>Type: {type(obj)}</p>"
    out += f"<p>Attributes:</p>"
    for attr in dir(obj):
        if not attr.startswith("__"):
            value = getattr(obj, attr)
            out = out + f"<p>{attr}: {type(value).__name__} : {value}</p>"
    return out

def displaySportOrCategory(activity):
    """
    Returns the sport type if no associated training log is found,
    otherwise returns the category in the primary training log.

    Works for StravaActivity and canonical Activity.
    """
    tl = get_primary_training_log(activity)
    if tl is not None and getattr(tl, "category", None):
        return tl.category.full_path()

    # Fallback to sport field on canonical or Strava
    sport = getattr(activity, "sport", None) or getattr(activity, "sportType", None)
    return sport or "Unknown"

def category_path_filter(cat_or_id, sep=" : "):
    # If a Category object is provided, use its method (already in your model)
    if isinstance(cat_or_id, Category):
        return cat_or_id.full_path()
    # Otherwise treat as an id
    cache = _get_category_cache()
    return category_full_path_from_id(cat_or_id, cache, sep=sep)

def register_filters(app):
    # Deferred import to avoid circular import at module import time
    
    """
    Registers the formatting utility functions as Jinja2 filters in a Flask application.

    Args:
        app (Flask): The Flask application instance to register the filters with.
    """
    app.jinja_env.filters['format_duration'] = format_duration
    app.jinja_env.filters["pretty_datetime"] = format_datetime_pretty
    app.jinja_env.filters["km"] = format_kilometers
    app.jinja_env.filters["time_only"] = format_timeonly
    app.jinja_env.filters["describe_object"] = describe_object
    app.jinja_env.filters["displaySportOrCategory"] = displaySportOrCategory
    app.jinja_env.filters["category_path"] = category_path_filter
    app.jinja_env.filters["localtime"] = utc_to_local
    app.jinja_env.filters["activity_localtime"] = activity_localtime

