"""
Flask app with two endpoints:

1. POST /webhook
   Telegram calls this whenever you send the bot a message.
   Supports:
     - Free text describing one or more events -> parsed with Gemini, saved to Firestore
     - /list   -> shows all saved events
     - /delete <name> -> deletes matching event(s) by name
     - /start, /help -> shows usage instructions

2. POST /check-reminders
   Called once a day by Cloud Scheduler. Checks Firestore for any events
   happening TOMORROW and sends you a Telegram message if there are matches.
"""

import os
import logging
import requests
from datetime import datetime, timedelta, timezone
from flask import Flask, request, jsonify

from gemini_parser import parse_message
from firestore_db import (
    add_event,
    get_events_for_month_day,
    set_owner_chat_id,
    get_owner_chat_id,
    list_all_events,
    find_events_by_name,
    delete_event,
)

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# Shared secret used to verify Cloud Scheduler's request (simple auth)
SCHEDULER_SECRET = os.environ.get("SCHEDULER_SECRET", "")

MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

HELP_TEXT = (
    "Here's what I can do:\n\n"
    "• Just tell me about a date, e.g. \"Aman's birthday is on 1st September\" "
    "— I'll remember it and remind you the day before, every year.\n"
    "• /list — show everything I'm currently tracking.\n"
    "• /delete <name> — remove an event (e.g. /delete Aman).\n"
    "• /help — show this message again."
)


def send_telegram_message(chat_id: int, text: str):
    try:
        requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=15,
        )
    except requests.exceptions.RequestException:
        # If Telegram itself is unreachable there's nothing more we can do here;
        # just log it so it shows up in Cloud Run logs instead of crashing.
        logging.exception("Failed to send Telegram message")


def handle_list() -> str:
    events = list_all_events()
    if not events:
        return "You don't have any events saved yet. Try: \"Aman's birthday is on 1st September\"."

    lines = ["Here's everything I'm tracking:"]
    for e in events:
        month_name = MONTH_NAMES[e["month"]] if 1 <= e["month"] <= 12 else str(e["month"])
        line = f"• {e['name']} — {e['event_type']} ({month_name} {e['day']})"
        if e.get("notes"):
            line += f" [{e['notes']}]"
        lines.append(line)
    return "\n".join(lines)


def handle_delete(name_query: str) -> str:
    if not name_query:
        return "Tell me who to delete, e.g. /delete Aman"

    matches = find_events_by_name(name_query)
    if not matches:
        return f"I couldn't find anyone matching \"{name_query}\". Try /list to see everyone saved."

    if len(matches) > 1:
        lines = [f"Found {len(matches)} matches for \"{name_query}\" — be more specific:"]
        for e in matches:
            month_name = MONTH_NAMES[e["month"]] if 1 <= e["month"] <= 12 else str(e["month"])
            lines.append(f"• {e['name']} — {e['event_type']} ({month_name} {e['day']})")
        return "\n".join(lines)

    event = matches[0]
    delete_event(event["id"])
    return f"Deleted {event['name']}'s {event['event_type']}."


def handle_new_event(text: str) -> str:
    events = parse_message(text)
    if not events:
        return "I didn't catch an event/date in that message. Try something like: " \
               "\"Aman's birthday is on 1st September\". Or send /help for all commands."

    confirmations = []
    for event in events:
        add_event(
            name=event["name"],
            event_type=event["event_type"],
            month=event["month"],
            day=event["day"],
            notes=event.get("notes", ""),
        )
        confirmations.append(
            f"{event['name']}'s {event['event_type']} (month {event['month']}, day {event['day']})"
        )
    return "Got it — I'll remind you about: " + "; ".join(confirmations) + ", the day before, every year."


@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json(silent=True) or {}
    message = update.get("message")
    if not message or "text" not in message:
        return jsonify(ok=True)

    chat_id = message["chat"]["id"]
    text = message["text"].strip()

    # Remember this chat_id as "the owner" so /check-reminders knows where to send reminders.
    # (Fine for a single-user personal bot; first person to message it becomes the owner.)
    try:
        if get_owner_chat_id() is None:
            set_owner_chat_id(chat_id)
    except Exception:
        logging.exception("Failed to set owner chat_id")

    # Each command handler is wrapped individually so a bug in one command
    # (e.g. /list) can never take down the whole bot or leave you without a reply.
    try:
        if text in ("/start", "/help"):
            reply = HELP_TEXT
        elif text == "/list":
            reply = handle_list()
        elif text.startswith("/delete"):
            name_query = text[len("/delete"):].strip()
            reply = handle_delete(name_query)
        else:
            reply = handle_new_event(text)
    except Exception:
        logging.exception(f"Error handling message: {text!r}")
        reply = "Something went wrong on my end processing that — mind trying again?"

    send_telegram_message(chat_id, reply)
    return jsonify(ok=True)


@app.route("/check-reminders", methods=["POST"])
def check_reminders():
    # Basic auth so random internet traffic can't trigger this
    if SCHEDULER_SECRET and request.headers.get("X-Scheduler-Secret") != SCHEDULER_SECRET:
        return jsonify(error="unauthorized"), 401

    try:
        owner_chat_id = get_owner_chat_id()
        if not owner_chat_id:
            return jsonify(ok=True, message="No owner chat_id set yet — message the bot once first.")

        tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
        events = get_events_for_month_day(tomorrow.month, tomorrow.day)

        for event in events:
            text = f"Reminder: tomorrow is {event['name']}'s {event['event_type']}!"
            if event.get("notes"):
                text += f" ({event['notes']})"
            send_telegram_message(owner_chat_id, text)

        return jsonify(ok=True, reminders_sent=len(events))
    except Exception:
        logging.exception("Error in check_reminders")
        return jsonify(ok=False, error="internal error, check logs"), 500


@app.route("/", methods=["GET"])
def health_check():
    return jsonify(status="ok")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
