from flask import Flask
from views import views

UPLOAD_FOLDER = '/app/apps/frontend/static/uploads'
ALLOWED_EXTENSIONS = {'fit'}

app = Flask(__name__)
app.jinja_env.auto_reload = True
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['ALLOWED_EXTENSIONS'] = ALLOWED_EXTENSIONS
app.register_blueprint(views, url_prefix="/")

if __name__ == "__main__":
    # Please do not set debug=True in production
    app.run(host="0.0.0.0", port=5000, debug=True)