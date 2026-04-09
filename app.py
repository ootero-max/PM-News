"""
Flask web server for the News Aggregator.
Serves the HTML digest and refreshes articles on a background schedule.
"""

import threading
import time
from pathlib import Path

from flask import Flask, Response, send_from_directory
from news_aggregator import main as refresh_news, HTML_PATH

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = Flask(__name__)

REFRESH_INTERVAL = 6 * 3600  # 6 hours


def background_refresh():
    """Refresh news on startup, then every REFRESH_INTERVAL seconds."""
    while True:
        try:
            refresh_news()
            print("News refreshed successfully.")
        except Exception as exc:
            print(f"Refresh failed: {exc}")
        time.sleep(REFRESH_INTERVAL)


_thread = threading.Thread(target=background_refresh, daemon=True)
_thread.start()


@app.route("/")
def index():
    try:
        with open(HTML_PATH, "r", encoding="utf-8") as fh:
            return Response(fh.read(), content_type="text/html")
    except FileNotFoundError:
        return (
            "<h1>Generating news digest&hellip;</h1>"
            "<p>Please refresh in a minute.</p>"
        ), 503


@app.route("/refresh", methods=["GET", "POST"])
def refresh():
    refresh_news()
    return "Refreshed!", 200


@app.route("/manifest.json")
def manifest():
    return send_from_directory(STATIC_DIR, "manifest.json", mimetype="application/manifest+json")


@app.route("/sw.js")
def service_worker():
    return send_from_directory(STATIC_DIR, "sw.js", mimetype="application/javascript")


@app.route("/icon-192.svg")
@app.route("/icon-512.svg")
def icon():
    return send_from_directory(STATIC_DIR, "icon.svg", mimetype="image/svg+xml")
