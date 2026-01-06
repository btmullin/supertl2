"""Primary views of the flask application."""

import os
import sys
import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from collections import defaultdict, OrderedDict
from flask import (
    Blueprint,
    render_template,
    request,
    url_for,
    redirect,
    current_app,
    flash,
)
from sqlalchemy import func, text
from sqlalchemy.orm import joinedload
from app.db.db import (
    import_strava_data,
    get_canonical_activities,
    get_canonical_activity_count,
    get_canonical_id_for_strava_activity,
    get_strava_activity_id_for_canonical_activity
)
from app.services.analytics import (
    summarize_activities,
    bucket_daily,
    summarize_by,
    group_by_category_id,
    group_by_sport,
    get_start_datetime,
    get_local_date_for_activity,
    get_primary_training_log,
)
from app.services.seasons import (
    get_season_summary,
    get_season_weekly_series,
    get_season_traininglog_category_breakdown,
    get_season_comparison_rows,
    get_season_cumulative_series,
    get_season_weekly_stacked_by_category,
)
from app.services.calendar import (
    get_calendar_year_overview,
    get_calendar_month_overview,
    get_available_years
)
from app.services.timezones import activity_local_dt
from util.canonical.backfill_new_strava_to_canonical import backfill_new_strava
from util.canonical.backfill_activity_timezones_util import backfill_activity_timezones, HOME_TZ
from .forms.EditActivityForm import EditActivityForm
from .forms.CategoryForm import CategoryForm
from .forms.ActivityQueryForm import ActivityQueryFilterForm
from .forms.season_forms import SeasonCreateForm
from .models import StravaActivity, WorkoutType, TrainingLogData, Category, Activity, SportTracksActivity, Season
from .db.base import sqla_db
from .filters import category_path_filter

PER_PAGE = 25

views = Blueprint("views", __name__)

def _utc_bounds_for_local_week(start_of_week, end_of_week):
    """
    Conservative bounding box: include one extra day on both ends.
    This ensures we fetch anything that might map into the local week after tz conversion.
    """
    start_utc = datetime.combine(start_of_week, datetime.min.time(), tzinfo=timezone.utc) - timedelta(days=1)
    end_utc_excl = datetime.combine(end_of_week + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc) + timedelta(days=1)
    start_utc_s = start_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_utc_excl_s = end_utc_excl.strftime("%Y-%m-%dT%H:%M:%SZ")
    return start_utc_s, end_utc_excl_s

def _today_local_date() -> date:
    return datetime.now(ZoneInfo("America/Chicago")).date()

def _week_start(d: date, week_start: int = 0) -> date:
    delta = (d.weekday() - week_start) % 7
    return d - timedelta(days=delta)

