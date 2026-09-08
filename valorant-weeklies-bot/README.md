# Valorant Weeklies Bot

A small, self-hosted Discord bot for a weekly Valorant pickup night:

- `/link` -- players register their Riot ID once
- `/balance` -- split a pool of players into two Elo-balanced teams
- `/report-match` -- upload a screenshot of the post-match **Scoreboard**
  tab; the bot reads it with Claude's vision model, shows you what it
  extracted, and only saves it once someone hits **Confirm**
- `/leaderboard`, `/stats` -- season standings, in Discord
- a small companion web page (same data, easier to browse/share) with a
  **sortable** leaderboard (Elo, win rate, K/D, KPR, ACS, plants, defuses,
  first bloods) and recent match history, each linking back to the
  original screenshot it was read from

No dependency on Riot's API or any unofficial scraper -- it only ever reads
what's on screen in a screenshot someone chose to upload, and a human
confirms it before it's scored. That sidesteps the class of "bot silently
breaks because Riot changed something upstream" problem that a lot of
auto-detecting queue bots (NeatQueue included) run into.

## How it works, end to end

1. Everyone plays their custom game in Valorant as normal (teams picked via
   `/balance`, or Valorant's own in-game team randomizer -- either works,
   the bot doesn't care how teams were formed).
2. At the end of the match, open the post-match summary and switch to the
   **Scoreboard** tab (not the live in-match Tab overlay -- the post-match
   one has far more data: Avg Combat Score, First Bloods, Plants, and
   Defuses in addition to K/D/A). Screenshot that and run `/report-match`
   with it attached.
3. The bot sends the image to Claude, gets back structured per-player
   stats + winner + the round score, matches each in-game name to a linked
   Discord account, and posts an embed showing exactly what it read.
4. Someone confirms (ideally a captain from each team, so nobody can
   quietly submit a doctored screenshot) and the match is saved: Elo
   updates, all the per-player stats accumulate, the leaderboard updates
   immediately, and the original screenshot is kept alongside the match
   (linked from the web page) so a disputed stat can always be double
   checked against what was actually submitted.

Anyone the bot couldn't match to a Discord account (because they haven't
run `/link` yet) is called out in that confirmation message and just won't
be scored for that match -- get your regulars to `/link` once and this
stops coming up.

Note on this screen: it lists all 10 players together sorted by combat
score rather than split into two blocks, so team membership is shown by
each row's background color instead of position. The extraction prompt
already accounts for this -- if a match still comes out with a whole team
missing, it's more likely someone hasn't `/link`ed yet than a reading
mistake.

## Local setup

1. **Create the Discord application.**
   Go to <https://discord.com/developers/applications> -> New Application.
   Under **Bot**, create a bot user and copy its token. Under
   **OAuth2 -> URL Generator**, check scopes `bot` and `applications.commands`,
   and under bot permissions check at least: Send Messages, Embed Links,
   Attach Files, Read Message History, Use Slash Commands. Use the
   generated URL to invite it to your server.

   While testing, right-click your server in Discord (with Developer Mode
   on, in Settings -> Advanced) -> Copy Server ID -- that's your
   `DISCORD_GUILD_ID` below, which makes slash commands show up instantly
   instead of waiting up to an hour for a global sync.

2. **Get an Anthropic API key** at <https://console.anthropic.com/> ->
   API Keys. This is what powers screenshot reading. At this project's
   scale (a couple of games a week) the cost is trivial -- a few cents a
   month at most -- but it does need billing set up on the account. If
   you'd rather use a free-tier vision model instead (e.g. Google Gemini),
   the extraction logic is isolated in `vision.py` -- swap the API call
   there, keep the same JSON contract, and nothing else needs to change.

3. **Configure environment variables.**

   ```bash
   cp .env.example .env
   # then fill in DISCORD_TOKEN, DISCORD_GUILD_ID, ANTHROPIC_API_KEY
   ```

