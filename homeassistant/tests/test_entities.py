"""Tests of the entities of a set-up entry (sensors, binary sensors, calendar, diagnostics)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta
from urllib.parse import urlparse

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.lumo.const import (
    CONF_ACCOUNTS,
    CONF_ALLOW_HOMEWORK_WRITE,
    CONF_ENABLE_GRADES,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SSL,
    DOMAIN,
)

from .fake_server import PASSWORD, FakeLumo


def _iso(day_offset: int) -> str:
    return (dt_util.now().date() + timedelta(days=day_offset)).isoformat()


@pytest.fixture
def populated(fake: tuple[FakeLumo, str]) -> FakeLumo:
    server, _ = fake
    today = dt_util.now()
    server.data["substitutions"] = [
        {
            "date": _iso(0),
            "entries": [
                {"period": "1", "type": "Vertretung", "subject": "D", "className": "08b"},
                {"period": "3 - 4", "type": "Entfall", "subject": "M", "className": "08b"},
            ],
            "notices": [{"title": "Hinweise", "lines": ["Wandertag<br>am Freitag"]}],
        },
        {"date": _iso(1), "entries": [{"period": "2", "type": "Vertretung"}], "notices": []},
    ]
    server.data["homework"] = [
        {
            "courseId": "104",
            "courseName": "Mathematik 08b",
            "entryId": "1",
            "date": _iso(-1),
            "topic": "Brüche",
            "description": "S. 45<br>Nr. 3",
            "done": False,
        },
        {
            "courseId": "105",
            "courseName": "Deutsch 08b",
            "entryId": "2",
            "date": _iso(-2),
            "topic": "Gedicht",
            "description": None,
            "done": True,
        },
    ]
    # a lesson starting in the future today or tomorrow, whatever time the test runs
    weekday = (today + timedelta(days=1)).isoweekday()
    server.data["timetable"] = {
        "currentWeek": None,
        "slots": [],
        "lessons": [
            {
                "weekday": weekday,
                "period": 1,
                "duration": 1,
                "start": "07:50",
                "end": "08:35",
                "subject": "M",
                "room": "A104",
                "teacher": "Becker",
                "week": None,
            },
        ],
    }
    server.data["calendar"] = [
        {
            "id": "7",
            "title": "Elternsprechtag",
            "description": "x",
            "allDay": False,
            "start": f"{_iso(3)}T16:00:00.000",
            "end": f"{_iso(3)}T19:00:00.000",
            "place": "Aula",
            "category": "Termine",
        },
    ]
    server.data["grades"] = [
        {
            "course": {"id": "104", "name": "Mathematik 08b", "teachers": []},
            "grades": [
                {"name": "1. Klassenarbeit", "date": "12.09.2026", "mark": "2", "comment": None}
            ],
            "exams": [],
        },
        {"course": {"id": "105", "name": "Deutsch 08b", "teachers": []}, "grades": [], "exams": []},
    ]
    server.data["meals"] = {
        "balanceCents": 845,
        "orders": [
            {
                "date": _iso(0),
                "line": "Menü 1",
                "name": "Gemüsemaultaschen",
                "allergens": ["a"],
                "priceCents": 390,
                "ordered": 1,
                "deadlinePassed": True,
            },
            {
                "date": _iso(1),
                "line": "Menü 2",
                "name": "Pizza",
                "allergens": [],
                "priceCents": 350,
                "ordered": 0,
                "deadlinePassed": False,
            },
        ],
    }
    return server


@pytest.fixture
async def setup(hass: HomeAssistant, fake: tuple[FakeLumo, str]) -> AsyncIterator[callable]:
    _, url = fake
    entries: list[MockConfigEntry] = []

    async def factory(**options) -> MockConfigEntry:
        parsed = urlparse(url)
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={
                CONF_HOST: parsed.hostname,
                CONF_PORT: parsed.port,
                CONF_SSL: False,
                CONF_PASSWORD: PASSWORD,
            },
            options={
                CONF_ACCOUNTS: ["k3x9ab"],
                CONF_ENABLE_GRADES: False,
                CONF_ALLOW_HOMEWORK_WRITE: False,
                **options,
            },
            unique_id="fake",
        )
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED
        entries.append(entry)
        return entry

    yield factory
    for entry in entries:
        await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


def _state(hass: HomeAssistant, entry: MockConfigEntry, platform: str, key: str, account="k3x9ab"):
    registry = er.async_get(hass)
    unique_id = f"{entry.entry_id}_{account}_{key}"
    entity_id = registry.async_get_entity_id(platform, DOMAIN, unique_id)
    return None if entity_id is None else hass.states.get(entity_id)


async def test_substitution_sensors(hass: HomeAssistant, populated: FakeLumo, setup) -> None:
    entry = await setup()
    today = _state(hass, entry, "sensor", "substitutions_today")
    assert today.state == "2"
    assert today.attributes["published"] is True
    assert len(today.attributes["entries"]) == 2
    assert today.attributes["notices"][0]["lines"] == ["Wandertag\nam Freitag"]  # HTML -> text
    assert today.attributes["stale"] is False
    tomorrow = _state(hass, entry, "sensor", "substitutions_tomorrow")
    assert tomorrow.state == "1"


async def test_unpublished_day_has_zero_entries_and_flag(
    hass: HomeAssistant, populated: FakeLumo, setup
) -> None:
    populated.data["substitutions"] = []
    entry = await setup()
    state = _state(hass, entry, "sensor", "substitutions_today")
    assert state.state == "0"
    assert state.attributes["published"] is False


async def test_cancellation_binary_sensors(hass: HomeAssistant, populated: FakeLumo, setup) -> None:
    entry = await setup()
    today = _state(hass, entry, "binary_sensor", "cancelled_today")
    assert today.state == "on"
    assert today.attributes["cancelled"][0]["subject"] == "M"
    assert _state(hass, entry, "binary_sensor", "cancelled_tomorrow").state == "off"


async def test_homework_sensor_lists_open_homework_as_text(
    hass: HomeAssistant, populated: FakeLumo, setup
) -> None:
    entry = await setup()
    state = _state(hass, entry, "sensor", "open_homework")
    assert state.state == "1"
    assert state.attributes["homework"] == [
        {
            "course": "Mathematik 08b",
            "date": _iso(-1),
            "topic": "Brüche",
            "description": "S. 45\nNr. 3",
        }
    ]


async def test_lesson_sensors(hass: HomeAssistant, populated: FakeLumo, setup) -> None:
    entry = await setup()
    first = _state(hass, entry, "sensor", "first_lesson_tomorrow")
    assert first.attributes["subject"] == "M"
    assert dt_util.as_local(dt_util.parse_datetime(first.state)).hour == 7  # 07:50 local
    next_ = _state(hass, entry, "sensor", "next_lesson")
    assert next_.attributes["room"] == "A104"


async def test_time_based_sensors_follow_the_clock(
    hass: HomeAssistant, populated: FakeLumo, setup, freezer
) -> None:
    entry = await setup()
    assert _state(hass, entry, "sensor", "substitutions_today").state == "2"
    # two days later "today" is a day without a plan entry
    freezer.tick(timedelta(days=2, minutes=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert _state(hass, entry, "sensor", "substitutions_today").state == "0"


async def test_meal_sensors_only_with_caseda(
    hass: HomeAssistant, populated: FakeLumo, setup
) -> None:
    entry = await setup()
    assert _state(hass, entry, "sensor", "meal_balance").state == "8.45"
    meal = _state(hass, entry, "sensor", "meal_today")
    assert meal.state == "Gemüsemaultaschen"
    assert meal.attributes["price"] == 3.9


async def test_no_meal_sensors_without_caseda(
    hass: HomeAssistant, populated: FakeLumo, setup
) -> None:
    del populated.data["meals"]
    entry = await setup()
    assert _state(hass, entry, "sensor", "meal_balance") is None
    assert _state(hass, entry, "sensor", "substitutions_today") is not None


async def test_grades_are_off_by_default(hass: HomeAssistant, populated: FakeLumo, setup) -> None:
    entry = await setup()
    assert _state(hass, entry, "sensor", "grades_count") is None
    assert "grades" not in [path for _, path in populated.requests]


async def test_grades_sensor_with_option(hass: HomeAssistant, populated: FakeLumo, setup) -> None:
    entry = await setup(**{CONF_ENABLE_GRADES: True})
    state = _state(hass, entry, "sensor", "grades_count")
    assert state.state == "1"
    assert state.attributes["courses"] == [
        {
            "course": "Mathematik 08b",
            "grades": [{"name": "1. Klassenarbeit", "date": "12.09.2026", "mark": "2"}],
        }
    ]


async def test_large_attributes_stay_out_of_the_recorder(
    hass: HomeAssistant, populated: FakeLumo, setup
) -> None:
    from custom_components.lumo.sensor import LumoSensor

    unrecorded = LumoSensor._unrecorded_attributes  # noqa: SLF001
    assert {"entries", "homework", "courses", "notices"} <= set(unrecorded)


async def test_stale_data_is_flagged(hass: HomeAssistant, populated: FakeLumo, setup) -> None:
    populated.stale = True
    entry = await setup()
    assert _state(hass, entry, "sensor", "open_homework").attributes["stale"] is True


async def test_calendar_entity_and_events(hass: HomeAssistant, populated: FakeLumo, setup) -> None:
    entry = await setup()
    state = _state(hass, entry, "calendar", "calendar")
    assert state is not None
    assert state.attributes["message"] == "Elternsprechtag"
    assert state.attributes["location"] == "Aula"

    start = dt_util.now()
    # within the synced range: no extra request
    populated.calendar_queries.clear()
    events = await _calendar_events(hass, state.entity_id, start, start + timedelta(days=30))
    assert [e["summary"] for e in events] == ["Elternsprechtag"]
    assert populated.calendar_queries == []

    # outside the synced range the server is asked for exactly that range
    far = start + timedelta(days=100)
    await _calendar_events(hass, state.entity_id, far, far + timedelta(days=5))
    assert populated.calendar_queries == [
        {"from": far.date().isoformat(), "to": (far + timedelta(days=5)).date().isoformat()}
    ]


async def _calendar_events(hass, entity_id, start, end):
    component = hass.data["calendar"]
    entity = component.get_entity(entity_id)
    events = await entity.async_get_events(hass, start, end)
    return [{"summary": e.summary} for e in events]


async def test_diagnostics(hass: HomeAssistant, populated: FakeLumo, setup) -> None:
    entry = await setup(**{CONF_ACCOUNTS: ["k3x9ab", "p7q2mz"]})
    ok = _state(hass, entry, "binary_sensor", "schulportal_connection")
    assert ok.state == "on"
    warn = _state(hass, entry, "binary_sensor", "schulportal_connection", account="p7q2mz")
    assert warn.state == "off"
    assert warn.attributes["state"] == "warn"
    assert warn.attributes["failures"] == 1

    registry = er.async_get(hass)
    update = registry.async_get_entity_id(
        "binary_sensor", DOMAIN, f"{entry.entry_id}_server_update_available"
    )
    state = hass.states.get(update)
    assert state.state == "on"
    assert state.attributes["latest_version"] == "v0.26.0"
    assert registry.async_get_entity_id(
        "binary_sensor", DOMAIN, f"{entry.entry_id}_server_updates_connection"
    )
    # caseda / untis connection entities only exist when the server reports them
    assert _state(hass, entry, "binary_sensor", "caseda_connection") is None


async def test_failing_status_only_affects_diagnostics(
    hass: HomeAssistant, populated: FakeLumo, setup
) -> None:
    populated.fail_paths["/api/status"] = 503
    populated.fail_paths["/api/update"] = 503
    entry = await setup()
    assert _state(hass, entry, "sensor", "open_homework").state == "1"
    assert _state(hass, entry, "binary_sensor", "schulportal_connection") is None


async def test_each_child_gets_a_device(hass: HomeAssistant, populated: FakeLumo, setup) -> None:
    from homeassistant.helpers import device_registry as dr

    entry = await setup(**{CONF_ACCOUNTS: ["k3x9ab", "p7q2mz"]})
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert sorted(d.name for d in devices) == sorted(
        ["Lumo Anna", "Lumo Max", f"Lumo ({entry.data[CONF_HOST]})"]
    )
    by_name = {d.name: d for d in devices}
    server = by_name[f"Lumo ({entry.data[CONF_HOST]})"]
    assert by_name["Lumo Max"].via_device_id == server.id
    assert by_name["Lumo Anna"].via_device_id == server.id
