import sqlite3
from flask import Flask, g
from .views import views
import os
from .filters import register_filters
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from .db.base import sqla_db

STL_DB = '/app/db/supertl2.db'

# Initialize Flask app
def create_app():
    """Create the flask application

    Returns:
        Flask: the app
    """
    app = Flask(__name__)

    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + STL_DB
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    sqla_db.init_app(app)
    with app.app_context():
        from . import models  # Import models to register them with SQLAlchemy

    app.jinja_env.auto_reload = True
    app.config['TEMPLATES_AUTO_RELOAD'] = True
    app.config['UPLOAD_FOLDER'] = '/data/uploads'
    app.config['ALLOWED_EXTENSIONS'] = {'fit'}

    # TODO - Figure out what a secretkey really should be
    app.config['SECRET_KEY'] = 'secretkey'

    # Ensure upload directory exists
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])

    # Import blueprints/routes
    app.register_blueprint(views, url_prefix="/")

    # Register formatting filters
    register_filters(app)

    return app