def _week_index(season_start: date, day: date, week_start: int = 0) -> int:
    # Week index is 1-based, aligned to your weekly bucketing (Monday start)
    start_ws = _week_start(season_start, week_start)
    day_ws = _week_start(day, week_start)
    return int(((day_ws - start_ws).days // 7) + 1)

def get_or_create_training_log(activity_id: str) -> TrainingLogData:
    """
    Fetch TrainingLogData for the given Strava activityId, or create it if missing.
    Also ensure canonical_activity_id is populated if we can find a canonical activity.
    """
    training_data = sqla_db.session.get(TrainingLogData, activity_id)
    if not training_data:
        training_data = TrainingLogData(activityId=activity_id)
        sqla_db.session.add(training_data)

    if training_data.canonical_activity_id is None:
        canonical_id = get_canonical_id_for_strava_activity(activity_id)
        if canonical_id is not None:
            training_data.canonical_activity_id = canonical_id

    return training_data

def allowed_file(filename):
    """Check if the file has an allowed extension."""
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower()
        in current_app.config["ALLOWED_EXTENSIONS"]
    )

from datetime import datetime, timedelta, timezone

def _utc_bounds_for_local_date_range(start_local, end_local_inclusive):
    start_utc = datetime.combine(start_local, datetime.min.time(), tzinfo=timezone.utc) - timedelta(days=1)
    end_utc_excl = datetime.combine(end_local_inclusive + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc) + timedelta(days=1)
    return (
        start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        end_utc_excl.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )

def build_weekly_time_series(center_week_start, weeks_before: int = 5, weeks_after: int = 5):
    """
    Build a time series of weekly total training time (hours) around a given week.

    - center_week_start: date (typically a Monday) of the "current" week.
    - weeks_before / weeks_after: number of weeks to show on each side.

    Returns:
      {
        "weeks": [
          {"week_start": "2025-11-03", "label": "Nov 03", "total_hours": 5.5},
          ...
        ],
        "current_index": 5,  # index in weeks[] of center_week_start
      }
    """
    if isinstance(center_week_start, datetime):
        center_week_start = center_week_start.date()

    # Normalize to Monday just in case
    center_week_start = center_week_start - timedelta(days=center_week_start.weekday())

    window_start = center_week_start - timedelta(weeks=weeks_before)
    # include the full last week (Mon..Sun) on the right
    window_end = center_week_start + timedelta(weeks=weeks_after, days=6)

    # Fetch training activities in the window (canonical Activity + TrainingLogData.isTraining)
    start_utc_s, end_utc_excl_s = _utc_bounds_for_local_date_range(window_start, window_end)

    candidate_activities = (
        sqla_db.session.query(Activity)
        .join(TrainingLogData, TrainingLogData.canonical_activity_id == Activity.id)
        .filter(
            TrainingLogData.isTraining == 1,
            Activity.start_time_utc >= start_utc_s,
            Activity.start_time_utc < end_utc_excl_s,
        )
        .order_by(Activity.start_time_utc)
        .all()
    )

    # Initialize all week slots with zero seconds
    per_week_seconds = {}
    for offset in range(-weeks_before, weeks_after + 1):
        ws = center_week_start + timedelta(weeks=offset)
        per_week_seconds[ws] = 0

    # Bucket activities by LOCAL week (using analytics helper)
    for a in candidate_activities:
        local_date = get_local_date_for_activity(a)
        if local_date is None:
            continue

        week_start = local_date - timedelta(days=local_date.weekday())
        if week_start not in per_week_seconds:
            # outside our 11-week window
            continue

        moving_s = getattr(a, "moving_time_s", None)
        if moving_s is None:
            moving_s = getattr(a, "elapsed_time_s", 0) or 0

        per_week_seconds[week_start] += moving_s

    # Build ordered list for the chart
    sorted_weeks = sorted(per_week_seconds.keys())
    weeks = []
    for ws in sorted_weeks:
        total_hours = per_week_seconds[ws] / 3600.0
        weeks.append(
            {
                "week_start": ws.isoformat(),
                "label": ws.strftime("%b %d"),
                "total_hours": total_hours,
            }
        )

    current_index = (
        sorted_weeks.index(center_week_start)
        if center_week_start in sorted_weeks
        else 0
    )

    return {"weeks": weeks, "current_index": current_index}

def get_dashboard_context(week_offset=0):
    today = datetime.today().date()
    start_of_week = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
    end_of_week = start_of_week + timedelta(days=6)

    start_utc_s, end_utc_excl_s = _utc_bounds_for_local_week(start_of_week, end_of_week)

    candidate_activities = (
        sqla_db.session.query(Activity)
        .join(TrainingLogData, TrainingLogData.canonical_activity_id == Activity.id)
        .filter(
            TrainingLogData.isTraining == 1,
            Activity.start_time_utc >= start_utc_s,
            Activity.start_time_utc < end_utc_excl_s,
        )
        .order_by(Activity.start_time_utc)
        .all()
    )

    # Now apply the *true* week membership test using activity-local date
    activities_by_day = defaultdict(list)
    activities = []
    for a in candidate_activities:
        day = get_local_date_for_activity(a)
        if day is None:
            continue
        if start_of_week <= day <= end_of_week:
            activities_by_day[day].append(a)
            activities.append(a)


    days = [start_of_week + timedelta(days=i) for i in range(7)]

    daily_summaries = {
        day: summarize_activities(activities_by_day[day])
        for day in days
    }
    week_summary = summarize_activities(activities)

    # Per-category (training-log hierarchy) summaries for this week
    # Key is categoryId; we’ll turn that into a full path in the template.
    category_summaries = summarize_by(
        activities,
        key=group_by_category_id,
    )

    # Get previous week summaries
    previous_week_start = start_of_week - timedelta(weeks=1)
    previous_week_end = end_of_week - timedelta(weeks=1)
    prev_start_utc_s, prev_end_utc_excl_s = _utc_bounds_for_local_week(previous_week_start, previous_week_end)

    previous_candidates = (
        sqla_db.session.query(Activity)
        .join(TrainingLogData, TrainingLogData.canonical_activity_id == Activity.id)
        .filter(
            TrainingLogData.isTraining == 1,
            Activity.start_time_utc >= prev_start_utc_s,
            Activity.start_time_utc < prev_end_utc_excl_s,
        )
        .order_by(Activity.start_time_utc)
        .all()
    )

    previous_activities = []
    for a in previous_candidates:
        day = get_local_date_for_activity(a)
        if day is None:
            continue
        if previous_week_start <= day <= previous_week_end:
            previous_activities.append(a)

    previous_week_summary = summarize_activities(previous_activities)

    # Weekly time series for the bar chart (about 11 weeks centered on this one)
    weekly_series = build_weekly_time_series(start_of_week, weeks_before=5, weeks_after=5)

    return {
        "start_of_week": start_of_week,
        "end_of_week": end_of_week,
        "activities_by_day": activities_by_day,
        "daily_summaries": daily_summaries,
        "week_summary": week_summary,
        "previous_week_summary": previous_week_summary,
        "category_summaries": category_summaries,
        "weekly_series": weekly_series,
        "days": days,
        "week_offset": week_offset,
    }

@views.route("/")
@views.route("/dashboard")
def dashboard():
    week_offset = int(request.args.get("week_offset", 0))

    context = get_dashboard_context(week_offset)
    return render_template(
        "dashboard.html",
        **context
    )

@views.route("/calendar")
def calendar_view():
    view = request.args.get("view", "year")

    today = date.today()
    year = request.args.get("year", type=int) or today.year

    if view == "month":
        month = request.args.get("month", type=int) or today.month
        data = get_calendar_month_overview(year=year, month=month, use_local=True)

        return render_template(
            "calendar_month.html",
            year=data["year"],
            month=data["month"],
            month_label=data["month_label"],
            month_totals=data["month_totals"],
            weeks=data["weeks"],
            now_month=today.month,
            now_year=today.year,
        )

    # default: year
    available_years = get_available_years(use_local=True)
    available_years = sorted(available_years, reverse=True)
    if available_years and year not in available_years:
        # pick a sane default: most recent year with data
        year = available_years[-1]
    data = get_calendar_year_overview(year=year, use_local=True)
    return render_template(
        "calendar_year.html",
        year=data["year"],
        year_totals=data["year_totals"],
        months=data["months"],
        now_month=today.month,
        now_year=today.year,
        available_years=available_years,
    )


@views.route("/analysis")
def analysis():
    return render_template("analysis.html")


@views.route("/gear")
def gear():
    return render_template("gear.html")


@views.route("/test")
def test():
    activity = sqla_db.session.query(StravaActivity).first()
    return render_template("test.html", activity=activity)

@views.route("/activity/edit", methods=["GET", "POST"])
def edit_activity():
    next_url = request.args.get("next") or url_for("views.dashboard")

    # ---- Interpret id as canonical Activity.id ----
    canonical_id_param = request.args.get("id")
    if not canonical_id_param:
        flash("Missing activity ID.")
        return redirect(url_for("views.dashboard"))

    try:
        canonical_id = int(canonical_id_param)
    except ValueError:
        flash("Invalid activity ID.")
        return redirect(url_for("views.dashboard"))

    # Ensure the canonical activity exists
    canonical_activity = sqla_db.session.get(Activity, canonical_id)
    if not canonical_activity:
        flash("Activity not found.")
        return redirect(next_url)

    # ---- Sources: Strava and SportTracks (if any) ----
    all_sources = list(canonical_activity.sources or [])
    strava_sources = [s for s in all_sources if s.source == "strava"]
    sporttracks_sources = [s for s in all_sources if s.source == "sporttracks"]

    # Optional Strava activity (for rich details, map, streams)
    strava_activity = None
    summary_polyline = ""
    if strava_sources:
        strava_id = strava_sources[0].source_activity_id
        strava_activity = sqla_db.session.get(StravaActivity, strava_id)
        if strava_activity:
            activity_data = strava_activity.data or {}
            summary_polyline = activity_data.get("map", {}).get("summary_polyline", "")

    # Optional SportTracks activity link could be constructed from source_activity_id
    sporttracks_activity = None
    if sporttracks_sources:
        sporttracks_id = sporttracks_sources[0].source_activity_id
        sporttracks_activity = sqla_db.session.get(SportTracksActivity, sporttracks_id)

    form = EditActivityForm()

    # Populate select fields
    form.workoutTypeId.choices = [(0, "—")] + [
        (w.id, w.name)
        for w in sqla_db.session.query(WorkoutType).order_by(WorkoutType.name).all()
    ]

    # Recursive category path query
    category_paths = sqla_db.session.execute(text("""
        WITH RECURSIVE category_path(id, name, parent_id, full_path) AS (
            SELECT id, name, parent_id, name
            FROM Category
            WHERE parent_id IS NULL
            UNION ALL
            SELECT c.id, c.name, c.parent_id, cp.full_path || ' : ' || c.name
            FROM Category c
            JOIN category_path cp ON c.parent_id = cp.id
        )
        SELECT id, full_path FROM category_path
        ORDER BY full_path
    """)).fetchall()
    form.categoryId.choices = [(0, "—")] + [(row.id, row.full_path) for row in category_paths]

    # ---------- TrainingLogData helpers (canonical-centric) ----------

    def _find_training_log_for_canonical():
        """
        Try to locate an existing TrainingLogData for this canonical activity.
        1) Prefer canonical_activity_id match
        2) Fall back to Strava-based record if present
        """
        tl = (
            sqla_db.session.query(TrainingLogData)
            .filter(TrainingLogData.canonical_activity_id == canonical_activity.id)
            .one_or_none()
        )
        if tl:
            return tl

        if strava_sources:
            strava_id = strava_sources[0].source_activity_id
            return sqla_db.session.get(TrainingLogData, strava_id)

        return None

    def _get_or_create_training_log_for_canonical():
        """
        Ensure there is a TrainingLogData row associated with this canonical activity.
        - If found (by canonical or by Strava id), ensure canonical_activity_id is set.
        - If not found, create one:
            * Use Strava activityId if available
            * Otherwise synthesize an ID from the canonical id
        """
        tl = _find_training_log_for_canonical()
        if tl is None:
            if strava_sources:
                activity_id = strava_sources[0].source_activity_id
            else:
                activity_id = f"canon-{canonical_activity.id}"

            tl = TrainingLogData(
                activityId=activity_id,
                canonical_activity_id=canonical_activity.id,
            )
            sqla_db.session.add(tl)
        else:
            if tl.canonical_activity_id is None:
                tl.canonical_activity_id = canonical_activity.id

        return tl

    # ---------- GET: prefill form ----------
    if request.method == "GET":
        training_log = _find_training_log_for_canonical()

        # Hidden field can carry canonical id (not currently used server-side)
        form.activityId.data = canonical_id

        if training_log:
            form.workoutTypeId.data = training_log.workoutTypeId or 0
            form.categoryId.data = training_log.categoryId or 0
            form.notes.data = training_log.notes
            form.tags.data = training_log.tags
            form.isTraining.data = (
                training_log.isTraining if training_log.isTraining is not None else 2
            )

        form.activityName.data = canonical_activity.name

        return render_template(
            "editactivity.html",
            form=form,
            canonical_activity=canonical_activity,
            strava_activity=strava_activity,
            sporttracks_sources=sporttracks_sources,
            sporttracks_activity=sporttracks_activity,
            summary_polyline=summary_polyline,
            training_log=training_log,
        )

    # ---------- POST: buttons & save ----------

    # Cancel: do nothing
    if form.cancel.data:
        return redirect(next_url)

    # Convenience helper for quick actions
    def _quicklog():
        return _get_or_create_training_log_for_canonical()

    # Quick button: General Trail Run
    if form.general_trail.data:
        training_data = _quicklog()
        training_data.workoutTypeId = 1   # General
        training_data.categoryId = 10     # Trail Running
        training_data.isTraining = 1
        sqla_db.session.commit()
        return redirect(next_url)

    # Quick button: General MTB / Gravel / Virtual bike
    if form.general_mountain_bike.data or form.general_gravel_bike.data or form.general_virtual_bike.data:
        training_data = _quicklog()
        training_data.workoutTypeId = 1  # General
        if form.general_gravel_bike.data:
            training_data.categoryId = 13  # Gravel Biking
        elif form.general_mountain_bike.data:
            training_data.categoryId = 14  # Mountain Biking
        else:
            training_data.categoryId = 18  # Virtual Biking
        training_data.isTraining = 1
        sqla_db.session.commit()
        return redirect(next_url)

    # Quick button: Strength
    if form.strength.data:
        training_data = _quicklog()
        training_data.workoutTypeId = 6   # Strength
        training_data.categoryId = 15     # Strength Training
        training_data.isTraining = 1
        sqla_db.session.commit()
        return redirect(next_url)

    # Quick button: L3 roller (classic or skate)
    if form.l3_classic_roller.data or form.l3_skate_roller.data:
        training_data = _quicklog()
        training_data.workoutTypeId = 2  # L3
        if form.l3_classic_roller.data:
            training_data.categoryId = 7  # L3 Classic Roller Ski
        else:
            training_data.categoryId = 6  # L3 Skate Roller Ski
        training_data.isTraining = 1
        sqla_db.session.commit()
        return redirect(next_url)

    # Quick button: General Skate/Classic snow ski
    if form.general_skate_ski.data or form.general_classic_ski.data:
        training_data = _quicklog()
        training_data.workoutTypeId = 1  # General
        if form.general_classic_ski.data:
            training_data.categoryId = 5  # Classic Snow Ski
        else:
            training_data.categoryId = 4  # Skate Snow Ski
        training_data.isTraining = 1
        sqla_db.session.commit()
        return redirect(next_url)

    # Normal submit: use full form values
    if form.validate_on_submit():
        training_data = _get_or_create_training_log_for_canonical()

        training_data.workoutTypeId = form.workoutTypeId.data or None
        training_data.categoryId = form.categoryId.data or None
        training_data.notes = form.notes.data
        training_data.tags = form.tags.data
        training_data.isTraining = form.isTraining.data

        # Update canonical activity name (if changed)
        new_name = (form.activityName.data or "").strip()
        if new_name and new_name != canonical_activity.name:
            canonical_activity.name = new_name
    
        sqla_db.session.commit()
        flash("Metadata updated.")
        return redirect(next_url)

    # If we get here, POST didn't match any button/validation; redisplay form
    training_log = _find_training_log_for_canonical()
    return render_template(
        "editactivity.html",
        form=form,
        canonical_activity=canonical_activity,
        strava_activity=strava_activity,
        sporttracks_sources=sporttracks_sources,
        sporttracks_activity=sporttracks_activity,
        summary_polyline=summary_polyline,
        training_log=training_log,
    )

@views.route("/admin/import-strava")
def import_strava():
    import_strava_data()

    from apps.backend.app.db.db import STL_DB
    result = backfill_new_strava(db_path=STL_DB)
    backfill_activity_timezones(db_path=STL_DB, assumed_tz=HOME_TZ, force=False)

    flash(f"Imported new activities.")
    return redirect(url_for("views.activitylist"))

@views.route("/admin/seasons", methods=["GET", "POST"])
def admin_seasons():
    form = SeasonCreateForm()

    if form.validate_on_submit():
        season = Season(
            name=form.name.data.strip(),
            start_date=form.start_date.data,
            end_date=form.end_date.data,
            is_active=bool(form.is_active.data),
        )
        sqla_db.session.add(season)
        sqla_db.session.commit()
        flash("Season created.", "success")
        return redirect(url_for("views.admin_seasons"))

    seasons = Season.query.order_by(Season.start_date.desc()).all()
    return render_template("admin_seasons.html", form=form, seasons=seasons)

def _get_default_season_id():
    s = (Season.query
         .filter(Season.is_active == True)
         .order_by(Season.start_date.desc())
         .first())
    return s.id if s else None


def _as_datetime_start(d):
    return datetime(d.year, d.month, d.day, 0, 0, 0)

def _as_datetime_end_exclusive(d):
    nd = d + timedelta(days=1)
    return datetime(nd.year, nd.month, nd.day, 0, 0, 0)

@views.route("/seasons")
def season_view():
    seasons = Season.query.order_by(Season.start_date.desc()).all()

    season_id = request.args.get("season_id", type=int) or _get_default_season_id()
    selected = Season.query.get(season_id) if season_id else None

    summary = None
    weekly = None
    breakdown = None

    compare_ids = request.args.getlist("compare_id", type=int)
    compare_ids_param = request.args.get("compare_id", "").strip()
    if compare_ids_param:
        for part in compare_ids_param.split(","):
            part = part.strip()
            if part.isdigit():
                compare_ids.append(int(part))
    compare_ids = sorted(set(compare_ids))
    if selected:
        compare_ids = [cid for cid in compare_ids if cid != selected.id]
    
    if selected:
        summary = get_season_summary(selected.start_date, selected.end_date, use_local=True)
        weekly = get_season_weekly_series(selected.start_date, selected.end_date, use_local=True)
        stacked_weekly = get_season_weekly_stacked_by_category(
            selected.start_date,
            selected.end_date,
            use_local=True,
            rollup_depth=0
        )
        start_dt = _as_datetime_start(selected.start_date)
        end_dt_excl = _as_datetime_end_exclusive(selected.end_date)
        breakdown = get_season_traininglog_category_breakdown(start_dt, end_dt_excl, use_local=True, rollup_depth=0, min_percent=2.0)

    compare_rows = get_season_comparison_rows(seasons)

    overlay = None
    if selected:
        primary = get_season_cumulative_series(selected, use_local=True)

        # If in progress, mark "to date" and add a week marker
        today = _today_local_date()
        in_progress = today < selected.end_date
        current_week_idx = _week_index(selected.start_date, min(today, selected.end_date), week_start=0) if in_progress else None

        compare_seasons = [s for s in seasons if s.id in compare_ids and s.id != selected.id]
        others = [get_season_cumulative_series(s, use_local=True) for s in compare_seasons]

        overlay = {
            "primary": primary,
            "others": others,
            "primary_in_progress": in_progress,
            "primary_current_week": current_week_idx,  # 1-based
        }

    return render_template(
        "season.html",
        seasons=seasons,
        selected_season=selected,
        season_id=season_id,
        summary=summary,
        weekly=weekly,
        breakdown=breakdown,
        compare_rows=compare_rows,
        compare_ids=compare_ids,
        overlay=overlay,
        stacked_weekly=stacked_weekly,
    )

@views.route("/activitylist")
def activitylist():
    page = request.args.get("page", 1, type=int)
    only_missing = request.args.get("missing_training_log", "0") == "1"

    offset = (page - 1) * PER_PAGE

    rows = get_canonical_activities(
        limit=PER_PAGE,
        offset=offset,
        only_missing_training_log=only_missing,
    )

    total = get_canonical_activity_count(only_missing_training_log=only_missing)
    total_pages = (total + PER_PAGE - 1) // PER_PAGE if total > 0 else 1

    return render_template(
        "activitylist.html",
        activities=rows,
        page=page,
        total_pages=total_pages,
        missing_training_log=only_missing,
    )

@views.route("/query", methods=["GET"])
def activity_query():
    # Bind from querystring; for GET filters we typically disable CSRF
    form = ActivityQueryFilterForm(request.args, meta={"csrf": False})

    show_form = not bool(request.args)

    if show_form:
        # Recursive category path query, for the category multi-select
        category_paths = sqla_db.session.execute(text("""
            WITH RECURSIVE category_path(id, name, parent_id, full_path) AS (
                SELECT id, name, parent_id, name
                FROM Category
                WHERE parent_id IS NULL
                UNION ALL
                SELECT c.id, c.name, c.parent_id, cp.full_path || ' : ' || c.name
                FROM Category c
                JOIN category_path cp ON c.parent_id = cp.id
            )
            SELECT id, full_path FROM category_path
            ORDER BY full_path
        """)).fetchall()
        form.categories.choices = [(row.id, row.full_path) for row in category_paths]

        workout_types = (
            sqla_db.session.query(WorkoutType)
            .order_by(WorkoutType.name)
            .all()
        )
        form.workout_types.choices = [(w.id, w.name) for w in workout_types]

        activities = None
        summary = None
        category_summary = None
        category_depths = None
        query_filter = None

    else:
        from sqlalchemy.orm import joinedload
        from collections import defaultdict, OrderedDict

        query_filter = []

        # Build human-readable list of selected filters
        if form.categories.data:
            query_filter.append((
                "Categories",
                ", ".join(category_path_filter(c) for c in form.categories.data),
            ))

        if form.is_training.data in ("1", "0"):
            query_filter.append((
                "Is Training",
                "Yes" if form.is_training.data == "1" else "No",
            ))

        if form.date_start.data:
            query_filter.append(("From", form.date_start.data.strftime("%Y-%m-%d")))
        if form.date_end.data:
            query_filter.append(("To", form.date_end.data.strftime("%Y-%m-%d")))

        if form.min_time.data:
            query_filter.append(("Min Time (minutes)", str(form.min_time.data)))
        if form.max_time.data:
            query_filter.append(("Max Time (minutes)", str(form.max_time.data)))

        if form.workout_types.data:
            wt_names = dict(
                sqla_db.session.query(WorkoutType.id, WorkoutType.name).all()
            )
            query_filter.append((
                "Workout Type",
                ", ".join(wt_names.get(wid, str(wid)) for wid in form.workout_types.data),
            ))

        # Fetch all canonical activities with training_logs preloaded.
        # (We filter in Python for now; DB size is modest and this keeps
        # the logic simple & canonical-friendly.)
        base_q = sqla_db.session.query(Activity).options(
            joinedload(Activity.training_logs)
        )
        all_activities = base_q.all()

        filtered = []
        for a in all_activities:
            tl = get_primary_training_log(a)

            # Category filter (match on TrainingLogData.categoryId)
            if form.categories.data:
                cat_id = getattr(tl, "categoryId", None) if tl else None
                if cat_id not in form.categories.data:
                    continue

            # Workout type filter (match on TrainingLogData.workoutTypeId)
            if form.workout_types.data:
                wt_id = getattr(tl, "workoutTypeId", None) if tl else None
                if wt_id not in form.workout_types.data:
                    continue

            # Training flag filter (TrainingLogData.isTraining)
            if form.is_training.data in ("1", "0"):
                wanted = int(form.is_training.data)
                is_tr = getattr(tl, "isTraining", None) if tl else None
                if is_tr != wanted:
                    continue

            # Date filters use the activity-local date (from Activity.tz_name)
            if form.date_start.data or form.date_end.data:
                local_date = get_local_date_for_activity(a)
                if form.date_start.data and (local_date is None or local_date < form.date_start.data):
                    continue
                if form.date_end.data and (local_date is None or local_date > form.date_end.data):
                    continue

            # Time filters use canonical moving_time_s (seconds)
            if form.min_time.data:
                if a.moving_time_s is None or a.moving_time_s < form.min_time.data * 60:
                    continue
            if form.max_time.data:
                if a.moving_time_s is None or a.moving_time_s > form.max_time.data * 60:
                    continue

            filtered.append(a)

        # Sort ascending by start datetime (using canonical helper)
        filtered.sort(key=lambda x: activity_local_dt(x) or datetime.min)

        activities = filtered
        summary = summarize_activities(activities)

        # ---- Hierarchical category summary (inclusive totals) ----

        if activities:
            acts = list(activities)

            # Group activities by direct category id
            direct_groups = defaultdict(list)
            for a in acts:
                cid = group_by_category_id(a)
                direct_groups[cid].append(a)

            # Load the category tree (id, parent_id)
            cats = sqla_db.session.query(Category.id, Category.parent_id).all()
            children = defaultdict(list)   # parent_id -> [child_id]
            for cid, parent_id in cats:
                children[parent_id].append(cid)

            def gather_activities_for_category(root_cid: int):
                stack = [root_cid]
                acc = []
                while stack:
                    current = stack.pop()
                    acc.extend(direct_groups.get(current, []))
                    stack.extend(children.get(current, []))
                return acc

            raw_summary = {}

            # Inclusive summary for each defined category
            for cid, parent_id in cats:
                cat_acts = gather_activities_for_category(cid)
                if cat_acts:
                    raw_summary[cid] = summarize_activities(cat_acts)

            # Handle uncategorized activities (no TrainingLogData category)
            if direct_groups.get(None):
                raw_summary[None] = summarize_activities(direct_groups[None])

            # Depth for indentation (root depth = 0)
            category_depths = {}

            def assign_depths(parent_id, depth: int):
                for cid in children.get(parent_id, []):
                    category_depths[cid] = depth
                    assign_depths(cid, depth + 1)

            assign_depths(None, 0)

            # Order categories in tree order (parent then children)
            name_lookup = dict(
                sqla_db.session.query(Category.id, Category.name).all()
            )
            ordered = OrderedDict()

            def add_with_children(parent_id):
                for cid in sorted(children.get(parent_id, []), key=lambda x: name_lookup.get(x, "")):
                    if cid in raw_summary:
                        ordered[cid] = raw_summary[cid]
                    add_with_children(cid)

            add_with_children(None)

            # Put uncategorized at the bottom if present
            if None in raw_summary:
                ordered[None] = raw_summary[None]

            category_summary = ordered
        else:
            category_summary = None
            category_depths = {}

    return render_template(
        "query.html",
        form=form,
        activities=activities,
        summary=summary,
        category_summary=category_summary,
        # if you’re using indentation; otherwise you can drop this
        category_depths=category_depths if not show_form else None,
        query_filter=query_filter,
    )


@views.route("/addcategory", methods=["GET", "POST"])
def add_category():
    form = CategoryForm()
    category_paths = sqla_db.session.execute(text("""
        WITH RECURSIVE category_path(id, name, parent_id, full_path) AS (
            SELECT id, name, parent_id, name
            FROM Category
            WHERE parent_id IS NULL
            UNION ALL
            SELECT c.id, c.name, c.parent_id, cp.full_path || ' : ' || c.name
            FROM Category c
            JOIN category_path cp ON c.parent_id = cp.id
        )
        SELECT id, full_path FROM category_path
        ORDER BY full_path
    """)).fetchall()
    form.parent_id.choices = [(0, "— No Parent —")] + [(row.id, row.full_path) for row in category_paths]

    if "cancel" in request.form:
        return redirect(url_for("views.dashboard"))

    if form.validate_on_submit():
        parent_id = form.parent_id.data or None
        new_cat = Category(name=form.name.data, parent_id=parent_id)
        sqla_db.session.add(new_cat)
        sqla_db.session.commit()
        flash("Category added.")
        return redirect(url_for("views.dashboard"))

    return render_template("add_category.html", form=form)

@views.route("/admin")
def admin():
    return render_template("admin.html")
