"""
Uses the Claude API to turn a free-text message like:
    "Aman's birthday is on 1st September"
into structured JSON:
    {"is_event": true, "name": "Aman", "event_type": "birthday", "month": 9, "day": 1}

If the message isn't describing an event to remember, returns {"is_event": false}.
"""

import os
import json
import anthropic

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

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
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": text}],
    )
    raw = response.content[0].text.strip()
    # Strip accidental markdown fences just in case
    raw = raw.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"is_event": False}