4. **Install dependencies and run.**

   ```bash
   python3 -m venv venv && source venv/bin/activate
   pip install -r requirements.txt
   python run.py
   ```

   This starts the Discord bot and the leaderboard web page (default
   `http://localhost:8080`) in one process. Play a test match, run
   `/report-match` with a screenshot, confirm it, and check the web page
   updates.

## Deploying so it survives after this laptop is closed

This needs to run somewhere always-on, since Discord bots hold a
persistent connection. A couple of reasonable free options for a
low-traffic club bot like this:

**Option A -- Oracle Cloud Free Tier (most robust, genuinely free forever)**
Oracle's Always Free tier includes a small VM that's yours indefinitely,
no trial period to run out. Spin up an Ubuntu instance, install Docker,
then:

```bash
git clone <your repo>
cd valorant-weeklies-bot
cp .env.example .env   # fill in real values
docker build -t weeklies-bot .
docker run -d --restart unless-stopped \
  -p 8080:8080 \
  -v $(pwd)/data:/app/data -e DB_PATH=/app/data/weeklies.db \
  --env-file .env \
  weeklies-bot
```

Open port 8080 in Oracle's security list/firewall if you want the
leaderboard page reachable from outside the VM, and put it behind a
domain + HTTPS (e.g. via Caddy or Nginx) if you want it to look nice for
sharing around campus.

**Option B -- Fly.io or Railway**
Both can deploy straight from the included `Dockerfile`. Free allowances
change fairly often on these platforms, so check current pricing before
committing; either works fine for a bot this light. Set the same env vars
from `.env.example` as secrets/config vars in whichever dashboard you use,
and mount a persistent volume for the SQLite file if the platform
supports one (otherwise your leaderboard resets on every redeploy).

**Option C -- A machine your club already controls**
If your club has a spare machine, a server room box, or similar, that's
often the path of least resistance: install Docker (or just Python) and
run it there with `systemd` (or the Docker command above) so it restarts
on reboot.

Whichever you pick, back up the `data/` folder occasionally (or wherever
you mounted it) -- it holds `weeklies.db` (the entire season's history)
and every confirmed match's screenshot, and it's all that would need
restoring if the VM itself was ever lost.

## Updating the bot with new code later

Database changes (new columns, etc.) apply automatically on the next
startup -- `db.py` migrates an existing `weeklies.db` in place rather than
requiring a fresh one, so redeploying never wipes the season's history.
To ship a code update once you've pushed it to your GitHub repo:

```bash
cd valorant-weeklies-bot   # wherever you cloned it on the VM
git pull
docker stop weeklies && docker rm weeklies
docker build -t weeklies-bot .
docker run -d --name weeklies --restart unless-stopped \
  -p 8080:8080 \
  -v $(pwd)/data:/app/data -e DB_PATH=/app/data/weeklies.db \
  --env-file .env \
  weeklies-bot
docker logs -f weeklies   # confirm it started cleanly
```

## Extending this later

- **Per-round MVP / ACS-based Elo weighting** -- right now every player on
  a team gets the same Elo delta regardless of individual performance,
  even though ACS is now tracked per match. If you want ACS to actually
  influence Elo, `elo.py` is where you'd add that scaling factor.
- **Two-sided confirmation** -- right now anyone can hit Confirm. If you
  want both team captains to have to confirm before it counts, that's a
  small change to `ConfirmMatchView` in `bot.py`.
- **Seasons** -- everything currently accumulates into one running
  leaderboard. Add a `season` column to `matches`/`players` and filter by
  it if you want to reset standings periodically.
- **Manual/fun stats** -- anything Valorant doesn't display anywhere on
  screen (KAST, spike-plant "MVP of the round" type awards, etc.) can't be
  read from a screenshot -- there's nothing there for the vision model to
  see. Tracking those would mean a lightweight manual command instead
  (e.g. a lightweight `/plant @player` tally), not extraction.
