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
You are reading a screenshot of a VALORANT post-game scoreboard (the tab
screen or the end-of-match summary screen). Extract every player you can
read and return ONLY valid JSON, no other text, matching exactly this
shape:

{
  "map_name": "<map name if visible, else null>",
  "winner": "team1" | "team2" | "draw" | "unknown",
  "team1": [
    {"riot_name": "<name as shown, include the tag after # if visible>",
     "agent": "<agent name if visible, else null>",
     "kills": <int>, "deaths": <int>, "assists": <int>}
  ],
  "team2": [ ... same shape ... ]
}

Rules:
- "team1" is whichever team is listed first / on top of the scoreboard,
  "team2" the other team. Do not try to guess which is "attackers" or
  "defenders" -- just preserve the on-screen grouping.
- If you cannot confidently tell who won from this image, set winner to
  "unknown" rather than guessing.
- If a stat is not legible, use 0 for numbers and null for text rather than
  omitting the field.
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

    return data
