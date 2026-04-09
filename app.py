"""
Flask web server for the News Aggregator.
Serves the HTML digest and refreshes articles on a background schedule.
"""

import threading
import time

from flask import Flask, Response
from news_aggregator import main as refresh_news, HTML_PATH

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
