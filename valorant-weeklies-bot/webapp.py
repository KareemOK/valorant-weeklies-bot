"""
Tiny companion leaderboard site. Reads the exact same SQLite file the
Discord bot writes to, so there's nothing to sync -- as soon as a match is
confirmed in Discord, this page reflects it on next refresh.

Run standalone with `python webapp.py` (for local testing), or it's started
automatically alongside the bot by run.py in production.
"""

import os

from flask import Flask, render_template_string, send_from_directory

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
  main { max-width: 1000px; margin: 0 auto; padding: 0 16px 48px; }
  .panel {
    background: var(--panel); border: 1px solid var(--border); border-radius: 12px;
    padding: 16px; margin-bottom: 24px; overflow-x: auto;
  }
  h2 { font-size: 1.1rem; margin: 4px 0 4px; }
  .hint { color: var(--muted); font-size: 0.8rem; margin: 0 0 12px; }
  table { width: 100%; border-collapse: collapse; font-size: 0.92rem; }
  th, td { text-align: left; padding: 8px 10px; white-space: nowrap; }
  th { color: var(--muted); font-weight: 600; border-bottom: 1px solid var(--border); }
  th[data-key] { cursor: pointer; user-select: none; }
  th[data-key]:hover { color: var(--text); }
  th.sorted { color: var(--accent); }
  tr:not(:last-child) td { border-bottom: 1px solid var(--border); }
  .rank { color: var(--muted); width: 2em; }
  .elo { font-weight: 700; }
  .win { color: #3ddc84; } .loss { color: #ff6b6b; }
  a { color: var(--accent); }
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
    <p class="hint">Click a column heading to sort. Elo is the official ranking; the rest are for bragging rights.</p>
    <table id="leaderboard-table">
      <thead>
        <tr>
          <th class="rank">#</th>
          <th data-key="name">Player</th>
          <th data-key="elo" class="sorted">Elo</th>
          <th data-key="winrate">Win%</th>
          <th data-key="kd">K/D</th>
          <th data-key="kpr">KPR</th>
          <th data-key="acs">ACS</th>
          <th data-key="plants">Plants</th>
          <th data-key="defuses">Defuses</th>
          <th data-key="fb">FB</th>
        </tr>
      </thead>
      <tbody>
      {% for r in leaderboard %}
      <tr>
        <td class="rank">{{ loop.index }}</td>
        <td data-key="name" data-value="{{ r['display_name']|lower }}">{{ r['display_name'] }}</td>
        <td data-key="elo" data-value="{{ r['elo'] }}" class="elo">{{ r['elo']|round|int }}</td>
        <td data-key="winrate" data-value="{{ r['win_rate'] }}">
          {{ (r['win_rate'] * 100)|round|int }}% (<span class="win">{{ r['wins'] }}W</span>-<span class="loss">{{ r['losses'] }}L</span>)
        </td>
        <td data-key="kd" data-value="{{ r['kd'] }}">{{ '%.2f'|format(r['kd']) }}</td>
        <td data-key="kpr" data-value="{{ r['kpr'] or 0 }}">{{ '%.2f'|format(r['kpr']) if r['kpr'] is not none else '-' }}</td>
        <td data-key="acs" data-value="{{ r['avg_acs'] or 0 }}">{{ r['avg_acs']|round|int if r['avg_acs'] is not none else '-' }}</td>
        <td data-key="plants" data-value="{{ r['plants'] }}">{{ r['plants'] }}</td>
        <td data-key="defuses" data-value="{{ r['defuses'] }}">{{ r['defuses'] }}</td>
        <td data-key="fb" data-value="{{ r['first_bloods'] }}">{{ r['first_bloods'] }}</td>
      </tr>
      {% else %}
      <tr><td colspan="10">No matches recorded yet.</td></tr>
      {% endfor %}
      </tbody>
    </table>
  </div>

  <div class="panel">
    <h2>Recent matches</h2>
    {% for entry in recent %}
      {% set m = entry['match'] %}
      <h3 style="font-size:0.95rem;margin:16px 0 8px;">
        {{ m['map_name'] or 'Unknown map' }}
        {% if m['team1_score'] is not none and m['team2_score'] is not none %}
          ({{ m['team1_score'] }}-{{ m['team2_score'] }})
        {% endif %}
        &middot; winner: {{ m['winner'] }}
        {% if m['screenshot_path'] %}
          &middot; <a href="/screenshots/{{ m['screenshot_path'] }}" target="_blank" rel="noopener">view screenshot</a>
        {% endif %}
      </h3>
      <table>
        <tr><th>Team</th><th>Player</th><th>Agent</th><th>K/D/A</th><th>ACS</th><th>Plants</th><th>Defuses</th><th>FB</th><th>Elo &Delta;</th></tr>
        {% for p in entry['players'] %}
        <tr>
          <td>{{ p['team'] }}</td>
          <td>{{ p['display_name'] }}</td>
          <td>{{ p['agent'] or '-' }}</td>
          <td>{{ p['kills'] }}/{{ p['deaths'] }}/{{ p['assists'] }}</td>
          <td>{{ p['acs'] if p['acs'] is not none else '-' }}</td>
          <td>{{ p['plants'] }}</td>
          <td>{{ p['defuses'] }}</td>
          <td>{{ p['first_bloods'] }}</td>
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
<script>
(function () {
  var table = document.getElementById('leaderboard-table');
  if (!table) return;
  var tbody = table.tBodies[0];
  Array.prototype.forEach.call(table.querySelectorAll('th[data-key]'), function (th) {
    th.addEventListener('click', function () {
      var key = th.getAttribute('data-key');
      var dir = th.getAttribute('data-dir') === 'asc' ? 'desc' : 'asc';
      Array.prototype.forEach.call(table.querySelectorAll('th[data-key]'), function (h) {
        h.removeAttribute('data-dir');
        h.classList.remove('sorted');
      });
      th.setAttribute('data-dir', dir);
      th.classList.add('sorted');

      var rows = Array.prototype.slice.call(tbody.querySelectorAll('tr'));
      rows.sort(function (a, b) {
        var ca = a.querySelector('[data-key="' + key + '"]');
        var cb = b.querySelector('[data-key="' + key + '"]');
        var va = ca ? ca.getAttribute('data-value') : '';
        var vb = cb ? cb.getAttribute('data-value') : '';
        var na = parseFloat(va), nb = parseFloat(vb);
        var cmp;
        if (!isNaN(na) && !isNaN(nb)) { cmp = na - nb; }
        else { cmp = String(va).localeCompare(String(vb)); }
        return dir === 'asc' ? cmp : -cmp;
      });
      rows.forEach(function (r) { tbody.appendChild(r); });
    });
  });
})();
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(
        PAGE,
        leaderboard=db.get_leaderboard_extended(limit=50),
        recent=db.get_recent_matches(limit=15),
    )


@app.route("/screenshots/<path:filename>")
def screenshot(filename):
    return send_from_directory(db.SCREENSHOTS_DIR, filename)


if __name__ == "__main__":
    db.init_db()
    port = int(os.environ.get("WEB_PORT", 8080))
    app.run(host="0.0.0.0", port=port)
