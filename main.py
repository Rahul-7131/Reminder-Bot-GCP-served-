"""
Flask app with two endpoints:

1. POST /webhook
   Telegram calls this whenever you send the bot a message.
   It parses your message with Claude, stores structured events in Firestore,
   and replies with a confirmation.

2. POST /check-reminders
   Called once a day by Cloud Scheduler. Checks Firestore for any events
   happening TOMORROW and sends you a Telegram message if there are matches.
"""

import os
import requests
from datetime import datetime, timedelta, timezone
from flask import Flask, request, jsonify

from gemini_parser import parse_message
from firestore_db import add_event, get_events_for_month_day, set_owner_chat_id, get_owner_chat_id

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# Shared secret used to verify Cloud Scheduler's request (simple auth)
SCHEDULER_SECRET = os.environ.get("SCHEDULER_SECRET", "")


def send_telegram_message(chat_id: int, text: str):
    requests.post(f"{TELEGRAM_API}/sendMessage", json={"chat_id": chat_id, "text": text})


@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json(silent=True) or {}
    message = update.get("message")
    if not message or "text" not in message:
        return jsonify(ok=True)

    chat_id = message["chat"]["id"]
    text = message["text"]

    # Remember this chat_id as "the owner" so /check-reminders knows where to send reminders.
    # (Fine for a single-user personal bot; first person to message it becomes the owner.)
    if get_owner_chat_id() is None:
        set_owner_chat_id(chat_id)

    parsed = parse_message(text)

    if parsed.get("is_event"):
        add_event(
            name=parsed["name"],
            event_type=parsed["event_type"],
            month=parsed["month"],
            day=parsed["day"],
            notes=parsed.get("notes", ""),
        )
        reply = f"Got it — I'll remind you about {parsed['name']}'s {parsed['event_type']} " \
                f"(month {parsed['month']}, day {parsed['day']}) the day before, every year."
    else:
        reply = "I didn't catch an event/date in that message. Try something like: " \
                "\"Aman's birthday is on 1st September\"."

    send_telegram_message(chat_id, reply)
    return jsonify(ok=True)


@app.route("/check-reminders", methods=["POST"])
def check_reminders():
    # Basic auth so random internet traffic can't trigger this
    if SCHEDULER_SECRET and request.headers.get("X-Scheduler-Secret") != SCHEDULER_SECRET:
        return jsonify(error="unauthorized"), 401

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


@app.route("/", methods=["GET"])
def health_check():
    return jsonify(status="ok")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
