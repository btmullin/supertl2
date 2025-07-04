"""Primary views of the flask application."""

import os
import sys
import json
from datetime import datetime, timedelta
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
from werkzeug.utils import secure_filename
from trainingdata.activity import Activity
from sqlalchemy import func, text
from app.db.db import import_strava_data
from .forms import ImportSummaryForm
from .forms.EditExtraForm import EditExtraForm
from .models import StravaActivity, WorkoutType, TrainingLogData, Category
from .db.base import sqla_db

PER_PAGE = 20

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
        .filter(func.date(StravaActivity.startDateTime).between(start_of_week, end_of_week))
        .order_by(StravaActivity.startDateTime)
        .all()
    )

    # Organize and annotate
    activities_by_day = defaultdict(list)
    activities_data = []
    for a in activities:
        day = a.startDateTime.date()
        activity_dict = {
            "activityId": a.activityId,
            "startDateTime": a.startDateTime,
            "sportType": a.sportType,
            "name": a.name,
            "distance": a.distance,
            "movingTimeInSeconds": a.movingTimeInSeconds,
            "has_extra": a.training_log is not None,
        }
        activities_by_day[day].append(activity_dict)
        activities_data.append(activity_dict)

    days = [start_of_week + timedelta(days=i) for i in range(7)]

    daily_summaries = {
        day: {
            "total_distance": sum(a["distance"] for a in activities_by_day[day] if a["distance"] is not None),
            "total_duration": sum(a["movingTimeInSeconds"] for a in activities_by_day[day] if a["movingTimeInSeconds"] is not None),
        }
        for day in days
    }

    week_summary = {
        "total_distance": sum(d["total_distance"] for d in daily_summaries.values()),
        "total_duration": sum(d["total_duration"] for d in daily_summaries.values()),
    }

    return {
        "start_of_week": start_of_week,
        "end_of_week": end_of_week,
        "activities_by_day": activities_by_day,
        "daily_summaries": daily_summaries,
        "week_summary": week_summary,
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


@views.route("/import", methods=["GET", "POST"])
def import_page():
    if request.method == "POST":
        # check if the post request has the file part
        if "file" not in request.files:
            flash("No file part")
            return redirect(request.url)
        file = request.files["file"]
        # If the user does not select a file, the browser submits an
        # empty file without a filename.
        if file.filename == "":
            flash("No selected file")
            return redirect(request.url)
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(current_app.config["UPLOAD_FOLDER"], filename))
            return redirect(url_for("views.import_summary", file_name=filename))
    return render_template("import.html")


@views.route("/activity")
def activity_view():
    args = request.args
    activity_id = args.get("id")
    return render_template("activity.html", id=activity_id)


@views.route("/import_summary", methods=['GET', 'POST'])
def import_summary():
    form = ImportSummaryForm.ImportSummaryForm(request.form)
    if request.method == 'GET':
        args = request.args
        file_name = args.get("file_name")
        form.activity = Activity(os.path.join(current_app.config["UPLOAD_FOLDER"], file_name))

        return render_template("import_summary.html", activity=form.activity, form=form)
    else:
        # user pressed a button
        if form.save.data:
            print('Save button pressed', file=sys.stderr)
            print(f'Description: {form.description.data}', file=sys.stderr)
            print(f'Category: {form.category_field.data}', file=sys.stderr)
            print(f'Activity info?: {form.activity.summary.distance_m}', file=sys.stderr)
            # TODO - Here is where we can take the data from the activity and
            # from the form and save it
            # WONDER IF THERE IS A WAY TO NOT RECREATE THE ACTIVITY AGAIN....
        elif form.cancel.data:
            print('Cancel button pressed', file=sys.stderr)
        return 'HELP ME'

@views.route("/test")
def test():
    activity = sqla_db.session.query(TrainingLogData).first()
    return render_template("test.html", activity=activity)

@views.route("/activity/edit", methods=["GET", "POST"])
def edit_extra():
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

    form = EditExtraForm()

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
        return render_template("edit_extra.html", form=form, activityId=activity_id, activity=activity, summary_polyline=summary_polyline)

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

    return render_template("edit_extra.html", form=form, activityId=activity_id, activity=activity, summary_polyline=summary_polyline)

@views.route("/admin/import-strava")
def import_strava():
    import_strava_data()

    flash(f"Imported new activities.")
    return redirect(url_for("views.dashboard"))