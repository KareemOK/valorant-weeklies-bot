"""
Tiny companion leaderboard site. Reads the exact same SQLite file the
Discord bot writes to, so there's nothing to sync -- as soon as a match is
confirmed in Discord, this page reflects it on next refresh.

Run standalone with `python webapp.py` (for local testing), or it's started
automatically alongside the bot by run.py in production.
"""

import os

from flask import Flask, render_template_string

import db

app = Flask(__name__)

PAGE = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Valorant Weeklies</title>
<style>
  :root {
    color-scheme: light dark;
    --bg: #0f1115; --panel: #171a21; --text: #e8eaed; --muted: #9aa0a6;
    --accent: #ff4655; --border: #2a2e37;
  }
  @media (prefers-color-scheme: light) {
    :root { --bg: #f6f7f9; --panel: #ffffff; --text: #1b1f24; --muted: #5f6672; --border: #e3e5e8; }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }
  header {
    padding: 32px 24px 16px; text-align: center;
  }
  header h1 { margin: 0 0 4px; font-size: 1.6rem; letter-spacing: 0.02em; }
  header p { margin: 0; color: var(--muted); font-size: 0.9rem; }
  .accent { color: var(--accent); }
  main { max-width: 900px; margin: 0 auto; padding: 0 16px 48px; }
  .panel {
    background: var(--panel); border: 1px solid var(--border); border-radius: 12px;
    padding: 16px; margin-bottom: 24px; overflow-x: auto;
  }
  h2 { font-size: 1.1rem; margin: 4px 0 16px; }
  table { width: 100%; border-collapse: collapse; font-size: 0.92rem; }
  th, td { text-align: left; padding: 8px 10px; white-space: nowrap; }
  th { color: var(--muted); font-weight: 600; border-bottom: 1px solid var(--border); }
  tr:not(:last-child) td { border-bottom: 1px solid var(--border); }
  .rank { color: var(--muted); width: 2em; }
  .elo { font-weight: 700; }
  .win { color: #3ddc84; } .loss { color: #ff6b6b; }
  footer { text-align: center; color: var(--muted); font-size: 0.8rem; padding: 24px; }
</style>
</head>
<body>
<header>
  <h1><span class="accent">VALORANT</span> WEEKLIES</h1>
  <p>Season leaderboard &amp; recent matches</p>
</header>
<main>
  <div class="panel">
    <h2>Leaderboard</h2>
    <table>
      <tr><th class="rank">#</th><th>Player</th><th>Elo</th><th>Record</th><th>K/D/A</th></tr>
      {% for r in leaderboard %}
      <tr>
        <td class="rank">{{ loop.index }}</td>
        <td>{{ r['display_name'] }}</td>
        <td class="elo">{{ r['elo']|round|int }}</td>
        <td><span class="win">{{ r['wins'] }}W</span> - <span class="loss">{{ r['losses'] }}L</span></td>
        <td>{{ r['kills'] }}/{{ r['deaths'] }}/{{ r['assists'] }}</td>
      </tr>
      {% else %}
      <tr><td colspan="5">No matches recorded yet.</td></tr>
      {% endfor %}
    </table>
  </div>

  <div class="panel">
    <h2>Recent matches</h2>
    {% for entry in recent %}
      {% set m = entry['match'] %}
      <h3 style="font-size:0.95rem;margin:16px 0 8px;">
        {{ m['map_name'] or 'Unknown map' }} &middot; winner: {{ m['winner'] }}
      </h3>
      <table>
        <tr><th>Team</th><th>Player</th><th>Agent</th><th>K/D/A</th><th>Elo &Delta;</th></tr>
        {% for p in entry['players'] %}
        <tr>
          <td>{{ p['team'] }}</td>
          <td>{{ p['display_name'] }}</td>
          <td>{{ p['agent'] or '-' }}</td>
          <td>{{ p['kills'] }}/{{ p['deaths'] }}/{{ p['assists'] }}</td>
          <td>{{ (p['elo_after'] - p['elo_before'])|round(1) }}</td>
        </tr>
        {% endfor %}
      </table>
    {% else %}
      <p>No matches yet -- run <code>/report-match</code> in Discord after your first game.</p>
    {% endfor %}
  </div>
</main>
<footer>Valorant Weeklies &middot; auto-generated from Discord match reports</footer>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(
        PAGE,
        leaderboard=db.get_leaderboard(limit=50),
        recent=db.get_recent_matches(limit=15),
    )


if __name__ == "__main__":
    db.init_db()
    port = int(os.environ.get("WEB_PORT", 8080))
    app.run(host="0.0.0.0", port=port)
