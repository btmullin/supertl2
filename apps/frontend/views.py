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

views = Blueprint(__name__, "views")


def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower()
        in current_app.config["ALLOWED_EXTENSIONS"]
    )


@views.route("/")
@views.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")


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


@views.route("/import_summary")
def import_summary():
    args = request.args
    file_name = args.get("file_name")
    return render_template("import_summary.html", file_name=file_name)


@views.route("/test")
def test():
    return render_template("test.html")
