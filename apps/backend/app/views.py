"""Primary views of the flask application."""

import os
import sys
import json
from datetime import datetime, timedelta, time
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
    get_start_datetime,
    get_local_date_for_activity
) 
from util.canonical.backfill_new_strava_to_canonical import backfill_new_strava
from .forms.EditActivityForm import EditActivityForm
from .forms.CategoryForm import CategoryForm
from .forms.ActivityQueryForm import ActivityQueryFilterForm
from .models import StravaActivity, WorkoutType, TrainingLogData, Category, Activity, SportTracksActivity
from .db.base import sqla_db
from .filters import category_path_filter

PER_PAGE = 25

views = Blueprint("views", __name__)

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

def get_dashboard_context(week_offset=0):
    today = datetime.today().date()
    start_of_week = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
    end_of_week = start_of_week + timedelta(days=6)

    # Fetch activities in date range
    activities = (
        sqla_db.session.query(Activity)
        .join(TrainingLogData, TrainingLogData.canonical_activity_id == Activity.id)
        .filter(
            TrainingLogData.isTraining == 1,
            func.date(Activity.start_time_utc).between(start_of_week, end_of_week),
        )
        .order_by(Activity.start_time_utc)
        .all()
    )

    # Organize and annotate
    activities_by_day = defaultdict(list)
    activities_data = []
    for a in activities:
        day = get_local_date_for_activity(a)
        activities_by_day[day].append(a)
        activities_data.append(a)

    days = [start_of_week + timedelta(days=i) for i in range(7)]

    daily_summaries = {
        day: summarize_activities(activities_by_day[day])
        for day in days
    }
    week_summary = summarize_activities(activities)

    # Get previous week summaries
    previous_week_start = start_of_week - timedelta(weeks=1)
    previous_week_end = end_of_week - timedelta(weeks=1)
    previous_activities = (
        sqla_db.session.query(Activity)
        .join(TrainingLogData, TrainingLogData.canonical_activity_id == Activity.id)
        .filter(
            TrainingLogData.isTraining == 1,
            func.date(Activity.start_time_utc).between(previous_week_start, previous_week_end),
        )
        .order_by(Activity.start_time_utc)
        .all()
    )

    previous_week_summary = summarize_activities(previous_activities)

    return {
        "start_of_week": start_of_week,
        "end_of_week": end_of_week,
        "activities_by_day": activities_by_day,
        "daily_summaries": daily_summaries,
        "week_summary": week_summary,
        "previous_week_summary": previous_week_summary,
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
def calendar():
    return render_template("calendar.html")


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

    flash(f"Imported new activities.")
    return redirect(url_for("views.activitylist"))

@views.route("/activitylist")
def activitylist():
    page = request.args.get('page', 1, type=int)
    offset = (page - 1) * PER_PAGE
    # Fetch activities in date range
    rows = get_canonical_activities(limit=PER_PAGE, offset=offset)
    total = get_canonical_activity_count()
    total_pages = (total + PER_PAGE - 1) // PER_PAGE if total > 0 else 1

    return render_template("activitylist.html", activities=rows, page=page, total_pages=total_pages)

@views.route("/query", methods=["GET"])
def activity_query():
    # Bind from querystring; for GET filters we typically disable CSRF
    form = ActivityQueryFilterForm(request.args, meta={"csrf": False})

    show_form = not bool(request.args)

    if show_form:
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
        form.categories.choices = [(row.id, row.full_path) for row in category_paths]

        activities = None
        summary = None
        category_summary = None
        category_depths = None
        query_filter = None

    else:
        # Build query
        query_filter = []
        q = sqla_db.session.query(StravaActivity).options(
            joinedload(StravaActivity.training_log)  # avoid N+1 when showing tags/category
        )

        joined_tl = False

        # Categories (requires join)
        if form.categories.data:
            query_filter.append(("Categories", ", ".join(category_path_filter(c) for c in form.categories.data)))
            q = q.join(StravaActivity.training_log)
            joined_tl = True
            q = q.filter(TrainingLogData.categoryId.in_(form.categories.data))

        # Training flag (requires join)
        if form.is_training.data in ("1", "0"):
            query_filter.append(("Is Training", ("Yes" if form.is_training.data == "1" else "No")))
            if not joined_tl:
                q = q.join(StravaActivity.training_log)
                joined_tl = True
            q = q.filter(TrainingLogData.isTraining == int(form.is_training.data))

        # Date range (inclusive of end date)
        if form.date_start.data:
            query_filter.append(("From", form.date_start.data.strftime("%Y-%m-%d")))
            start_dt = datetime.combine(form.date_start.data, time.min)
            q = q.filter(StravaActivity.startDateTime >= start_dt)
        if form.date_end.data:
            query_filter.append(("To", form.date_end.data.strftime("%Y-%m-%d")))
            # Use exclusive upper bound midnight next day to include the whole end date
            end_dt = datetime.combine(form.date_end.data + timedelta(days=1), time.min)
            q = q.filter(StravaActivity.startDateTime < end_dt)

        if form.min_time.data:
            query_filter.append(("Min Time (minutes)", str(form.min_time.data)))
            q = q.filter(StravaActivity.movingTimeInSeconds >= form.min_time.data * 60)
        if form.max_time.data:
            query_filter.append(("Max Time (minutes)", str(form.max_time.data)))
            q = q.filter(StravaActivity.movingTimeInSeconds <= form.max_time.data * 60)

        # Order
        q = q.order_by(StravaActivity.startDateTime.asc())

        activities = q.all()
        summary = summarize_activities(activities)

        # Build hierarchical category summary: each category row includes
        # activities directly in that category PLUS all activities in its
        # descendant subcategories.
        if activities:
            acts = list(activities)

            # Group activities by their direct category id (including None)
            direct_groups = defaultdict(list)
            for a in acts:
                cid = group_by_category_id(a)
                direct_groups[cid].append(a)

            # Load the category tree (id, parent_id)
            cats = sqla_db.session.query(Category.id, Category.parent_id).all()
            children = defaultdict(list)  # parent_id -> [child_id]
            for cid, parent_id in cats:
                children[parent_id].append(cid)

            # Helper: gather all activities for a category and its descendants
            def gather_activities_for_category(root_cid: int):
                stack = [root_cid]
                acc = []
                while stack:
                    current = stack.pop()
                    acc.extend(direct_groups.get(current, []))
                    stack.extend(children.get(current, []))
                return acc

            raw_summary = {}

            # Inclusive summary for every defined category
            for cid, parent_id in cats:
                cat_acts = gather_activities_for_category(cid)
                if cat_acts:
                    raw_summary[cid] = summarize_activities(cat_acts)

            # Handle uncategorized (cid is None) separately; it has no children
            if direct_groups.get(None):
                raw_summary[None] = summarize_activities(direct_groups[None])

            # Compute depth for indentation in the template (root depth = 0)
            category_depths = {}

            def assign_depths(parent_id, depth: int):
                for cid in children.get(parent_id, []):
                    category_depths[cid] = depth
                    assign_depths(cid, depth + 1)

            assign_depths(None, 0)

            # Order categories in a tree-friendly way (root -> children DFS)
            name_lookup = dict(
                sqla_db.session.query(Category.id, Category.name).all()
            )
            ordered = OrderedDict()

            def add_with_children(parent_id):
                # sort siblings by name for stable ordering
                for cid in sorted(children.get(parent_id, []), key=lambda x: name_lookup.get(x, "")):
                    if cid in raw_summary:
                        ordered[cid] = raw_summary[cid]
                    add_with_children(cid)

            # Start from roots (parent_id is NULL)
            add_with_children(None)

            # Put uncategorized at the bottom if present
            if None in raw_summary:
                ordered[None] = raw_summary[None]

            category_summary = ordered
        else:
            summary = None
            category_summary = None
            category_depths = {}

    return render_template(
        "query.html",
        form=form,
        activities=activities,
        summary=summary,
        category_summary=category_summary,
        category_depths=category_depths,
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
