"""Primary views of the flask application."""

import os
import sys
import json
from datetime import datetime, timedelta, time
from collections import defaultdict
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
from app.db.db import import_strava_data
from .forms.EditActivityForm import EditActivityForm
from .forms.CategoryForm import CategoryForm
from .forms.SummaryForm import SummaryFilterForm
from .models import StravaActivity, WorkoutType, TrainingLogData, Category
from .db.base import sqla_db
from app.services.analytics import summarize_activities, bucket_daily, summarize_by, group_by_category_id
from .filters import category_path_filter

PER_PAGE = 25

views = Blueprint("views", __name__)

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
        sqla_db.session.query(StravaActivity)
        .join(StravaActivity.training_log)  # Only join activities that have a training_log
        .filter(
            TrainingLogData.isTraining == 1,
            func.date(StravaActivity.startDateTime).between(start_of_week, end_of_week)
        )
        .order_by(StravaActivity.startDateTime)
        .all()
    )

    # Organize and annotate
    activities_by_day = defaultdict(list)
    activities_data = []
    for a in activities:
        day = a.startDateTime.date()
        activities_by_day[day].append(a)
        activities_data.append(a)

    days = [start_of_week + timedelta(days=i) for i in range(7)]

    daily_summaries = bucket_daily(activities)

    week_summary = summarize_activities(activities)

    # Get previous week summaries
    previous_week_start = start_of_week - timedelta(weeks=1)
    previous_week_end = end_of_week - timedelta(weeks=1)
    previous_activities = (
        sqla_db.session.query(StravaActivity)
        .join(StravaActivity.training_log)  # Only join activities that have a training_log
        .filter(
            TrainingLogData.isTraining == 1,
            func.date(StravaActivity.startDateTime).between(previous_week_start, previous_week_end)
        )
        .order_by(StravaActivity.startDateTime)
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
    activity_id = request.args.get("id")
    if not activity_id:
        flash("Missing activity ID.")
        return redirect(url_for("views.dashboard"))

    activity = sqla_db.session.get(StravaActivity, activity_id)
    if not activity:
        flash("Activity not found.")
        return redirect(next_url)

    activity_data = activity.data or {}
    summary_polyline = activity_data.get("map", {}).get("summary_polyline", "")

    form = EditActivityForm()

    # Populate select fields
    form.workoutTypeId.choices = [(0, "—")] + [
        (w.id, w.name) for w in sqla_db.session.query(WorkoutType).order_by(WorkoutType.name).all()
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

    if request.method == "GET":
        form.activityId.data = activity_id
        existing = sqla_db.session.get(TrainingLogData, activity_id)
        if existing:
            form.workoutTypeId.data = existing.workoutTypeId or 0
            form.categoryId.data = existing.categoryId or 0
            form.notes.data = existing.notes
            form.tags.data = existing.tags
            form.isTraining.data = existing.isTraining if existing.isTraining is not None else 2
        return render_template("editactivity.html", form=form, activityId=activity_id, activity=activity, summary_polyline=summary_polyline)

    if form.cancel.data:
        return redirect(next_url)

    if form.validate_on_submit():
        workout_id = form.workoutTypeId.data or None
        category_id = form.categoryId.data or None

        training_data = sqla_db.session.get(TrainingLogData, activity_id)
        if not training_data:
            training_data = TrainingLogData(activityId=activity_id)
            sqla_db.session.add(training_data)

        training_data.workoutTypeId = workout_id
        training_data.categoryId = category_id
        training_data.notes = form.notes.data
        training_data.tags = form.tags.data
        training_data.isTraining = form.isTraining.data

        sqla_db.session.commit()

        flash("Metadata updated.")
        return redirect(next_url)

    return render_template("editactivity.html", form=form, activityId=activity_id, activity=activity, summary_polyline=summary_polyline)

@views.route("/admin/import-strava")
def import_strava():
    import_strava_data()

    flash(f"Imported new activities.")
    return redirect(url_for("views.activitylist"))

@views.route("/activitylist")
def activitylist():
    page = request.args.get('page', 1, type=int)
    offset = (page - 1) * PER_PAGE
    # Fetch activities in date range
    activities = (
        sqla_db.session.query(StravaActivity)
        .order_by(StravaActivity.startDateTime.desc())
        .limit(PER_PAGE)
        .offset(offset)
        .all()
    )

    # Get total number of rows
    total = sqla_db.session.query(func.count(StravaActivity.activityId)).scalar()
    total_pages = (total + PER_PAGE - 1) // PER_PAGE
    
    return render_template("activitylist.html", activities=activities, page=page, total_pages=total_pages)

@views.route("/summary", methods=["GET"])
def summary_list():
    # Bind from querystring; for GET filters we typically disable CSRF
    form = SummaryFilterForm(request.args, meta={"csrf": False})

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
        summary_filter = None

    else:
        # Build query
        summary_filter = []
        q = sqla_db.session.query(StravaActivity).options(
            joinedload(StravaActivity.training_log)  # avoid N+1 when showing tags/category
        )

        joined_tl = False

        # Categories (requires join)
        if form.categories.data:
            summary_filter.append(("Categories", ", ".join(category_path_filter(c) for c in form.categories.data)))
            q = q.join(StravaActivity.training_log)
            joined_tl = True
            q = q.filter(TrainingLogData.categoryId.in_(form.categories.data))

        # Training flag (requires join)
        if form.is_training.data in ("1", "0"):
            summary_filter.append(("Is Training", ("Yes" if form.is_training.data == "1" else "No")))
            if not joined_tl:
                q = q.join(StravaActivity.training_log)
                joined_tl = True
            q = q.filter(TrainingLogData.isTraining == int(form.is_training.data))

        # Date range (inclusive of end date)
        if form.date_start.data:
            summary_filter.append(("From", form.date_start.data.strftime("%Y-%m-%d")))
            start_dt = datetime.combine(form.date_start.data, time.min)
            q = q.filter(StravaActivity.startDateTime >= start_dt)
        if form.date_end.data:
            summary_filter.append(("To", form.date_end.data.strftime("%Y-%m-%d")))
            # Use exclusive upper bound midnight next day to include the whole end date
            end_dt = datetime.combine(form.date_end.data + timedelta(days=1), time.min)
            q = q.filter(StravaActivity.startDateTime < end_dt)

        # Order
        q = q.order_by(StravaActivity.startDateTime.asc())

        activities = q.all()
        summary = summarize_activities(activities)
        category_summary = summarize_by(activities, group_by_category_id)

    return render_template(
        "summary.html",
        form=form,
        activities=activities,
        summary=summary,
        category_summary=category_summary,
        summary_filter=summary_filter,
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
