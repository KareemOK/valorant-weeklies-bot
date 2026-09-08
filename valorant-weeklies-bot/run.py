"""
Entry point that runs the Discord bot and the leaderboard web page together
in one process, so a single free-tier host/container is enough for the
whole project.
"""

import os
import threading

from waitress import serve

import bot
import db
import webapp


def start_webapp():
    port = int(os.environ.get("WEB_PORT", 8080))
    serve(webapp.app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    db.init_db()
    threading.Thread(target=start_webapp, daemon=True).start()
    bot.main()
