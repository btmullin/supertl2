from flask import Blueprint, jsonify, render_template, request

views = Blueprint(__name__, "views")

@views.route("/")
def home():
    return render_template('index.html')

@views.route("/test")
def test():
    return render_template('test.html')

@views.route("/activity")
def activiy_view():
    args = request.args
    activity_id = args.get('id')
    return render_template('activity.html', id=activity_id)
