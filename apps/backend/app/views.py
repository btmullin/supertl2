"""Primary views of the flask application."""

import os
import sys
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
from .forms import ImportSummaryForm
from .forms.EditExtraForm import EditExtraForm
from app.db import get_stl_db, import_strava_data
import json
from datetime import datetime, timedelta
from collections import defaultdict

PER_PAGE = 20

views = Blueprint("views", __name__)


def allowed_file(filename):
    """Check if the file has an allowed extension."""
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower()
        in current_app.config["ALLOWED_EXTENSIONS"]
    )


@views.route("/")
@views.route("/dashboard")
def dashboard():
    week_offset = int(request.args.get("week_offset", 0))

    # Calculate the current Monday (week starts)
    today = datetime.today().date()
    start_of_week = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
    end_of_week = start_of_week + timedelta(days=6)
    print(f"start_of_week: {start_of_week}, end_of_week: {end_of_week}", file=sys.stderr)

    supertl2_db = get_stl_db()

    # Fetch just the current week
    rows = supertl2_db.execute("""
        SELECT * FROM StravaActivity WHERE date(startDateTime) BETWEEN ? AND ?
        ORDER BY startDateTime ASC""", (start_of_week.isoformat(), end_of_week.isoformat())).fetchall()
    
    # Collect activityIds to check extras
    activity_ids = [row["activityId"] for row in rows]

    # Find which ones have extras
    placeholders = ",".join("?" for _ in activity_ids)
    extras = supertl2_db.execute(
        f"SELECT activityId FROM Supertl2Extra WHERE activityId IN ({placeholders})",
        activity_ids
    ).fetchall()
    extras_set = set(row["activityId"] for row in extras)

    # Attach info to each row
    activities = []
    for row in rows:
        activity = dict(row)
        activity["has_extra"] = activity["activityId"] in extras_set
        activities.append(activity)

    # Group activities by day of week
    activities_by_day = defaultdict(list)
    for a in activities:
        day = datetime.fromisoformat(a["startDateTime"]).date()
        activities_by_day[day].append(a)
    days = [(start_of_week + timedelta(days=i)) for i in range(7)]

    # Get daily summaries
    daily_summaries = defaultdict(list)
    for i,day in enumerate(days):
        daily_summaries[day] = {
            "total_distance": sum(
                a["distance"] for a in activities_by_day[day] if a["distance"] is not None
            ),
            "total_duration": sum(
                a["movingTimeInSeconds"] for a in activities_by_day[day] if a["movingTimeInSeconds"] is not None
            ),
        }

    # Get this weeks summary
    week_summary = {
        "total_distance": sum(
            daily_summaries[day]["total_distance"] for day in days
        ),
        "total_duration": sum(
            daily_summaries[day]["total_duration"] for day in days
        ),
    }

    return render_template("dashboard.html",
                           start_of_week=start_of_week,
                           week_offset=week_offset,
                           activities_by_day=activities_by_day,
                           days=days,
                           daily_summaries=daily_summaries,
                           week_summary=week_summary,)


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
    return render_template("test.html")

@views.route("/activity/edit", methods=["GET", "POST"])
def edit_extra():
    next_url = request.args.get("next") or url_for("views.dashboard")
    activity_id = request.args.get("id")
    if not activity_id:
        flash("Missing activity ID.")
        return redirect(url_for("views.dashboard"))

    stl_db = get_stl_db()

    activity = stl_db.execute(
        "SELECT * FROM StravaActivity WHERE activityId = ?", (activity_id,)
        ).fetchone()

    activity_data = json.loads(activity["data"]) if activity and activity["data"] else {}
    summary_polyline = activity_data.get("map", {}).get("summary_polyline", "")

    form = EditExtraForm()

    # Populate select fields
    form.workoutTypeId.choices = [(0, "—")] + [
        (row["id"], row["name"])
        for row in stl_db.execute("SELECT id, name FROM WorkoutType ORDER BY name").fetchall()
    ]

    form.categoryId.choices = [(0, "—")] + [
        (row["id"], row["full_path"])
        for row in stl_db.execute("""
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
        """).fetchall()
    ]

    if request.method == "GET":
        form.activityId.data = activity_id
        row = stl_db.execute(
            "SELECT * FROM Supertl2Extra WHERE activityId = ?", (activity_id,)
        ).fetchone()
        if row:
            form.workoutTypeId.data = row["workoutTypeId"] or 0
            form.categoryId.data = row["categoryId"] or 0
            form.notes.data = row["notes"]
            form.tags.data = row["tags"]
            form.isTraining.data = row["isTraining"] if row["isTraining"] is not None else 2
        return render_template("edit_extra.html", form=form, activityId=activity_id, activity=activity, summary_polyline=summary_polyline)

    if form.cancel.data:
        return redirect(next_url)

    if form.validate_on_submit():
        workout_id = form.workoutTypeId.data or None
        category_id = form.categoryId.data or None

        stl_db.execute("""
            INSERT INTO Supertl2Extra (activityId, workoutTypeId, categoryId, notes, tags, isTraining)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(activityId) DO UPDATE SET
                workoutTypeId=excluded.workoutTypeId,
                categoryId=excluded.categoryId,
                notes=excluded.notes,
                tags=excluded.tags,
                isTraining=excluded.isTraining
        """, (
            activity_id,
            workout_id,
            category_id,
            form.notes.data,
            form.tags.data,
            form.isTraining.data,
        ))
        stl_db.commit()
        flash("Metadata updated.")
        return redirect(next_url)

    return render_template("edit_extra.html", form=form, activityId=activity_id, activity=activity, summary_polyline=summary_polyline)

@views.route("/admin/import-strava")
def import_strava():
    import_strava_data()

    flash(f"Imported new activities.")
    return redirect(url_for("views.dashboard"))