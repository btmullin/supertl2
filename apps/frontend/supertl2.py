from flask import Flask
from views import views

app = Flask(__name__)
app.register_blueprint(views, url_prefix="/")

if __name__ == "__main__":
    # Please do not set debug=True in production
    app.run(host="0.0.0.0", port=5000, debug=True)