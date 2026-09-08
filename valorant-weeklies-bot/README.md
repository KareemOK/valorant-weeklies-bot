# Valorant Weeklies Bot

A small, self-hosted Discord bot for a weekly Valorant pickup night:

- `/link` -- players register their Riot ID once
- `/balance` -- split a pool of players into two Elo-balanced teams
- `/report-match` -- upload a screenshot of the post-game scoreboard; the
  bot reads it with Claude's vision model, shows you what it extracted,
  and only saves it once someone hits **Confirm**
- `/leaderboard`, `/stats` -- season standings, in Discord
- a small companion web page (same data, easier to browse/share) showing
  the leaderboard and recent match history

No dependency on Riot's API or any unofficial scraper -- it only ever reads
what's on screen in a screenshot someone chose to upload, and a human
confirms it before it's scored. That sidesteps the class of "bot silently
breaks because Riot changed something upstream" problem that a lot of
auto-detecting queue bots (NeatQueue included) run into.

## How it works, end to end

1. Everyone plays their custom game in Valorant as normal (teams picked via
   `/balance`, or Valorant's own in-game team randomizer -- either works,
   the bot doesn't care how teams were formed).
2. At the end of the match, anyone screenshots the scoreboard (Tab screen,
   or the post-match summary) and runs `/report-match` with that image
   attached.
3. The bot sends the image to Claude, gets back structured per-player
   stats + winner, matches each in-game name to a linked Discord account,
   and posts an embed showing exactly what it read.
4. Someone confirms (ideally a captain from each team, so nobody can
   quietly submit a doctored screenshot) and the match is saved: Elo
   updates, K/D/A accumulates, the leaderboard updates immediately.

Anyone the bot couldn't match to a Discord account (because they haven't
run `/link` yet) is called out in that confirmation message and just won't
be scored for that match -- get your regulars to `/link` once and this
stops coming up.

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

Whichever you pick, back up `weeklies.db` occasionally (or point `DB_PATH`
at a mounted volume) -- it's the entire season's history and it's just a
single file.

## Extending this later

- **Per-round MVP / ACS-based Elo weighting** -- right now every player on
  a team gets the same Elo delta. If you want individual performance to
  matter, `elo.py` is where you'd add a scaling factor.
- **Two-sided confirmation** -- right now anyone can hit Confirm. If you
  want both team captains to have to confirm before it counts, that's a
  small change to `ConfirmMatchView` in `bot.py`.
- **Seasons** -- everything currently accumulates into one running
  leaderboard. Add a `season` column to `matches`/`players` and filter by
  it if you want to reset standings periodically.
