import sqlite3
from flask import Flask
from .views import views
import os

# Function to create the SQLite database connection
def create_connection():
    """Create the db connection

    Returns:
        Connection: The db connection.
    """
    connection = sqlite3.connect('/data/supertl2.db')
    return connection

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

    # Create database connection
    with app.app_context():
        connection = create_connection()
        cursor = connection.cursor()

        # TODO - If the db is empty initialize it (currently always initialized)
        if True:
            # Read schema file and execute SQL commands
            with app.open_resource('/app/apps/backend/schema.sql') as f:
                sql_script = f.read().decode('utf-8')
                cursor.executescript(sql_script)
            
            # Read the initial data and execute SQL commands
            with app.open_resource('/app/apps/backend/data.sql') as f:
                sql_script = f.read().decode('utf-8')
                cursor.executescript(sql_script)

        connection.commit()
        cursor.close()

    return app
