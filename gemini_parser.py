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

from datetime import datetime, timedelta
import json
import logging
import os
import re
from typing import Any

import requests

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
OPENAI_URL = "https://api.openai.com/v1/responses"

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.5-flash:generateContent"
)

MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

EVENT_ALIASES = {
    "bday": "birthday",
    "bd": "birthday",
    "birthday": "birthday",
    "birth day": "birthday",
    "anni": "anniversary",
    "anniv": "anniversary",
    "anniversary": "anniversary",
    "appt": "appointment",
    "appointment": "appointment",
    "mtg": "meeting",
    "meeting": "meeting",
}

EVENT_PATTERN = r"\b(b'?day|b-day|bd|birthday|birth day|anni|anniv|anniversary|appt|appointment|mtg|meeting)\b"
DATE_PATTERN = (
    r"\b(?P<day>\d{1,2})(?:st|nd|rd|th)?\s+"
    r"(?P<month>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
    r"(?:\s+(?P<year>\d{4}))?\b"
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

OPENAI_JSON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["action", "events", "query", "updates", "range"],
    "properties": {
        "action": {"type": "string", "enum": ["add", "delete", "update", "search", "upcoming", "unknown"]},
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "event_type", "month", "day", "year", "notes"],
                "properties": {
                    "name": {"type": "string"},
                    "event_type": {"type": "string"},
                    "month": {"type": "integer"},
                    "day": {"type": "integer"},
                    "year": {"type": ["integer", "null"]},
                    "notes": {"type": "string"},
                },
            },
        },
        "query": {
            "type": "object",
            "additionalProperties": False,
            "required": ["name", "event_type", "month", "day", "year"],
            "properties": {
                "name": {"type": ["string", "null"]},
                "event_type": {"type": ["string", "null"]},
                "month": {"type": ["integer", "null"]},
                "day": {"type": ["integer", "null"]},
                "year": {"type": ["integer", "null"]},
            },
        },
        "updates": {
            "type": "object",
            "additionalProperties": False,
            "required": ["name", "event_type", "month", "day", "year", "notes"],
            "properties": {
                "name": {"type": ["string", "null"]},
                "event_type": {"type": ["string", "null"]},
                "month": {"type": ["integer", "null"]},
                "day": {"type": ["integer", "null"]},
                "year": {"type": ["integer", "null"]},
                "notes": {"type": ["string", "null"]},
            },
        },
        "range": {"type": "string", "enum": ["next", "week", "month", "30_days", "all"]},
    },
}


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


def _normalize_event_alias(value: str | None) -> str:
    """Normalize event words used by the local fallback parser."""
    if not value:
        return "other"
    cleaned = re.sub(r"[-\s]+", " ", value.strip().casefold().replace("'", ""))
    if cleaned == "b day":
        cleaned = "bday"
    return EVENT_ALIASES.get(cleaned, cleaned or "other")


