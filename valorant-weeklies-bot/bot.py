"""
Valorant Weeklies Discord bot.

Commands:
  /link riot_name:<Name#Tag>          -- register your Valorant IGN
  /report-match screenshot:<image>    -- parse a scoreboard screenshot,
                                          then confirm before it's saved
  /balance @player @player ...        -- split a list of players into two
                                          Elo-balanced teams
  /leaderboard                        -- top players by Elo
  /stats [@player]                    -- one player's season stats

Run `python bot.py` with DISCORD_TOKEN and ANTHROPIC_API_KEY set (see
.env.example / README.md).
"""

import io
import logging
import os

import discord
from discord import app_commands
from dotenv import load_dotenv

import db
import elo
import vision

load_dotenv()

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("weeklies-bot")

GUILD_ID = os.environ.get("DISCORD_GUILD_ID")  # optional: instant command sync to one server

intents = discord.Intents.default()
intents.members = True


class WeekliesClient(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        db.init_db()
        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("Synced commands to guild %s", GUILD_ID)
        else:
            await self.tree.sync()
            log.info("Synced global commands (can take up to an hour to appear)")


client = WeekliesClient()


# ---------------------------------------------------------------------------
# /link
# ---------------------------------------------------------------------------

@client.tree.command(description="Register your Riot ID so match screenshots can be matched to you")
@app_commands.describe(riot_name="Your Riot ID, e.g. Sova#EU1")
async def link(interaction: discord.Interaction, riot_name: str):
    db.upsert_player(
        discord_id=str(interaction.user.id),
        display_name=interaction.user.display_name,
        riot_name=riot_name,
    )
    await interaction.response.send_message(
        f"Linked **{interaction.user.display_name}** to Riot ID `{riot_name}`.", ephemeral=True
    )


# ---------------------------------------------------------------------------
# /balance
# ---------------------------------------------------------------------------

@client.tree.command(description="Split players into two Elo-balanced teams")
@app_commands.describe(
    players="Mention everyone playing this round, e.g. @a @b @c @d @e @f @g @h @i @j"
)
async def balance(interaction: discord.Interaction, players: str):
    user_ids = [m.strip("<@!>") for m in players.split() if m.startswith("<@")]

    if len(user_ids) < 2:
        await interaction.response.send_message(
            "Mention at least 2 players, e.g. `/balance players:@a @b @c @d`", ephemeral=True
        )
        return

    elos = {}
    unlinked = []
    for uid in user_ids:
        row = db.get_player(uid)
        if row is None:
            db.upsert_player(uid, display_name=uid)
            row = db.get_player(uid)
        elos[uid] = row["elo"]

    team1, team2 = elo.balance_teams(elos)

    def fmt(team):
        return "\n".join(f"<@{uid}> ({int(elos[uid])})" for uid in team)

    avg1 = sum(elos[u] for u in team1) / len(team1)
    avg2 = sum(elos[u] for u in team2) / len(team2)

    embed = discord.Embed(title="Balanced Teams", color=discord.Color.blurple())
    embed.add_field(name=f"Team 1 (avg {int(avg1)})", value=fmt(team1) or "-", inline=True)
    embed.add_field(name=f"Team 2 (avg {int(avg2)})", value=fmt(team2) or "-", inline=True)
    await interaction.response.send_message(embed=embed)


# ---------------------------------------------------------------------------
# /leaderboard
# ---------------------------------------------------------------------------

@client.tree.command(description="Show the season leaderboard")
async def leaderboard(interaction: discord.Interaction):
    rows = db.get_leaderboard(limit=15)
    if not rows:
        await interaction.response.send_message("No matches recorded yet.")
        return

    lines = []
    for i, r in enumerate(rows, start=1):
        kd = r["kills"] / r["deaths"] if r["deaths"] else float(r["kills"])
        lines.append(
            f"**{i}. {r['display_name']}** -- {int(r['elo'])} Elo | "
            f"{r['wins']}W-{r['losses']}L | {kd:.2f} K/D"
        )

    embed = discord.Embed(
        title="Valorant Weeklies -- Season Leaderboard",
        description="\n".join(lines),
        color=discord.Color.gold(),
    )
    await interaction.response.send_message(embed=embed)


# ---------------------------------------------------------------------------
# /stats
# ---------------------------------------------------------------------------

@client.tree.command(description="Show a player's season stats")
@app_commands.describe(player="Whose stats to show (defaults to you)")
async def stats(interaction: discord.Interaction, player: discord.Member | None = None):
    target = player or interaction.user
    row = db.get_player(str(target.id))
    if row is None or row["games_played"] == 0:
        await interaction.response.send_message(f"{target.display_name} hasn't played a match yet.")
        return

    kd = row["kills"] / row["deaths"] if row["deaths"] else float(row["kills"])
    embed = discord.Embed(title=f"{target.display_name}'s stats", color=discord.Color.green())
    embed.add_field(name="Elo", value=int(row["elo"]))
    embed.add_field(name="Record", value=f"{row['wins']}W-{row['losses']}L")
    embed.add_field(name="K/D/A", value=f"{row['kills']}/{row['deaths']}/{row['assists']} ({kd:.2f})")
    embed.add_field(name="Games played", value=row["games_played"])
    await interaction.response.send_message(embed=embed)


# ---------------------------------------------------------------------------
# /report-match
# ---------------------------------------------------------------------------

class ConfirmMatchView(discord.ui.View):
    def __init__(self, extracted: dict, team1_players: list[dict], team2_players: list[dict],
                 winner: str, reporter_id: str):
        super().__init__(timeout=300)
        self.team1_players = team1_players
        self.team2_players = team2_players
        self.winner = winner
        self.reporter_id = reporter_id
        self.map_name = extracted.get("map_name")

    @discord.ui.button(label="Confirm & Save", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.winner not in ("team1", "team2", "draw"):
            await interaction.response.send_message(
                "Couldn't tell who won from the screenshot -- re-run /report-match with a "
                "clearer image, or ask a mod to enter this one manually.",
                ephemeral=True,
            )
            return

        team1_elos = {p["discord_id"]: db.get_player(p["discord_id"])["elo"] for p in self.team1_players}
        team2_elos = {p["discord_id"]: db.get_player(p["discord_id"])["elo"] for p in self.team2_players}

        updates = elo.update_team_elos(team1_elos, team2_elos, self.winner)

        db.record_match(
            winner=self.winner,
            reported_by=self.reporter_id,
            team1=self.team1_players,
            team2=self.team2_players,
            elo_updates=updates,
            map_name=self.map_name,
        )

        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="Match saved! Leaderboard updated. ✅", view=self
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="Cancelled -- nothing saved.", view=self)


def _build_summary_embed(extracted: dict, team1_players: list[dict], team2_players: list[dict],
                          unmatched: list[str], winner: str) -> discord.Embed:
    def fmt(team):
        if not team:
            return "-"
        return "\n".join(
            f"<@{p['discord_id']}> ({p.get('agent') or '?'}) "
            f"{p['kills']}/{p['deaths']}/{p['assists']}"
            for p in team
        )

    embed = discord.Embed(
        title="Match report -- please confirm",
        description=f"Map: {extracted.get('map_name') or 'unknown'} | Winner: **{winner}**",
        color=discord.Color.orange(),
    )
    embed.add_field(name="Team 1", value=fmt(team1_players), inline=True)
    embed.add_field(name="Team 2", value=fmt(team2_players), inline=True)
    if unmatched:
        embed.add_field(
            name="Not matched to a Discord account (won't be scored)",
            value="\n".join(unmatched) + "\n\nThey should run `/link <RiotName#Tag>` for next time.",
            inline=False,
        )
    embed.set_footer(text="Double-check the read stats before confirming -- this writes to the season leaderboard.")
    return embed


@client.tree.command(name="report-match", description="Report a match from a scoreboard screenshot")
@app_commands.describe(screenshot="Screenshot of the end-of-match scoreboard")
async def report_match(interaction: discord.Interaction, screenshot: discord.Attachment):
    await interaction.response.defer(thinking=True)

    if not (screenshot.content_type or "").startswith("image/"):
        await interaction.followup.send("That attachment doesn't look like an image.")
        return

    image_bytes = await screenshot.read()
    media_type = screenshot.content_type or "image/png"

    try:
        extracted = vision.extract_scoreboard(image_bytes, media_type=media_type)
    except vision.ExtractionError as e:
        log.warning("Extraction failed: %s", e)
        await interaction.followup.send(
            "Couldn't read that screenshot reliably. Try a clearer / uncropped shot of the "
            "full scoreboard."
        )
        return

    def resolve_team(raw_players: list[dict]):
        matched, unmatched_names = [], []
        for rp in raw_players:
            row = db.find_player_by_riot_name(rp.get("riot_name") or "")
            if row is None:
                unmatched_names.append(rp.get("riot_name") or "(unreadable name)")
                continue
            matched.append(
                {
                    "discord_id": row["discord_id"],
                    "agent": rp.get("agent"),
                    "kills": rp.get("kills", 0),
                    "deaths": rp.get("deaths", 0),
                    "assists": rp.get("assists", 0),
                }
            )
        return matched, unmatched_names

    team1_players, unmatched1 = resolve_team(extracted.get("team1", []))
    team2_players, unmatched2 = resolve_team(extracted.get("team2", []))
    unmatched = unmatched1 + unmatched2
    winner = extracted.get("winner", "unknown")

    if not team1_players or not team2_players:
        await interaction.followup.send(
            "Couldn't match enough players from that screenshot to linked Discord accounts. "
            "Make sure everyone has run `/link <RiotName#Tag>`, then try again.",
            embed=_build_summary_embed(extracted, team1_players, team2_players, unmatched, winner),
        )
        return

    embed = _build_summary_embed(extracted, team1_players, team2_players, unmatched, winner)
    view = ConfirmMatchView(extracted, team1_players, team2_players, winner, str(interaction.user.id))
    await interaction.followup.send(embed=embed, view=view)


def main():
    token = os.environ["DISCORD_TOKEN"]
    client.run(token)


if __name__ == "__main__":
    main()
