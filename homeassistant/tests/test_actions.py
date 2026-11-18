"""Tests of the button, the homework to-do list and the `lumo_new_item` event."""

from __future__ import annotations

import pytest
from homeassistant.components.todo import TodoListEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.lumo.const import (
    CONF_ALLOW_HOMEWORK_WRITE,
    CONF_ENABLE_GRADES,
    DOMAIN,
    EVENT_NEW_ITEM,
    MAX_EVENTS_PER_UPDATE,
)

from .fake_server import FakeLumo
from .test_entities import setup  # noqa: F401  (fixture)

HOMEWORK = [
    {
        "courseId": "104",
        "courseName": "Mathematik 08b",
        "entryId": "1",
        "date": "2026-11-09",
        "topic": "Brüche",
        "description": "S. 45<br>Nr. 3",
        "done": False,
    },
    {
        "courseId": "105",
        "courseName": "Deutsch 08b",
        "entryId": "2",
        "date": "2026-11-10",
        "topic": "Gedicht",
        "description": None,
        "done": True,
    },
]


def _entity_id(hass: HomeAssistant, entry, platform: str, key: str) -> str:
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(platform, DOMAIN, f"{entry.entry_id}_k3x9ab_{key}")
    assert entity_id is not None
    return entity_id


async def test_refresh_button(hass: HomeAssistant, fake: tuple[FakeLumo, str], setup) -> None:  # noqa: F811
    server, _ = fake
    entry = await setup()
    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": _entity_id(hass, entry, "button", "refresh")},
        blocking=True,
    )
    assert ("POST", "refresh") in server.requests


async def test_refresh_button_reports_errors(
    hass: HomeAssistant,
    fake: tuple[FakeLumo, str],
    setup,  # noqa: F811
) -> None:
    server, _ = fake
    entry = await setup()
    server.fail_paths["refresh"] = 503
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": _entity_id(hass, entry, "button", "refresh")},
            blocking=True,
        )


async def test_todo_is_read_only_by_default(
    hass: HomeAssistant,
    fake: tuple[FakeLumo, str],
    setup,  # noqa: F811
) -> None:
    server, _ = fake
    server.data["homework"] = HOMEWORK
    entry = await setup()
    entity_id = _entity_id(hass, entry, "todo", "homework")
    state = hass.states.get(entity_id)
    assert state.state == "1"  # one open item
    assert not state.attributes["supported_features"] & TodoListEntityFeature.UPDATE_TODO_ITEM

    items = (
        await hass.services.async_call(
            "todo", "get_items", {"entity_id": entity_id}, blocking=True, return_response=True
        )
    )[entity_id]["items"]
    assert [(i["summary"], i["status"]) for i in items] == [
        ("Mathematik 08b: Brüche", "needs_action"),
        ("Deutsch 08b: Gedicht", "completed"),
    ]
    assert items[0]["description"] == "S. 45\nNr. 3"

    with pytest.raises(HomeAssistantError):  # the service is not offered for this list
        await hass.services.async_call(
            "todo",
            "update_item",
            {"entity_id": entity_id, "item": "104/1", "status": "completed"},
            blocking=True,
        )
    assert server.homework_puts == []


async def test_todo_tick_off_with_option(
    hass: HomeAssistant,
    fake: tuple[FakeLumo, str],
    setup,  # noqa: F811
) -> None:
    server, _ = fake
    server.data["homework"] = HOMEWORK
    entry = await setup(**{CONF_ALLOW_HOMEWORK_WRITE: True})
    entity_id = _entity_id(hass, entry, "todo", "homework")
    assert hass.states.get(entity_id).attributes["supported_features"] & (
        TodoListEntityFeature.UPDATE_TODO_ITEM
    )

    await hass.services.async_call(
        "todo",
        "update_item",
        {"entity_id": entity_id, "item": "104/1", "status": "completed"},
        blocking=True,
    )
    assert server.homework_puts == [("104", "1", True)]

    # untick works too
    await hass.services.async_call(
        "todo",
        "update_item",
        {"entity_id": entity_id, "item": "105/2", "status": "needs_action"},
        blocking=True,
    )
    assert server.homework_puts[-1] == ("105", "2", False)

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "todo",
            "update_item",
            {"entity_id": entity_id, "item": "999/9", "status": "completed"},
            blocking=True,
        )
    assert len(server.homework_puts) == 2


async def test_new_items_fire_events(
    hass: HomeAssistant,
    fake: tuple[FakeLumo, str],
    setup,  # noqa: F811
) -> None:
    server, _ = fake
    server.data["homework"] = HOMEWORK[:1]
    entry = await setup()
    events = async_capture_events(hass, EVENT_NEW_ITEM)
    await hass.async_block_till_done()
    assert events == []  # the first load does not announce everything as new

    server.data["homework"] = HOMEWORK
    server.data["substitutions"] = [
        {
            "date": "2026-11-10",
            "entries": [{"period": "1", "type": "Entfall", "subject": "M", "className": "08b"}],
            "notices": [],
        }
    ]
    await entry.runtime_data.coordinators["k3x9ab"].async_refresh()
    await hass.async_block_till_done()

    kinds = sorted((e.data["kind"], e.data["account_id"], e.data["account_name"]) for e in events)
    assert kinds == [("substitution", "k3x9ab", "Max")]  # the new homework is already done

    server.data["homework"] = [*HOMEWORK, {**HOMEWORK[0], "entryId": "3", "topic": "Prozent"}]
    await entry.runtime_data.coordinators["k3x9ab"].async_refresh()
    await hass.async_block_till_done()
    assert [e.data["topic"] for e in events if e.data["kind"] == "homework"] == ["Prozent"]

    # an unchanged refresh fires nothing more
    count = len(events)
    await entry.runtime_data.coordinators["k3x9ab"].async_refresh()
    await hass.async_block_till_done()
    assert len(events) == count


async def test_event_burst_is_capped(
    hass: HomeAssistant,
    fake: tuple[FakeLumo, str],
    setup,  # noqa: F811
) -> None:
    server, _ = fake
    entry = await setup()
    events = async_capture_events(hass, EVENT_NEW_ITEM)
    server.data["substitutions"] = [
        {
            "date": "2026-11-10",
            "entries": [{"period": str(n), "type": "Vertretung"} for n in range(60)],
            "notices": [],
        }
    ]
    await entry.runtime_data.coordinators["k3x9ab"].async_refresh()
    await hass.async_block_till_done()
    assert len(events) == MAX_EVENTS_PER_UPDATE


async def test_grade_events_only_with_the_option(
    hass: HomeAssistant,
    fake: tuple[FakeLumo, str],
    setup,  # noqa: F811
) -> None:
    server, _ = fake
    course = {"course": {"id": "104", "name": "Mathematik 08b"}, "exams": []}
    server.data["grades"] = [{**course, "grades": []}]

    off = await setup()
    events = async_capture_events(hass, EVENT_NEW_ITEM)
    server.data["grades"] = [{**course, "grades": [{"name": "1. KA", "date": "x", "mark": "2"}]}]
    await off.runtime_data.coordinators["k3x9ab"].async_refresh()
    await hass.async_block_till_done()
    assert events == []  # grades are not even fetched

    on = await setup(**{CONF_ENABLE_GRADES: True})
    server.data["grades"][0]["grades"].append({"name": "2. KA", "date": "y", "mark": "1"})
    await on.runtime_data.coordinators["k3x9ab"].async_refresh()
    await hass.async_block_till_done()
    assert [e.data["name"] for e in events if e.data["kind"] == "grade"]
