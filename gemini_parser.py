"""
Uses the free Google Gemini API to turn a free-text message like:
    "Aman's birthday is on 1st September"
or a message with multiple events like:
    "Ayushi's bday on 27th September, Deepti's on 22nd July"
into a list of structured events:
    [{"name": "Aman", "event_type": "birthday", "month": 9, "day": 1, "notes": ""}]

If the message isn't describing any event to remember, returns an empty list.
Any failure (network, API, parsing) also safely returns an empty list rather
than raising -- the caller should always get a reply back, even on failure.

Get a free API key (no credit card needed) at https://ai.google.dev -> "Get API Key".
"""

import os
import json
import logging
import requests

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.5-flash:generateContent"
)

SYSTEM_PROMPT = """You extract reminder-worthy events (birthdays, anniversaries, etc.) from short messages.
A single message may describe ONE event or MULTIPLE events.

Respond with ONLY a JSON array, no other text, no markdown formatting.

Each event in the array should look like:
{"name": "<person or thing's name>", "event_type": "<birthday|anniversary|other>", "month": <1-12>, "day": <1-31>, "notes": "<any extra context, or empty string>"}

If the message describes no events to remember (e.g. it's a question, greeting, or unrelated text), respond with an empty array: []

Examples:
Input: "Aman's birthday is on 1st September"
Output: [{"name": "Aman", "event_type": "birthday", "month": 9, "day": 1, "notes": ""}]

Input: "Ayushi's bday on 27th September, Deepti's on 22nd July"
Output: [{"name": "Ayushi", "event_type": "birthday", "month": 9, "day": 27, "notes": ""}, {"name": "Deepti", "event_type": "birthday", "month": 7, "day": 22, "notes": ""}]

Input: "remind me of my parents' anniversary, it's 15 June"
Output: [{"name": "my parents", "event_type": "anniversary", "month": 6, "day": 15, "notes": ""}]

Input: "hey how are you"
Output: []
"""


def parse_message(text: str) -> list:
    """Returns a list of event dicts (possibly empty). Never raises."""
    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {"response_mime_type": "application/json"},
    }
    try:
        response = requests.post(
            f"{GEMINI_URL}?key={GEMINI_API_KEY}",
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        raw = data["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(raw)

        if not isinstance(parsed, list):
            return []
        events = []
        for item in parsed:
            if all(k in item for k in ("name", "event_type", "month", "day")):
                events.append(item)
        return events

    except requests.exceptions.RequestException as e:
        logging.error(f"Gemini API request failed: {e}")
        return []
    except (KeyError, IndexError, json.JSONDecodeError, TypeError) as e:
        logging.error(f"Failed to parse Gemini response: {e}")
        return []