def _clean_name(value: str) -> str:
    """Clean a locally parsed reminder name."""
    cleaned = value.strip()
    cleaned = re.sub(r"\bday after tomorrow\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\btomorrow\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bnext\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bin\s+\d{1,3}\s+days?\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^(remind me\s+(?:to|for|about)?\s*)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^(please\s+)?", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(EVENT_PATTERN, "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(is|on|for|about|actually|to|the|a|an)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"['’]s\b", "", cleaned)
    cleaned = re.sub(r"\bdi\b", "didi", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.-")
    return cleaned[:1].upper() + cleaned[1:] if cleaned else ""


def _next_year_for(month: int, day: int, current: datetime) -> int:
    """Return the year for the next occurrence of a month/day pair."""
    year = current.year
    try:
        candidate = datetime(year, month, day, tzinfo=current.tzinfo)
    except ValueError:
        return year
    if candidate.date() < current.date():
        return year + 1
    return year


def _date_from_relative(text: str, current: datetime) -> tuple[int, int, int] | None:
    """Parse common relative dates into month/day/year."""
    normalized = text.casefold()
    target = None
    if "day after tomorrow" in normalized:
        target = current + timedelta(days=2)
    elif "tomorrow" in normalized:
        target = current + timedelta(days=1)
    else:
        in_days = re.search(r"\bin\s+(\d{1,3})\s+days?\b", normalized)
        if in_days:
            target = current + timedelta(days=int(in_days.group(1)))
        else:
            weekday_match = re.search(r"\bnext\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", normalized)
            if weekday_match:
                weekday = WEEKDAYS[weekday_match.group(1)]
                days_ahead = (weekday - current.weekday()) % 7
                target = current + timedelta(days=days_ahead or 7)
    if not target:
        return None
    return target.month, target.day, target.year


def _date_from_text(text: str, current: datetime) -> tuple[int, int, int | None, str] | None:
    """Parse explicit or relative dates from text."""
    relative = _date_from_relative(text, current)
    if relative:
        month, day, year = relative
        return month, day, year, text

    match = re.search(DATE_PATTERN, text, flags=re.IGNORECASE)
    if not match:
        return None
    month = MONTHS[match.group("month").casefold()]
    day = int(match.group("day"))
    year_text = match.group("year")
    year = int(year_text) if year_text else None
    return month, day, year, text[: match.start()] + " " + text[match.end() :]


def _is_one_time_message(text: str, event_type: str, explicit_year: int | None) -> bool:
    """Decide whether a parsed add should be one-time or annual."""
    if explicit_year:
        return True
    normalized = text.casefold()
    if re.search(r"\b(every year|yearly|annually|annual)\b", normalized):
        return False
    if event_type in {"birthday", "anniversary"}:
        return False
    return bool(
        re.search(
            r"\b(remind me|appointment|appt|meeting|mtg|train|flight|bus|bill|deadline|task|call|exam|interview|ticket)\b",
            normalized,
        )
    )


def _local_delete_or_search(text: str) -> dict[str, Any] | None:
    """Parse simple delete and search messages locally."""
    normalized = text.strip().casefold()
    action = None
    remainder = text.strip()
    if normalized.startswith(("delete ", "remove ")):
        action = "delete"
        remainder = re.sub(r"^(delete|remove)\s+", "", remainder, flags=re.IGNORECASE)
    elif normalized.startswith(("show ", "find ", "list ")):
        action = "search"
        remainder = re.sub(r"^(show|find|list)\s+", "", remainder, flags=re.IGNORECASE)
        remainder = re.sub(r"\b(reminders?|events?)\b", "", remainder, flags=re.IGNORECASE).strip()
    if not action:
        return None

    query: dict[str, Any] = {}
    date_bits = _date_from_text(remainder, datetime.now()) if re.search(DATE_PATTERN, remainder, re.IGNORECASE) else None
    if date_bits:
        query["month"], query["day"], query["year"], remainder = date_bits
    else:
        for month_name, month in MONTHS.items():
            if re.search(rf"\b{re.escape(month_name)}\b", remainder, flags=re.IGNORECASE):
                query["month"] = month
                remainder = re.sub(rf"\b{re.escape(month_name)}\b", "", remainder, flags=re.IGNORECASE)
                break

    event_match = re.search(EVENT_PATTERN, remainder, flags=re.IGNORECASE)
    if event_match:
        query["event_type"] = _normalize_event_alias(event_match.group(1))
        remainder = remainder[: event_match.start()] + " " + remainder[event_match.end() :]

    name = _clean_name(remainder)
    if name and name.casefold() not in {"reminder", "reminders", "event", "events"}:
        query["name"] = name
    return {"action": action, "events": [], "query": query, "updates": {}, "range": "all"}


def _local_update(text: str, current: datetime) -> dict[str, Any] | None:
    """Parse common edit messages locally."""
    rename = re.search(r"^rename\s+(.+?)\s+to\s+(.+)$", text, flags=re.IGNORECASE)
    if rename:
        return {
            "action": "update",
            "events": [],
            "query": {"name": _clean_name(rename.group(1))},
            "updates": {"name": _clean_name(rename.group(2))},
            "range": "all",
        }

    if not re.search(r"\b(actually|change|update)\b", text, flags=re.IGNORECASE):
        return None
    date_bits = _date_from_text(text, current)
    if not date_bits:
        return None
    month, day, year, remainder = date_bits
    event_match = re.search(EVENT_PATTERN, remainder, flags=re.IGNORECASE)
    event_type = _normalize_event_alias(event_match.group(1)) if event_match else None
    if event_match:
        remainder = remainder[: event_match.start()] + " " + remainder[event_match.end() :]
    remainder = re.sub(r"\b(is|actually|on|change|update|to)\b", " ", remainder, flags=re.IGNORECASE)
    query = {"name": _clean_name(remainder)}
    if event_type:
        query["event_type"] = event_type
    updates: dict[str, Any] = {"month": month, "day": day}
    if year:
        updates["year"] = year
    return {"action": "update", "events": [], "query": query, "updates": updates, "range": "all"}


def _local_add(text: str, current: datetime) -> dict[str, Any] | None:
    """Parse common add reminders locally."""
    date_bits = _date_from_text(text, current)
    if not date_bits:
        return None
    month, day, year, remainder = date_bits
    event_match = re.search(EVENT_PATTERN, remainder, flags=re.IGNORECASE)
    event_type = _normalize_event_alias(event_match.group(1)) if event_match else "other"
    name = _clean_name(remainder)
    if not name:
        return None
    if _is_one_time_message(text, event_type, year):
        year = year or _next_year_for(month, day, current)
    else:
        year = None
    notes = "one-time reminder" if year else ""
    return {
        "action": "add",
        "events": [
            {
                "name": name,
                "event_type": event_type,
                "month": month,
                "day": day,
                "year": year,
                "notes": notes,
            }
        ],
        "query": {},
        "updates": {},
        "range": "all",
    }


def local_parse_message(text: str, now: datetime | None = None) -> dict[str, Any]:
    """Parse common messages without Gemini so the bot survives rate limits."""
    current = now or datetime.now()
    normalized = text.strip().casefold().rstrip("?.!")
    if normalized in {"what's next", "whats next", "what is next", "upcoming reminders", "upcoming"}:
        return {"action": "upcoming", "events": [], "query": {}, "updates": {}, "range": "next"}
    if normalized in {"upcoming this week", "this week"}:
        return {"action": "upcoming", "events": [], "query": {}, "updates": {}, "range": "week"}
    if normalized in {"upcoming this month", "this month"}:
        return {"action": "upcoming", "events": [], "query": {}, "updates": {}, "range": "month"}
    if normalized in {"next 30 days", "upcoming next 30 days"}:
        return {"action": "upcoming", "events": [], "query": {}, "updates": {}, "range": "30_days"}

    for parser in (_local_delete_or_search, lambda value: _local_update(value, current), lambda value: _local_add(value, current)):
        parsed = parser(text)
        if parsed and parsed.get("action") != "unknown":
            return parsed
    return _empty_action()


def _parser_input(text: str, current: datetime) -> str:
    """Build the user input passed to the model parser."""
    return (
        f"Current date: {current:%Y-%m-%d}. "
        f"Current weekday: {current:%A}.\n"
        f"User message: {text}"
    )


def _parse_openai_output(data: dict[str, Any]) -> dict[str, Any]:
    """Extract JSON text from a Responses API response."""
    raw = data.get("output_text")
    if isinstance(raw, str) and raw.strip():
        return _coerce_action(json.loads(raw))

    for item in data.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                return _coerce_action(json.loads(content["text"]))
    return _empty_action()


def _parse_with_openai(text: str, current: datetime) -> dict[str, Any]:
    """Parse with OpenAI Responses API."""
    payload = {
        "model": OPENAI_MODEL,
        "instructions": SYSTEM_PROMPT,
        "input": _parser_input(text, current),
        "text": {
            "format": {
                "type": "json_schema",
                "name": "reminder_parse",
                "strict": True,
                "schema": OPENAI_JSON_SCHEMA,
            }
        },
        "max_output_tokens": 800,
    }
    response = requests.post(
        OPENAI_URL,
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    return _parse_openai_output(response.json())


def _parse_with_gemini(text: str, current: datetime) -> dict[str, Any]:
    """Parse with Gemini."""
    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [
            {
                "parts": [{"text": _parser_input(text, current)}]
            }
        ],
        "generationConfig": {"response_mime_type": "application/json"},
    }
    response = requests.post(
        f"{GEMINI_URL}?key={GEMINI_API_KEY}",
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    raw = data["candidates"][0]["content"]["parts"][0]["text"]
    return _coerce_action(json.loads(raw))


def parse_message(text: str, now: datetime | None = None) -> dict[str, Any]:
    """Return a parsed action envelope. Never raises."""
    current = now or datetime.now()
    local = local_parse_message(text, current)
    if local.get("action") != "unknown":
        return local

    try:
        if OPENAI_API_KEY:
            return _parse_with_openai(text, current)
        if GEMINI_API_KEY:
            return _parse_with_gemini(text, current)
        logging.warning("No model API key configured; local parser could not parse message")
        return _empty_action()
    except requests.exceptions.HTTPError as exc:
        response = getattr(exc, "response", None)
        status_code = response.status_code if response is not None else None
        if status_code == 429:
            logging.warning("Model API rate limit hit; local parser could not parse message")
        else:
            logging.exception("Model API request failed")
        return _empty_action()
    except requests.exceptions.RequestException:
        logging.exception("Model API request failed")
        return _empty_action()
    except (KeyError, IndexError, json.JSONDecodeError, TypeError):
        logging.exception("Failed to parse model response")
        return _empty_action()
