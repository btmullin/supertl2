import sqlite3
from flask import Flask, g
from .views import views
import os
from .db import initialize_dbs
from .filters import register_filters

# Initialize Flask app
def create_app():
    """Create the flask application

    Returns:
        Flask: the app
    """
    app = Flask(__name__)

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

    # Initialize dbs
    initialize_dbs()

    return app
