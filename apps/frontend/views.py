from flask import Blueprint, jsonify, render_template, request, url_for

views = Blueprint(__name__, "views")

@views.route("/")
@views.route("/dashboard")
def dashboard():
    return render_template('dashboard.html')

@views.route("/calendar")
def calendar():
    return render_template('calendar.html')

@views.route("/analysis")
def analysis():
    return render_template('analysis.html')

@views.route("/gear")
def gear():
    return render_template('gear.html')

@views.route("/import")
def import_page():
    return render_template('import.html')

@views.route("/activity")
def activity_view():
    args = request.args
    activity_id = args.get('id')
    return render_template('activity.html', id=activity_id)

@views.route("/import_summary")
def import_summary():
    args = request.args
    activity_id = args.get('id')
    return render_template('import_summary.html', id=activity_id)

@views.route("/test")
def test():
    return render_template('test.html')

