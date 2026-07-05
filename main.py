"""
Flask app for the Telegram reminder bot.

Endpoints:
- POST /webhook: receives Telegram messages, parses them with Gemini, and
  creates, updates, deletes, searches, or lists reminders in Firestore.
- POST /check-reminders: called by Cloud Scheduler to send tomorrow reminders.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
import logging
import os
from typing import Any
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, request
import requests

from gemini_parser import parse_message
from firestore_db import (
    add_event,
    delete_event,
    delete_events,
    event_key,
    find_duplicate_events,
    find_events_for_action,
    get_events_for_month_day,
    get_owner_chat_id,
    list_all_events,
    normalize_event_type,
    normalize_year,
    search_events,
    set_owner_chat_id,
    update_event,
)

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
SCHEDULER_SECRET = os.environ.get("SCHEDULER_SECRET", "")
LOCAL_TZ = ZoneInfo(os.environ.get("BOT_TIMEZONE", "Asia/Kolkata"))

MONTH_NAMES = [
    "",
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]

CANCEL_WORDS = {"cancel", "never mind", "nevermind", "stop"}
HELP_QUERIES = {
    "what all can you do",
    "what can you do",
    "what do you do",
    "help",
    "show help",
    "commands",
}
PENDING_DELETE_OPTIONS: dict[int, list[dict[str, Any]]] = defaultdict(list)

HELP_TEXT = (
    "Here's what I can do:\n\n"
    "• Add: Rahul bday 2 July, Doctor appointment tomorrow\n"
    "• Edit: Rahul birthday is actually on 3 July, Rename Rahul to Rahul Kumar\n"
    "• Delete: Delete Rahul birthday, Delete Rahul 2 July\n"
    "• Search: Show Rahul reminders, Show birthdays, Show July reminders\n"
    "• Upcoming: What's next?, Upcoming this week, Next 30 days\n"
    "• /list shows everything, /help shows this message."
)


def send_telegram_message(chat_id: int, text: str) -> None:
    """Send a Telegram message and log failures."""
    try:
        response = requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=15,
        )
        response.raise_for_status()
    except requests.exceptions.RequestException:
        logging.exception("Failed to send Telegram message")


def month_name(month: int | None) -> str:
    """Return a display month name."""
    if month and 1 <= int(month) <= 12:
        return MONTH_NAMES[int(month)]
    return str(month or "")


def format_date(event: dict[str, Any]) -> str:
    """Format a reminder date for users."""
    day = event.get("day")
    month = event.get("month")
    year = normalize_year(event.get("year"))
    if not day or not month:
        return "Date not set"
    text = f"{int(day)} {month_name(int(month))}"
    return f"{text} {year}" if year else text


def event_title(event: dict[str, Any]) -> str:
    """Format a short reminder label."""
    event_type = normalize_event_type(event.get("event_type", "other")).title()
    return f"{event.get('name', 'Someone')} - {event_type} - {format_date(event)}"


def render_event_lines(events: list[dict[str, Any]]) -> str:
    """Render reminders as a concise list."""
    lines = []
    for event in events:
        line = f"• {event_title(event)}"
        if event.get("notes"):
            line += f"\n  Notes: {event['notes']}"
        lines.append(line)
    return "\n".join(lines)


def is_valid_event_date(month: Any, day: Any, year: Any = None) -> bool:
    """Validate month/day, using a leap year when the event is annual."""
    try:
        parsed_month = int(month)
        parsed_day = int(day)
        parsed_year = normalize_year(year) or 2024
        date(parsed_year, parsed_month, parsed_day)
        return True
    except (TypeError, ValueError):
        return False


def required_event_fields(event: dict[str, Any]) -> bool:
    """Check whether an add event has the required fields."""
    return bool(event.get("name") and event.get("event_type") and event.get("month") and event.get("day"))


def handle_list() -> str:
    """Return all saved reminders."""
    events = list_all_events()
    if not events:
        return "You don't have any reminders saved yet. Try: Rahul birthday 2 July"
    return "Here are all saved reminders:\n\n" + render_event_lines(events)


def handle_add(events: list[dict[str, Any]]) -> str:
    """Add reminders, skipping normalized duplicates."""
    if not events:
        return "I didn't catch a reminder/date in that message. Try: Rahul birthday 2 July"

    replies = []
    for event in events:
        if not required_event_fields(event):
            replies.append("I need a name, event type, and date to save a reminder.")
            continue
        if not is_valid_event_date(event.get("month"), event.get("day"), event.get("year")):
            replies.append(f"I couldn't save {event.get('name', 'that reminder')} because the date looks invalid.")
            continue

        normalized_type = normalize_event_type(event["event_type"])
        year = normalize_year(event.get("year"))
        duplicates = find_duplicate_events(
            name=event["name"],
            event_type=normalized_type,
            month=int(event["month"]),
            day=int(event["day"]),
            year=year,
        )
        if duplicates:
            existing = duplicates[0]
            replies.append(
                f"A reminder for {existing['name']}'s {normalize_event_type(existing['event_type'])} "
                f"on {format_date(existing)} already exists."
            )
            continue

        add_event(
            name=event["name"],
            event_type=normalized_type,
            month=int(event["month"]),
            day=int(event["day"]),
            year=year,
            notes=event.get("notes", ""),
        )
        saved = {
            "name": event["name"],
            "event_type": normalized_type,
            "month": int(event["month"]),
            "day": int(event["day"]),
            "year": year,
            "notes": event.get("notes", ""),
        }
        replies.append(
            "✅ Reminder Added\n\n"
            f"Name:\n{saved['name']}\n\n"
            f"Event:\n{normalized_type.title()}\n\n"
            f"Date:\n{format_date(saved)}\n\n"
            "I'll remind you on the day."
        )
    return "\n\n".join(replies)


def _query_from_delete_text(name_query: str) -> dict[str, Any]:
    return {"name": name_query} if name_query else {}


def is_help_query(text: str) -> bool:
    """Return True for common natural-language help requests."""
    normalized = text.strip().casefold().rstrip("?.!")
    return normalized in HELP_QUERIES


def handle_delete(query: dict[str, Any], chat_id: int | None = None) -> str:
    """Delete one match, all identical duplicates, or ask for clarification."""
    if not query:
        return "Tell me what to delete, e.g. Delete Rahul birthday."

    matches = find_events_for_action(
        name=query.get("name"),
        event_type=query.get("event_type"),
        month=query.get("month"),
        day=query.get("day"),
        year=query.get("year"),
    )
    if not matches:
        return "I couldn't find a matching reminder. Try /list to see what's saved."

    if len(matches) == 1:
        event = matches[0]
        delete_event(event["id"])
        return "🗑️ Reminder Deleted\n\n" + render_event_lines([event])

    grouped = defaultdict(list)
    for event in matches:
        grouped[event_key(event)].append(event)

    if len(grouped) == 1:
        delete_events([event["id"] for event in matches])
        return f"I found {len(matches)} identical reminders and removed them."

    if chat_id is not None:
        PENDING_DELETE_OPTIONS[chat_id] = matches
    lines = ["I found multiple different reminders. Which one should I delete? Reply with a number, or say cancel.\n"]
    for index, event in enumerate(matches, start=1):
        lines.append(f"{index}. {event_title(event)}")
    lines.append("\nI won't delete anything until you choose.")
    return "\n".join(lines)


def handle_pending_delete(chat_id: int, text: str) -> str | None:
    """Resolve a pending delete clarification."""
    if chat_id not in PENDING_DELETE_OPTIONS:
        return None
    normalized = text.strip().casefold()
    if normalized in CANCEL_WORDS:
        PENDING_DELETE_OPTIONS.pop(chat_id, None)
        return "Okay, cancelled. I didn't delete anything."
    try:
        choice = int(normalized)
    except ValueError:
        return "Please reply with one of the listed numbers, or say cancel."

    options = PENDING_DELETE_OPTIONS[chat_id]
    if choice < 1 or choice > len(options):
        return "That number isn't in the list. Please choose one of the shown options, or say cancel."

    event = options[choice - 1]
    identical = [candidate for candidate in options if event_key(candidate) == event_key(event)]
    delete_events([candidate["id"] for candidate in identical])
    PENDING_DELETE_OPTIONS.pop(chat_id, None)
    if len(identical) > 1:
        return f"I found {len(identical)} identical reminders and removed them."
    return "🗑️ Reminder Deleted\n\n" + render_event_lines([event])


def handle_update(query: dict[str, Any], updates: dict[str, Any]) -> str:
    """Update matching reminders in place."""
    if not query or not updates:
        return "Tell me which reminder to update and what to change, e.g. Rahul birthday is actually on 3 July."
    if ("month" in updates or "day" in updates) and not is_valid_event_date(
        updates.get("month") or query.get("month"),
        updates.get("day") or query.get("day"),
        updates.get("year") or query.get("year"),
    ):
        return "That new date doesn't look valid. Please try again with a real date."

    matches = find_events_for_action(
        name=query.get("name"),
        event_type=query.get("event_type"),
        month=query.get("month"),
        day=query.get("day"),
        year=query.get("year"),
    )
    if not matches:
        return "I couldn't find that reminder to update."

    grouped = defaultdict(list)
    for event in matches:
        grouped[event_key(event)].append(event)
    if len(matches) > 1 and len(grouped) > 1:
        return "I found more than one possible reminder. Please be more specific, like: Change Rahul birthday to 3 July."

    for event in matches:
        update_event(event["id"], updates)
    updated_events = []
    for event in matches:
        changed = dict(event)
        changed.update({k: v for k, v in updates.items() if v is not None})
        if "event_type" in changed:
            changed["event_type"] = normalize_event_type(changed["event_type"])
        updated_events.append(changed)

    heading = "✅ Reminder Updated" if len(matches) == 1 else f"✅ Updated {len(matches)} identical reminders"
    return f"{heading}\n\n" + render_event_lines(updated_events)


def handle_search(query: dict[str, Any]) -> str:
    """Search reminders by natural-language filters."""
    events = search_events(
        name=query.get("name"),
        event_type=query.get("event_type"),
        month=query.get("month"),
        day=query.get("day"),
        year=query.get("year"),
    )
    if not events:
        return "I couldn't find matching reminders."
    return f"Found {len(events)} reminder{'s' if len(events) != 1 else ''}:\n\n" + render_event_lines(events)


def next_occurrence(event: dict[str, Any], today: date) -> date | None:
    """Calculate the next occurrence date for annual or one-time reminders."""
    month = int(event.get("month", 0))
    day = int(event.get("day", 0))
    year = normalize_year(event.get("year"))
    try:
        if year:
            occurrence = date(year, month, day)
            return occurrence if occurrence >= today else None
        occurrence = date(today.year, month, day)
        if occurrence < today:
            occurrence = date(today.year + 1, month, day)
        return occurrence
    except ValueError:
        logging.warning("Skipping invalid stored reminder date: %s", event)
        return None


def handle_upcoming(reminder_range: str) -> str:
    """Return upcoming reminders sorted by occurrence date."""
    today = datetime.now(LOCAL_TZ).date()
    candidates = []
    for event in list_all_events():
        occurrence = next_occurrence(event, today)
        if not occurrence:
            continue
        days_remaining = (occurrence - today).days
        if reminder_range == "next" and days_remaining > 365:
            continue
        if reminder_range == "week" and days_remaining > 7:
            continue
        if reminder_range == "month" and not (occurrence.year == today.year and occurrence.month == today.month):
            continue
        if reminder_range == "30_days" and days_remaining > 30:
            continue
        candidates.append((occurrence, days_remaining, event))

    candidates.sort(key=lambda item: item[0])
    if reminder_range == "next":
        candidates = candidates[:1]
    if not candidates:
        return "No upcoming reminders found for that range."

    lines = ["Upcoming reminders:\n"]
    for occurrence, days_remaining, event in candidates:
        suffix = "today" if days_remaining == 0 else f"in {days_remaining} day{'s' if days_remaining != 1 else ''}"
        lines.append(f"• {event_title(event)} ({suffix})")
    return "\n".join(lines)


def handle_parsed_action(parsed: dict[str, Any], chat_id: int | None = None) -> str:
    """Dispatch a Gemini action envelope to a bot handler."""
    action = parsed.get("action", "unknown")
    if action == "add":
        return handle_add(parsed.get("events", []))
    if action == "delete":
        return handle_delete(parsed.get("query", {}), chat_id)
    if action == "update":
        return handle_update(parsed.get("query", {}), parsed.get("updates", {}))
    if action == "search":
        return handle_search(parsed.get("query", {}))
    if action == "upcoming":
        return handle_upcoming(parsed.get("range", "all"))
    return "I didn't catch what you wanted me to do. Try: Rahul birthday 2 July, Show July reminders, or What's next?"


@app.route("/webhook", methods=["POST"])
def webhook():
    """Handle Telegram webhook updates."""
    update = request.get_json(silent=True) or {}
    message = update.get("message")
    if not message or "text" not in message:
        return jsonify(ok=True)

    chat_id = message["chat"]["id"]
    text = message["text"].strip()

    try:
        if get_owner_chat_id() is None:
            set_owner_chat_id(chat_id)
    except Exception:
        logging.exception("Failed to set owner chat_id")

    try:
        pending_reply = handle_pending_delete(chat_id, text)
        if pending_reply is not None:
            reply = pending_reply
        elif text.casefold() in CANCEL_WORDS:
            reply = "Nothing to cancel."
        elif text in ("/start", "/help") or is_help_query(text):
            reply = HELP_TEXT
        elif text == "/list":
            reply = handle_list()
        elif text.startswith("/delete"):
            reply = handle_delete(_query_from_delete_text(text[len("/delete") :].strip()), chat_id)
        else:
            parsed = parse_message(text, datetime.now(LOCAL_TZ))
            reply = handle_parsed_action(parsed, chat_id)
    except Exception:
        logging.exception("Error handling message: %r", text)
        reply = "Something went wrong on my end. Please try again in a moment."

    send_telegram_message(chat_id, reply)
    return jsonify(ok=True)


@app.route("/check-reminders", methods=["POST"])
def check_reminders():
    """Send reminders for events happening today."""
    if SCHEDULER_SECRET and request.headers.get("X-Scheduler-Secret") != SCHEDULER_SECRET:
        return jsonify(error="unauthorized"), 401

    try:
        owner_chat_id = get_owner_chat_id()
        if not owner_chat_id:
            return jsonify(ok=True, message="No owner chat_id set yet. Message the bot once first.")

        today = datetime.now(LOCAL_TZ)
        events = [
            event
            for event in get_events_for_month_day(today.month, today.day)
            if normalize_year(event.get("year")) in (None, today.year)
        ]

        for event in events:
            text = f"Reminder: today is {event['name']}'s {normalize_event_type(event['event_type'])}!"
            if event.get("notes"):
                text += f" ({event['notes']})"
            send_telegram_message(owner_chat_id, text)

        return jsonify(ok=True, reminders_sent=len(events))
    except Exception:
        logging.exception("Error in check_reminders")
        return jsonify(ok=False, error="internal error, check logs"), 500


@app.route("/", methods=["GET"])
def health_check():
    """Basic health check endpoint."""
    return jsonify(status="ok")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
