#!/usr/bin/env python3
"""Meridian — Morning/Evening Brief agent.

Reads the live data in site/data/ and asks Claude to write the brief that
appears in the champagne panel on the dashboard. Writes site/data/brief.json.

Requires ANTHROPIC_API_KEY in the environment (GitHub Actions secret in CI).
Exits gracefully (keeping the previous brief) when the key is absent so the
data pull never fails because of the brief.

Run after scripts/pull.py:  python3 scripts/pull.py && python3 scripts/brief.py
"""
import datetime as dt
import json
import pathlib
import sys
import zoneinfo

TZ = zoneinfo.ZoneInfo("America/New_York")

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "site" / "data"

BRIEF_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {
            "type": "string",
            "description": "One elegant sentence, 8-16 words, lowercase-after-first-word style, no ending period needed but allowed. Sets the tone for the day.",
        },
        "paras": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Two short paragraphs (2-3 sentences each). First: weather and how to plan the day around it. Second: markets and the most noteworthy news.",
        },
        "signoff": {
            "type": "string",
            "description": "A short italic-style signoff line starting with an em dash, e.g. '— composed at dawn, from 214 sources'",
        },
    },
    "required": ["headline", "paras", "signoff"],
    "additionalProperties": False,
}


def load(name):
    p = DATA / f"{name}.json"
    return json.loads(p.read_text()) if p.exists() else None


def main() -> int:
    import os

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("brief: ANTHROPIC_API_KEY not set — keeping existing brief.json")
        return 0

    import anthropic

    weather = load("weather")
    markets = load("markets")
    news = load("news")
    if not (weather and markets and news):
        print("brief: missing data files — run pull.py first")
        return 1

    now = dt.datetime.now(TZ)
    edition = "morning" if now.hour < 14 else "evening"

    payload = {
        "now": now.strftime("%A %d %B %Y, %H:%M"),
        "edition": edition,
        "weather_raleigh": weather,
        "markets": markets,
        "news_headlines": [
            {"kicker": s["kicker"], "title": s["title"], "source": s["source"]}
            for c in news["columns"]
            for s in c["stories"]
        ],
    }

    client = anthropic.Anthropic()
    response = client.beta.messages.create(
        model="claude-opus-5",
        max_tokens=2048,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=(
            "You write the daily brief for 'Meridian', a private personal "
            "dashboard styled like a Swiss luxury watch. Voice: elegant, warm, "
            "concise, personal — like a trusted valet who reads the papers. "
            "The owner lives in the Raleigh-Durham area (the Triangle, NC), follows "
            "US index funds, Indian markets, and metals. Use ONLY the data "
            "provided; never invent events, appointments, or health facts. "
            "Weather temperatures are Fahrenheit. Mention 2-3 of the most "
            "consequential headlines at most, woven into prose."
        ),
        output_config={"format": {"type": "json_schema", "schema": BRIEF_SCHEMA}},
        messages=[{
            "role": "user",
            "content": (
                f"Write the {edition} brief from this data:\n\n"
                + json.dumps(payload, ensure_ascii=False)
            ),
        }],
    )

    if response.stop_reason == "refusal":
        print("brief: request was declined — keeping existing brief.json")
        return 0

    text = next(b.text for b in response.content if b.type == "text")
    brief = json.loads(text)
    brief["sample"] = False
    (DATA / "brief.json").write_text(json.dumps(brief, indent=2, ensure_ascii=False))
    print(f"brief: wrote {edition} edition — “{brief['headline']}”")
    return 0


if __name__ == "__main__":
    sys.exit(main())
