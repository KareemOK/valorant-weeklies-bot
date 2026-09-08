"""
Turns a screenshot of a VALORANT post-game scoreboard into structured data
using a vision-capable Claude model, instead of scraping any Valorant API.

This is deliberately provider-agnostic-ish: the extraction prompt and JSON
contract live here, separate from Discord/db code, so swapping models (or
adding a second provider like Gemini) later is a one-file change.
"""

import base64
import json
import os

from anthropic import Anthropic

# Check https://docs.claude.com/en/docs/about-claude/models for the current
# recommended small/cheap vision-capable model id and update this default
# (or just set ANTHROPIC_MODEL in your .env -- no code change needed).
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5")

EXTRACTION_PROMPT = """\
You are reading a screenshot of VALORANT's post-match summary screen, on
the "Scoreboard" tab. This screen lists every player in the match together
in one list sorted by Combat Score (this could be 10 players for a 5v5, 6
for a 3v3, or any other custom match size) -- it does NOT group them into
two separate blocks by side. Extract every player row you can see, whatever
the total count turns out to be.

There are exactly two team colors on this screen, and there are TWO
different visual signals that can indicate a row's team -- they will not
always agree, and when they don't, trust the second one:
1. Most rows have their whole background tinted one of the two team
   colors.
2. The row belonging to whoever's account took the screenshot gets a
   special "this is you" treatment instead -- typically an olive/gold/tan
   overall tint, sometimes with a chevron or arrow shape -- which visually
   overrides the plain team-color fill. That row still belongs to one of
   the two real teams, NOT a third category. Look at the thin colored
   accent stripe/border on the left edge of that row (it's a much smaller
   area than the row's main fill and keeps reflecting the true team color
   even when the rest of the row is highlighted specially) to figure out
   which of the two teams it actually belongs to, and group it there. Do
   not default to grouping the "this is you" row with whichever team has
   more plain-colored rows -- decide it independently from that thin
   accent color.

If a match has an even number of players, the two teams are almost always
equal size (e.g. 3v3, 5v5) -- if your grouping comes out uneven for an
even player count, that's a strong signal you mis-assigned the "this is
you" row and should re-examine it before finalizing.

At the top of the screen there are two numbers with a result word between
them (e.g. "4  DEFEAT  13" or "13  VICTORY  6"). The left-hand number and
the result word both describe the outcome for the team that the
locally-highlighted ("this is you") row belongs to, using the same
team-assignment logic above. The right-hand number is the other team's
score.

Extract everything you can read and return ONLY valid JSON, no other text,
matching exactly this shape:

{
  "map_name": "<map name if visible, else null>",
  "winner": "team1" | "team2" | "draw" | "unknown",
  "team1_score": <int>,
  "team2_score": <int>,
  "team1": [
    {"riot_name": "<name as shown, include the tag after # if visible>",
     "agent": "<agent name if visible, else null>",
     "kills": <int>, "deaths": <int>, "assists": <int>,
     "acs": <int, the Avg Combat Score column, or null if not legible>,
     "first_bloods": <int, or null if not legible>,
     "plants": <int, or null if not legible>,
     "defuses": <int, or null if not legible>,
     "econ_rating": <int, or null if not legible>,
     "is_you": <true if this is the "this is you" highlighted row
                (the one whose account took the screenshot), else false>}
  ],
  "team2": [ ... same shape ... ]
}

Rules:
- Group players into "team1" / "team2" using each row's BACKGROUND COLOR,
  not their position in the list -- this scoreboard interleaves both teams
  together sorted by Combat Score, so position tells you nothing about
  team membership.
- It doesn't matter which of the two colors you call "team1" vs "team2",
  as long as you're consistent between the player groupings, the scores,
  and the winner.
- Exactly one player should have "is_you": true (the highlighted row);
  everyone else should have "is_you": false. If you genuinely can't tell
  which row (if any) has the special highlight, it's fine for every player
  to have "is_you": false.
- Match "team1_score" to whichever color you assigned to team1, using the
  top-of-screen score/result readout described above to figure out which
  score belongs to which color.
- If you cannot confidently match the scores/colors together, still report
  both team1_score and team2_score using left-to-right order as shown on
  screen, but set winner to "unknown" rather than guessing.
- If a numeric stat is not legible or not present on screen, use null for
  it rather than guessing a value or omitting the field.
- Return JSON only. No markdown code fences, no commentary.
"""


class ExtractionError(Exception):
    pass


def extract_scoreboard(image_bytes: bytes, media_type: str = "image/png") -> dict:
    """
    Sends the screenshot to Claude and returns the parsed JSON dict described
    in EXTRACTION_PROMPT. Raises ExtractionError if the model didn't return
    parseable JSON (rare, but happens with a blurry/cropped screenshot).
    """
    client = Anthropic()  # reads ANTHROPIC_API_KEY from the environment

    b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": b64,
                        },
                    },
                    {"type": "text", "text": EXTRACTION_PROMPT},
                ],
            }
        ],
    )

    text = "".join(
        block.text for block in response.content if getattr(block, "type", None) == "text"
    ).strip()

    # Be forgiving of accidental code fences even though the prompt asks
    # the model not to use them.
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ExtractionError(f"Model did not return valid JSON: {e}\nRaw response:\n{text}")

    for key in ("team1", "team2", "winner"):
        if key not in data:
            raise ExtractionError(f"Missing '{key}' in extracted data: {data}")

    data.setdefault("team1_score", None)
    data.setdefault("team2_score", None)
    data.setdefault("map_name", None)

    return data
