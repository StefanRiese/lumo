"""Sensors: substitutions, homework, lessons, school meals and (opt-in) grades."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from . import LumoConfigEntry
from .coordinator import LumoCoordinator
from .entity import LumoEntity, add_when_available
from .timetable import LessonInstance, first_lesson_on, next_lesson
from .util import day_entry, html_to_text

PARALLEL_UPDATES = 0

Data = dict[str, Any]


def _entries(data: Data, day: date) -> list[dict[str, Any]] | None:
    entry = day_entry(data["substitutions"].data, day)
    return None if entry is None else list(entry.get("entries", []))


def _count_entries(data: Data, now: datetime, offset: int) -> int:
    return len(_entries(data, now.date() + timedelta(days=offset)) or [])


def _substitution_attrs(data: Data, now: datetime, offset: int) -> dict[str, Any]:
    day = now.date() + timedelta(days=offset)
    entry = day_entry(data["substitutions"].data, day)
    return {
        "date": day.isoformat(),
        # False: the portal has not published this day (yet), 0 entries mean nothing then
        "published": entry is not None,
        "entries": [
            {k: v for k, v in e.items() if v not in (None, "")}
            for e in (entry or {}).get("entries", [])
        ],
        "notices": [
            {"title": n.get("title"), "lines": [html_to_text(x) for x in n.get("lines", [])]}
            for n in (entry or {}).get("notices", [])
        ],
    }


def _open_homework(data: Data) -> list[dict[str, Any]]:
    return [h for h in data["homework"].data or [] if not h.get("done")]


def _homework_attrs(data: Data, now: datetime) -> dict[str, Any]:
    return {
        "homework": [
            {
                "course": h.get("courseName"),
                "date": h.get("date"),
                "topic": h.get("topic"),
                "description": html_to_text(h.get("description")),
            }
            for h in _open_homework(data)
        ]
    }


def _lesson_attrs(lesson: LessonInstance | None) -> dict[str, Any]:
    if lesson is None:
        return {}
    return {
        "subject": lesson.subject,
        "room": lesson.room,
        "teacher": lesson.teacher,
        "end": lesson.end.isoformat(),
    }


def _next_lesson(data: Data, now: datetime) -> LessonInstance | None:
    return next_lesson(data["timetable"].data, now)


def _first_tomorrow(data: Data, now: datetime) -> LessonInstance | None:
    return first_lesson_on(data["timetable"].data, now.date() + timedelta(days=1), now)


def _todays_meal(data: Data, now: datetime) -> dict[str, Any] | None:
    today = now.date().isoformat()
    for order in data["meals"].data.get("orders", []):
        if order.get("date") == today and (order.get("ordered") or 0) > 0:
            return order
    return None


def _grade_courses(data: Data) -> list[dict[str, Any]]:
    return [c for c in data["grades"].data or [] if c.get("grades")]


@dataclass(frozen=True, kw_only=True)
class LumoSensorDescription(SensorEntityDescription):
    """`value_fn(data, now)`; `time_based` sensors are re-evaluated every minute."""

    data_key: str
    value_fn: Callable[[Data, datetime], Any]
    attrs_fn: Callable[[Data, datetime], dict[str, Any]] | None = None
    time_based: bool = False


SENSORS: tuple[LumoSensorDescription, ...] = (
    LumoSensorDescription(
        key="substitutions_today",
        data_key="substitutions",
        translation_key="substitutions_today",
        value_fn=lambda d, now: _count_entries(d, now, 0),
        attrs_fn=lambda d, now: _substitution_attrs(d, now, 0),
        time_based=True,
    ),
    LumoSensorDescription(
        key="substitutions_tomorrow",
        data_key="substitutions",
        translation_key="substitutions_tomorrow",
        value_fn=lambda d, now: _count_entries(d, now, 1),
        attrs_fn=lambda d, now: _substitution_attrs(d, now, 1),
        time_based=True,
    ),
    LumoSensorDescription(
        key="open_homework",
        data_key="homework",
        translation_key="open_homework",
        value_fn=lambda d, now: len(_open_homework(d)),
        attrs_fn=_homework_attrs,
    ),
    LumoSensorDescription(
        key="next_lesson",
        data_key="timetable",
        translation_key="next_lesson",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d, now: lesson.start if (lesson := _next_lesson(d, now)) else None,
        attrs_fn=lambda d, now: _lesson_attrs(_next_lesson(d, now)),
        time_based=True,
    ),
    LumoSensorDescription(
        key="first_lesson_tomorrow",
        data_key="timetable",
        translation_key="first_lesson_tomorrow",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d, now: lesson.start if (lesson := _first_tomorrow(d, now)) else None,
        attrs_fn=lambda d, now: _lesson_attrs(_first_tomorrow(d, now)),
        time_based=True,
    ),
    LumoSensorDescription(
        key="meal_balance",
        data_key="meals",
        translation_key="meal_balance",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="EUR",
        suggested_display_precision=2,
        value_fn=lambda d, now: (
            None
            if d["meals"].data.get("balanceCents") is None
            else d["meals"].data["balanceCents"] / 100
        ),
    ),
    LumoSensorDescription(
        key="meal_today",
        data_key="meals",
        translation_key="meal_today",
        value_fn=lambda d, now: meal.get("name") if (meal := _todays_meal(d, now)) else None,
        attrs_fn=lambda d, now: (
            {
                "line": meal.get("line"),
                "allergens": meal.get("allergens"),
                "price": None if meal.get("priceCents") is None else meal["priceCents"] / 100,
            }
            if (meal := _todays_meal(d, now))
            else {}
        ),
        time_based=True,
    ),
    LumoSensorDescription(
        key="grades_count",
        data_key="grades",
        translation_key="grades_count",
        value_fn=lambda d, now: sum(len(c["grades"]) for c in _grade_courses(d)),
        attrs_fn=lambda d, now: {
            "courses": [
                {
                    "course": (c.get("course") or {}).get("name"),
                    "grades": [
                        {"name": g.get("name"), "date": g.get("date"), "mark": g.get("mark")}
                        for g in c["grades"]
                    ],
                }
                for c in _grade_courses(d)
            ]
        },
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: LumoConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    for coordinator in entry.runtime_data.coordinators.values():
        add_when_available(
            entry,
            async_add_entities,
            coordinator,
            lambda c: [
                LumoSensor(c, entry, description)
                for description in SENSORS
                if c.data and c.data.get(description.data_key) is not None
            ],
        )


class LumoSensor(LumoEntity, SensorEntity):
    entity_description: LumoSensorDescription

    def __init__(
        self, coordinator: LumoCoordinator, entry: ConfigEntry, description: LumoSensorDescription
    ) -> None:
        super().__init__(coordinator, entry, description.key, description.data_key)
        self.entity_description = description

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self.entity_description.time_based:
            # "today", "next lesson", … change with the clock, not only with new data
            @callback
            def _tick(_now: datetime) -> None:
                self.async_write_ha_state()

            self.async_on_remove(async_track_time_interval(self.hass, _tick, timedelta(minutes=1)))

    @property
    def native_value(self) -> Any:
        if self.envelope is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data, dt_util.now())

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.envelope is None:
            return None
        attrs = self.freshness()
        if self.entity_description.attrs_fn is not None:
            attrs |= self.entity_description.attrs_fn(self.coordinator.data, dt_util.now())
        return attrs
