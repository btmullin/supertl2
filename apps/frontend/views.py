from flask import Blueprint, jsonify, render_template, request, url_for

views = Blueprint(__name__, "views")

@views.route("/")
def home():
    return render_template('index.html')

@views.route("/test")
def test():
    return render_template('test.html')

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
