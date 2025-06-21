from flask import (
    Blueprint,
    jsonify,
    render_template,
    request,
    url_for,
    redirect,
    current_app,
    flash,
)
from werkzeug.utils import secure_filename
import os
from trainingdata.activity import Activity
from .forms import ImportSummaryForm
import sys
from app.db import get_strava_db

PER_PAGE = 20

views = Blueprint("views", __name__)


def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower()
        in current_app.config["ALLOWED_EXTENSIONS"]
    )


@views.route("/")
@views.route("/dashboard")
def dashboard():
    page = request.args.get('page', 1, type=int)
    offset = (page - 1) * PER_PAGE
    strava_db = get_strava_db()

    # Get total number of rows
    total = strava_db.execute("SELECT COUNT(*) FROM Activity").fetchone()[0]
    total_pages = (total + PER_PAGE - 1) // PER_PAGE
    
    # Fetch just the current page
    rows = strava_db.execute(
        "SELECT activityId, startDateTime, sportType, name, distance, movingTimeInSeconds FROM Activity ORDER BY startDateTime DESC LIMIT ? OFFSET ?",
        (PER_PAGE, offset)
    ).fetchall()
    
    return render_template("dashboard.html", activities=rows, page=page, total_pages=total_pages)


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
