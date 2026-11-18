"""Constants of the Lumo integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "lumo"

CONF_HOST: Final = "host"
CONF_PORT: Final = "port"
CONF_PASSWORD: Final = "password"
CONF_SSL: Final = "ssl"
CONF_ACCOUNTS: Final = "accounts"

# Options. Both are off by default.
CONF_ENABLE_GRADES: Final = "enable_grades"
CONF_ALLOW_HOMEWORK_WRITE: Final = "allow_homework_write"

DEFAULT_PORT: Final = 8080

# Fired on the event bus for every new substitution entry, homework or (opt-in) grade.
EVENT_NEW_ITEM: Final = "lumo_new_item"
# Upper limit per update, so a freshly published plan cannot flood the bus.
MAX_EVENTS_PER_UPDATE: Final = 25

# Safety net when the event stream is down; the stream normally pushes changes.
FALLBACK_INTERVAL: Final = timedelta(minutes=15)
# Health of the services and app update: only for the diagnostic entities.
STATUS_INTERVAL: Final = timedelta(minutes=5)
# A sync of the course pages produces many `update` events in a row (like the web UI).
EVENT_DEBOUNCE: Final = 0.6
RECONNECT_DELAY: Final = 5.0

# Data keys of the coordinator -> endpoint below /api/accounts/<id>/
ENDPOINTS: Final = {
    "account": "account",
    "timetable": "timetable",
    "substitutions": "substitutions",
    "calendar": "calendar",
    "homework": "homework",
    "meals": "meals",
    "grades": "grades",
}
# Portal area (AccountInfo.features) needed for a data key; keys without an entry are
# always available (meals: depends on the Caseda setup and answers 404 meals_disabled).
FEATURE_OF: Final = {
    "timetable": "timetable",
    "substitutions": "substitutions",
    "calendar": "calendar",
    "homework": "lessons",
    "grades": "lessons",
}
