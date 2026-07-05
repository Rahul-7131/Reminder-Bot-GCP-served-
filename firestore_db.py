"""
Firestore data access layer.

Collections used:
- "events": one doc per reminder-worthy date
    { name: str, event_type: str, month: int, day: int, notes: str, created_at: timestamp }
- "config": single doc "owner" storing your Telegram chat_id
    { chat_id: int }
"""

from google.cloud import firestore
from datetime import datetime, timezone

db = firestore.Client()


def set_owner_chat_id(chat_id: int):
    """Store the Telegram chat_id of the person using this bot (called on first message)."""
    db.collection("config").document("owner").set({"chat_id": chat_id})


def get_owner_chat_id():
    doc = db.collection("config").document("owner").get()
    if doc.exists:
        return doc.to_dict().get("chat_id")
    return None


def add_event(name: str, event_type: str, month: int, day: int, notes: str = ""):
    """Add a new reminder event (e.g. a birthday or anniversary). Returns the new doc's id."""
    event = {
        "name": name,
        "event_type": event_type,
        "month": month,
        "day": day,
        "notes": notes,
        "created_at": datetime.now(timezone.utc),
    }
    _, doc_ref = db.collection("events").add(event)
    return doc_ref.id


def get_events_for_month_day(month: int, day: int):
    """Return all events matching a given month/day (e.g. tomorrow's date)."""
    query = (
        db.collection("events")
        .where("month", "==", month)
        .where("day", "==", day)
        .stream()
    )
    return [doc.to_dict() for doc in query]


def list_all_events():
    """Return all stored events (with their doc id), sorted by month then day."""
    docs = db.collection("events").stream()
    events = []
    for doc in docs:
        data = doc.to_dict()
        data["id"] = doc.id
        events.append(data)
    events.sort(key=lambda e: (e["month"], e["day"]))
    return events


def find_events_by_name(name_query: str):
    """
    Case-insensitive substring search by name (e.g. "aman" matches "Aman").
    Firestore doesn't support this natively at scale, but for a personal
    reminder list (dozens of entries, not millions) fetching all and
    filtering in Python is simple and fast enough.
    """
    name_query = name_query.strip().lower()
    return [e for e in list_all_events() if name_query in e["name"].lower()]


def delete_event(doc_id: str):
    """Delete a single event by its Firestore document id."""
    db.collection("events").document(doc_id).delete()
