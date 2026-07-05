"""
Gemini parser for Telegram reminder messages.

The parser returns an action envelope:
{
  "action": "add|delete|update|search|upcoming|unknown",
  "events": [...],
  "query": {...},
  "updates": {...},
  "range": "next|week|month|30_days|all"
}

For compatibility with older Gemini responses, a raw JSON list is treated as an
"add" action.
"""

from __future__ import annotations

from datetime import datetime
import json
import logging
import os
from typing import Any

import requests

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.5-flash:generateContent"
)

SYSTEM_PROMPT = """You are the natural-language parser for a Telegram reminder bot.
Return ONLY valid JSON. Do not include markdown, explanations, or comments.

Return this object shape:
{
  "action": "add|delete|update|search|upcoming|unknown",
  "events": [
    {"name": "<person or thing>", "event_type": "<birthday|anniversary|appointment|meeting|other>", "month": <1-12>, "day": <1-31>, "year": <yyyy or null>, "notes": "<extra notes or empty string>"}
  ],
  "query": {"name": "<optional>", "event_type": "<optional>", "month": <optional 1-12>, "day": <optional 1-31>, "year": <optional yyyy>},
  "updates": {"name": "<optional>", "event_type": "<optional>", "month": <optional 1-12>, "day": <optional 1-31>, "year": <optional yyyy or null>, "notes": "<optional>"},
  "range": "next|week|month|30_days|all"
}

Rules:
- Use action "add" for new reminders. Put extracted reminders in events.
- Use action "delete" for delete/remove requests. Put identifying fields in query.
- Use action "update" for edits such as "is actually on", "change", "rename", or note changes. Put the existing reminder identity in query and changed fields in updates.
- Use action "search" for show/list/find/filter requests. Put filters in query.
- Use action "upcoming" for "what's next", "upcoming reminders", "upcoming this week", "upcoming this month", or "next 30 days"; set range accordingly.
- Use action "unknown" when the message is unrelated or missing enough information.
- Understand aliases: bday, bd, b'day, b-day -> birthday; anni, anniv -> anniversary; appt -> appointment; mtg -> meeting.
- Understand Indian/family title words in names. "di" and "didi" are often titles, so "Chinki di bday" and "Chinki didi's birthday" should refer to the same person/title.
- Understand relative dates using the supplied current date: tomorrow, day after tomorrow, next monday, in 10 days, next month.
- Use null year for annual reminders such as birthdays and anniversaries unless the user clearly wants a one-time reminder.
- For one-time reminders such as travel, bills, deadlines, appointments, meetings, calls, tasks, train/flight/bus events, or anything phrased as "remind me to", include a concrete year.
- If a one-time reminder gives a month/day without a year, choose the next upcoming occurrence based on the supplied current date. For example, if today is 2026-07-05, "catch train on 3 June" should use year 2027.
- If the user explicitly says a reminder repeats yearly/every year/annually, use null year.
- If a date is fully known, include month and day. If only searching by month (for example "Show July reminders"), include month only in query.

Examples:
Input: "Rahul bday 2 July"
Output: {"action":"add","events":[{"name":"Rahul","event_type":"birthday","month":7,"day":2,"year":null,"notes":""}],"query":{},"updates":{},"range":"all"}

Input: "chinki di bday 17 july"
Output: {"action":"add","events":[{"name":"Chinki didi","event_type":"birthday","month":7,"day":17,"year":null,"notes":""}],"query":{},"updates":{},"range":"all"}

Input: "Chinki didi's birthday 17 July"
Output: {"action":"add","events":[{"name":"Chinki didi","event_type":"birthday","month":7,"day":17,"year":null,"notes":""}],"query":{},"updates":{},"range":"all"}

Input when current date is 2026-07-05: "Remind me to catch the train on 3 June"
Output: {"action":"add","events":[{"name":"catch the train","event_type":"other","month":6,"day":3,"year":2027,"notes":"one-time reminder"}],"query":{},"updates":{},"range":"all"}

Input when current date is 2026-07-05: "Doctor appointment tomorrow"
Output: {"action":"add","events":[{"name":"Doctor","event_type":"appointment","month":7,"day":6,"year":2026,"notes":"one-time reminder"}],"query":{},"updates":{},"range":"all"}

Input: "Delete Rahul birthday"
Output: {"action":"delete","events":[],"query":{"name":"Rahul","event_type":"birthday"},"updates":{},"range":"all"}

Input: "Delete Rahul 2 July"
Output: {"action":"delete","events":[],"query":{"name":"Rahul","month":7,"day":2},"updates":{},"range":"all"}

Input: "Rahul birthday is actually on 3 July"
Output: {"action":"update","events":[],"query":{"name":"Rahul","event_type":"birthday"},"updates":{"month":7,"day":3},"range":"all"}

Input: "Rename Rahul to Rahul Kumar"
Output: {"action":"update","events":[],"query":{"name":"Rahul"},"updates":{"name":"Rahul Kumar"},"range":"all"}

Input: "Show July reminders"
Output: {"action":"search","events":[],"query":{"month":7},"updates":{},"range":"all"}

Input: "What's next?"
Output: {"action":"upcoming","events":[],"query":{},"updates":{},"range":"next"}
"""


def _empty_action() -> dict[str, Any]:
    return {"action": "unknown", "events": [], "query": {}, "updates": {}, "range": "all"}


def _coerce_action(parsed: Any) -> dict[str, Any]:
    """Normalize Gemini output into the action envelope expected by main.py."""
    if isinstance(parsed, list):
        return {"action": "add", "events": parsed, "query": {}, "updates": {}, "range": "all"}
    if not isinstance(parsed, dict):
        return _empty_action()

    action = parsed.get("action", "unknown")
    if action not in {"add", "delete", "update", "search", "upcoming", "unknown"}:
        action = "unknown"
    events = parsed.get("events") if isinstance(parsed.get("events"), list) else []
    query = parsed.get("query") if isinstance(parsed.get("query"), dict) else {}
    updates = parsed.get("updates") if isinstance(parsed.get("updates"), dict) else {}
    reminder_range = parsed.get("range", "all")
    if reminder_range not in {"next", "week", "month", "30_days", "all"}:
        reminder_range = "all"
    return {
        "action": action,
        "events": events,
        "query": query,
        "updates": updates,
        "range": reminder_range,
    }


def parse_message(text: str, now: datetime | None = None) -> dict[str, Any]:
    """Return a parsed action envelope. Never raises."""
    current = now or datetime.now()
    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [
            {
                "parts": [
                    {
                        "text": (
                            f"Current date: {current:%Y-%m-%d}. "
                            f"Current weekday: {current:%A}.\n"
                            f"User message: {text}"
                        )
                    }
                ]
            }
        ],
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
        return _coerce_action(json.loads(raw))
    except requests.exceptions.RequestException:
        logging.exception("Gemini API request failed")
        return _empty_action()
    except (KeyError, IndexError, json.JSONDecodeError, TypeError):
        logging.exception("Failed to parse Gemini response")
        return _empty_action()
