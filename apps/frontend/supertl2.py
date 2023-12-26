from flask import Flask, jsonify

app = Flask(__name__)


@app.route("/supertl2", methods=["GET"])
def say_hello():
    return jsonify({"msg": "Hello from SUPER Training Log 2"})


if __name__ == "__main__":
    # Please do not set debug=True in production
    app.run(host="0.0.0.0", port=5000, debug=True)