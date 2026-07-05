"""
Uses the free Google Gemini API to turn a free-text message like:
    "Aman's birthday is on 1st September"
into structured JSON:
    {"is_event": true, "name": "Aman", "event_type": "birthday", "month": 9, "day": 1}

If the message isn't describing an event to remember, returns {"is_event": false}.

Get a free API key (no credit card needed) at https://ai.google.dev -> "Get API Key".
"""

import os
import json
import requests

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.5-flash:generateContent"
)

SYSTEM_PROMPT = """You extract reminder-worthy events (birthdays, anniversaries, etc.) from short messages.

Respond with ONLY a JSON object, no other text, no markdown formatting.

If the message describes a date to remember, respond with:
{"is_event": true, "name": "<person or thing's name>", "event_type": "<birthday|anniversary|other>", "month": <1-12>, "day": <1-31>, "notes": "<any extra context, or empty string>"}

If the message is NOT describing an event to remember (e.g. it's a question, greeting, or unrelated text), respond with:
{"is_event": false}

Examples:
Input: "Aman's birthday is on 1st September"
Output: {"is_event": true, "name": "Aman", "event_type": "birthday", "month": 9, "day": 1, "notes": ""}

Input: "remind me of my parents' anniversary, it's 15 June"
Output: {"is_event": true, "name": "my parents", "event_type": "anniversary", "month": 6, "day": 15, "notes": ""}

Input: "hey how are you"
Output: {"is_event": false}
"""


def parse_message(text: str) -> dict:
    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {"response_mime_type": "application/json"},
    }
    response = requests.post(
        f"{GEMINI_URL}?key={GEMINI_API_KEY}",
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()

    try:
        raw = data["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(raw)
    except (KeyError, IndexError, json.JSONDecodeError):
        return {"is_event": False}
