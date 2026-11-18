"""School calendar of a child."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import LumoConfigEntry
from .api import LumoError
from .coordinator import LumoCoordinator
from .entity import LumoEntity, add_when_available
from .util import html_to_text

PARALLEL_UPDATES = 0

# The server answers ranges up to 400 days and keeps today … +60 days fresh.
MAX_RANGE = timedelta(days=399)
SYNCED_DAYS = 59


def to_event(entry: dict[str, Any]) -> CalendarEvent | None:
    """A CalendarEntry of the API as calendar event (`start`/`end` are local time)."""
    try:
        start = datetime.fromisoformat(entry["start"])
        end = datetime.fromisoformat(entry.get("end") or entry["start"])
    except (KeyError, ValueError):
        return None
    start_value: date | datetime
    end_value: date | datetime
    if entry.get("allDay"):
        start_value, end_value = start.date(), end.date()
        if end_value <= start_value:  # the end of an all-day event is exclusive
            end_value = start_value + timedelta(days=1)
    else:
        start_value = start.replace(tzinfo=dt_util.get_default_time_zone())
        end_value = end.replace(tzinfo=dt_util.get_default_time_zone())
        if end_value < start_value:
            end_value = start_value
    return CalendarEvent(
        start=start_value,
        end=end_value,
        summary=html_to_text(entry.get("title")) or "–",
        description=html_to_text(entry.get("description")) or None,
        location=entry.get("place") or None,
        uid=str(entry["id"]) if entry.get("id") is not None else None,
    )


async def async_setup_entry(
    hass: HomeAssistant, entry: LumoConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    for coordinator in entry.runtime_data.coordinators.values():
        add_when_available(
            entry,
            async_add_entities,
            coordinator,
            lambda c: (
                [LumoCalendar(c, entry)] if c.data and c.data.get("calendar") is not None else []
            ),
        )


class LumoCalendar(LumoEntity, CalendarEntity):
    """The school calendar; the next or current event is the entity state."""

    def __init__(self, coordinator: LumoCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "calendar", "calendar")

    @property
    def event(self) -> CalendarEvent | None:
        now = dt_util.now()
        upcoming: list[CalendarEvent] = []
        for raw in self.payload or []:
            event = to_event(raw)
            if event is None:
                continue
            end = (
                event.end
                if isinstance(event.end, datetime)
                else dt_util.start_of_local_day(event.end)
            )
            if end > now:
                upcoming.append(event)
        upcoming.sort(key=lambda e: dt_util.as_local(e.start_datetime_local))
        return upcoming[0] if upcoming else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        first = dt_util.as_local(start_date).date()
        last = min(dt_util.as_local(end_date).date(), first + MAX_RANGE)
        today = dt_util.now().date()
        if first >= today and last <= today + timedelta(days=SYNCED_DAYS):
            raw: list[dict[str, Any]] = list(self.payload or [])  # the synced range
        else:
            try:
                envelope = await self.coordinator.client.get(
                    self.coordinator.account_id,
                    "calendar",
                    params={"from": first.isoformat(), "to": last.isoformat()},
                )
            except LumoError as err:
                raise HomeAssistantError(f"Lumo calendar not available: {err}") from err
            raw = list(envelope.data or [])
        events = [e for item in raw if (e := to_event(item)) is not None]
        begin, finish = dt_util.as_local(start_date), dt_util.as_local(end_date)
        return [
            e for e in events if e.start_datetime_local < finish and e.end_datetime_local > begin
        ]

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return self.freshness() or None
