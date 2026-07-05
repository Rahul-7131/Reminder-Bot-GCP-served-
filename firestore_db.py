"""
Firestore data access layer.

Collections used:
- "events": one doc per reminder-worthy date
    { name: str, event_type: str, month: int, day: int, year: int | None,
      notes: str, created_at: timestamp, updated_at: timestamp }
- "config": single doc "owner" storing your Telegram chat_id
    { chat_id: int }
"""

from __future__ import annotations

from datetime import datetime, timezone
from difflib import SequenceMatcher
import logging
import re
from typing import Any

from google.cloud import firestore

db = firestore.Client()

EVENT_TYPE_ALIASES = {
    "bday": "birthday",
    "bd": "birthday",
    "b'day": "birthday",
    "b-day": "birthday",
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


def normalize_name(name: str) -> str:
    """Normalize a reminder name for matching."""
    normalized = (name or "").strip().casefold()
    normalized = re.sub(r"['’]s\b", "", normalized)
    normalized = re.sub(r"\bdi\b", "didi", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def display_name(name: str) -> str:
    """Clean a user-provided name while preserving natural capitalization."""
    cleaned = re.sub(r"\s+", " ", (name or "").strip())
    return cleaned[:1].upper() + cleaned[1:] if cleaned else cleaned


def normalize_event_type(event_type: str) -> str:
    """Normalize common event-type aliases before matching or storing."""
    normalized = re.sub(r"\s+", " ", (event_type or "").strip()).casefold()
    return EVENT_TYPE_ALIASES.get(normalized, normalized or "other")


def normalize_year(year: Any) -> int | None:
    """Return a valid integer year or None for recurring annual reminders."""
    if year in (None, "", 0, "0"):
        return None
    try:
        parsed = int(year)
    except (TypeError, ValueError):
        return None
    return parsed if 1900 <= parsed <= 2100 else None


def event_key(event: dict[str, Any]) -> tuple[str, str, int, int, int | None]:
    """Build the canonical duplicate key for an event-like dict."""
    return (
        normalize_name(str(event.get("name", ""))),
        normalize_event_type(str(event.get("event_type", ""))),
        int(event.get("day", 0)),
        int(event.get("month", 0)),
        normalize_year(event.get("year")),
    )


def set_owner_chat_id(chat_id: int) -> None:
    """Store the Telegram chat_id of the person using this bot."""
    db.collection("config").document("owner").set({"chat_id": chat_id})


def get_owner_chat_id() -> int | None:
    """Return the configured owner chat_id, if any."""
    doc = db.collection("config").document("owner").get()
    if doc.exists:
        return doc.to_dict().get("chat_id")
    return None


def _event_from_doc(doc: Any) -> dict[str, Any]:
    data = doc.to_dict()
    data["id"] = doc.id
    data["event_type"] = normalize_event_type(data.get("event_type", "other"))
    data["year"] = normalize_year(data.get("year"))
    return data


def list_all_events() -> list[dict[str, Any]]:
    """Return all stored events with document ids, sorted by month and day."""
    docs = db.collection("events").stream()
    events = [_event_from_doc(doc) for doc in docs]
    events.sort(key=lambda e: (e.get("month", 0), e.get("day", 0), e.get("name", "")))
    return events


def find_duplicate_events(
    name: str,
    event_type: str,
    month: int,
    day: int,
    year: int | None = None,
) -> list[dict[str, Any]]:
    """Return reminders with the same normalized name, type, and date."""
    target = event_key(
        {
            "name": name,
            "event_type": event_type,
            "month": month,
            "day": day,
            "year": year,
        }
    )
    return [event for event in list_all_events() if event_key(event) == target]


def add_event(
    name: str,
    event_type: str,
    month: int,
    day: int,
    notes: str = "",
    year: int | None = None,
) -> str:
    """Add a reminder event and return the new document id."""
    now = datetime.now(timezone.utc)
    event = {
        "name": display_name(name),
        "event_type": normalize_event_type(event_type),
        "month": int(month),
        "day": int(day),
        "year": normalize_year(year),
        "notes": (notes or "").strip(),
        "created_at": now,
        "updated_at": now,
    }
    _, doc_ref = db.collection("events").add(event)
    return doc_ref.id


def get_events_for_month_day(month: int, day: int) -> list[dict[str, Any]]:
    """Return all events matching a given month/day."""
    query = (
        db.collection("events")
        .where("month", "==", month)
        .where("day", "==", day)
        .stream()
    )
    return [_event_from_doc(doc) for doc in query]


def update_event(doc_id: str, updates: dict[str, Any]) -> None:
    """Update a reminder document in place."""
    allowed = {"name", "event_type", "month", "day", "year", "notes"}
    payload: dict[str, Any] = {}
    for key, value in updates.items():
        if key not in allowed or value is None:
            continue
        if key == "name":
            payload[key] = display_name(str(value))
        elif key == "event_type":
            payload[key] = normalize_event_type(str(value))
        elif key in {"month", "day"}:
            payload[key] = int(value)
        elif key == "year":
            payload[key] = normalize_year(value)
        else:
            payload[key] = str(value).strip()
    if not payload:
        return
    payload["updated_at"] = datetime.now(timezone.utc)
    db.collection("events").document(doc_id).update(payload)


def delete_event(doc_id: str) -> None:
    """Delete a single event by its Firestore document id."""
    db.collection("events").document(doc_id).delete()


def delete_events(doc_ids: list[str]) -> None:
    """Delete several events by document id."""
    batch = db.batch()
    for doc_id in doc_ids:
        batch.delete(db.collection("events").document(doc_id))
    batch.commit()


def search_events(
    name: str | None = None,
    event_type: str | None = None,
    month: int | None = None,
    day: int | None = None,
    year: int | None = None,
) -> list[dict[str, Any]]:
    """Search reminders using normalized filters."""
    events = list_all_events()
    if name:
        query = normalize_name(name)
        events = [event for event in events if query in normalize_name(event.get("name", ""))]
    if event_type:
        normalized_type = normalize_event_type(event_type)
        events = [event for event in events if normalize_event_type(event.get("event_type", "")) == normalized_type]
    if month:
        events = [event for event in events if int(event.get("month", 0)) == int(month)]
    if day:
        events = [event for event in events if int(event.get("day", 0)) == int(day)]
    if year:
        normalized_year = normalize_year(year)
        events = [event for event in events if normalize_year(event.get("year")) == normalized_year]
    return events


def find_events_for_action(
    name: str | None = None,
    event_type: str | None = None,
    month: int | None = None,
    day: int | None = None,
    year: int | None = None,
    fuzzy: bool = True,
) -> list[dict[str, Any]]:
    """Find candidate reminders, using fuzzy name matching only if exact matching fails."""
    exact = search_events(name=name, event_type=event_type, month=month, day=day, year=year)
    if exact or not fuzzy or not name:
        return exact

    target = normalize_name(name)
    candidates = search_events(event_type=event_type, month=month, day=day, year=year)
    scored = []
    for event in candidates:
        score = SequenceMatcher(None, target, normalize_name(event.get("name", ""))).ratio()
        if score >= 0.72:
            scored.append((score, event))
    scored.sort(key=lambda item: item[0], reverse=True)
    if scored:
        logging.info("Using fuzzy name match for %r -> %r", name, scored[0][1].get("name"))
    return [event for _, event in scored]
