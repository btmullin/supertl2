from app import create_app
import sys
sys.stdout.reconfigure(line_buffering=True)

app = create_app()

if __name__ == "__main__":
    # Please do not set debug=True in production
    app.run(host="0.0.0.0", port=5000, debug=True)
