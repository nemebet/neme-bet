from flask import Flask, jsonify

app = Flask(__name__)

@app.route("/")
def home():
    return "NEME BET OK"

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
