"""Tests of the coordinator: fetching, option handling and live updates."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lumo import coordinator as coordinator_module
from custom_components.lumo.api import LumoClient
from custom_components.lumo.coordinator import LumoCoordinator, data_key_for

from .fake_server import FakeLumo

Make = Callable[..., Awaitable[LumoCoordinator]]


@pytest.fixture(autouse=True)
def _fast_timers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(coordinator_module, "EVENT_DEBOUNCE", 0.05)
    monkeypatch.setattr(coordinator_module, "RECONNECT_DELAY", 0.05)


@pytest.fixture
async def make(
    hass: HomeAssistant,
    fake: tuple[FakeLumo, str],
    client: LumoClient,
    config_entry: MockConfigEntry,
) -> AsyncIterator[Make]:
    config_entry.add_to_hass(hass)
    created: list[LumoCoordinator] = []

    async def factory(**options: bool) -> LumoCoordinator:
        coordinator = LumoCoordinator(
            hass, config_entry, client, {"id": "k3x9ab", "name": "Max"}, **options
        )
        created.append(coordinator)
        await coordinator.async_refresh()
        return coordinator

    yield factory
    for coordinator in created:
        await coordinator.stop_events()
        await coordinator.async_shutdown()


def _fetched(server: FakeLumo) -> list[str]:
    return [path for method, path in server.requests if method == "GET"]


async def _until(predicate: Callable[[], bool], timeout: float = 3.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


def test_data_key_for() -> None:
    assert data_key_for("substitutions") == "substitutions"
    assert data_key_for("calendar:2026-11-10:2027-01-09") == "calendar"
    assert data_key_for("homework") == "homework"
    assert data_key_for("homework:all") is None
    assert data_key_for("course:104") is None
    assert data_key_for("untis") is None


async def test_grades_are_not_fetched_by_default(fake: tuple[FakeLumo, str], make: Make) -> None:
    server, _ = fake
    coordinator = await make()
    assert coordinator.last_update_success
    assert set(coordinator.data) == {
        "account",
        "timetable",
        "substitutions",
        "calendar",
        "homework",
        "meals",
    }
    assert "grades" not in _fetched(server)
    assert coordinator.data["meals"] is None  # 404: not set up for this child
    assert coordinator.data["substitutions"].data == server.data["substitutions"]


async def test_grades_option_fetches_grades(fake: tuple[FakeLumo, str], make: Make) -> None:
    server, _ = fake
    coordinator = await make(enable_grades=True)
    assert "grades" in _fetched(server)
    assert coordinator.data["grades"].data == []


async def test_disabled_features_are_skipped(fake: tuple[FakeLumo, str], make: Make) -> None:
    server, _ = fake
    server.data["account"] = {**server.data["account"], "features": ["timetable"]}
    coordinator = await make(enable_grades=True)
    assert set(coordinator.data) == {"account", "timetable", "meals"}
    assert "calendar" not in _fetched(server)
    assert "grades" not in _fetched(server)


async def test_partial_failure_keeps_previous_data(fake: tuple[FakeLumo, str], make: Make) -> None:
    server, _ = fake
    coordinator = await make()
    before = coordinator.data["homework"]
    server.fail_paths["homework"] = 503
    await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert coordinator.data["homework"] is before


async def test_total_failure_marks_update_failed(fake: tuple[FakeLumo, str], make: Make) -> None:
    server, _ = fake
    coordinator = await make()
    server.fail_paths["account"] = 503
    await coordinator.async_refresh()
    assert not coordinator.last_update_success
    assert isinstance(coordinator.last_exception, UpdateFailed)


async def test_rejected_password_requests_reauth(
    fake: tuple[FakeLumo, str], make: Make, client: LumoClient
) -> None:
    server, _ = fake
    coordinator = await make()
    server.expire_sessions()
    client._password = "changed"  # noqa: SLF001
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()  # noqa: SLF001


async def test_update_events_refetch_only_the_key(fake: tuple[FakeLumo, str], make: Make) -> None:
    server, _ = fake
    coordinator = await make()
    coordinator.start_events()
    await _until(lambda: server.event_streams == 1)
    server.requests.clear()

    server.data["substitutions"] = [{"date": "2026-11-11", "entries": [], "notices": []}]
    # a burst (e.g. a sync of the course pages) is fetched once; unused keys are ignored
    for _ in range(3):
        server.push("update", {"key": "substitutions", "fetchedAt": "t"})
    server.push("update", {"key": "course:104", "fetchedAt": "t"})
    server.push("update", {"key": "untis", "fetchedAt": "t"})

    await _until(lambda: coordinator.data["substitutions"].data[0]["date"] == "2026-11-11")
    assert _fetched(server) == ["substitutions"]


async def test_calendar_event_with_range_key(fake: tuple[FakeLumo, str], make: Make) -> None:
    server, _ = fake
    coordinator = await make()
    coordinator.start_events()
    await _until(lambda: server.event_streams == 1)
    server.data["calendar"] = [{"id": "1", "title": "Elternsprechtag"}]
    server.push("update", {"key": "calendar:2026-11-10:2027-01-09", "fetchedAt": "t"})
    await _until(lambda: coordinator.data["calendar"].data == server.data["calendar"])


async def test_grades_event_ignored_when_option_is_off(
    fake: tuple[FakeLumo, str], make: Make
) -> None:
    server, _ = fake
    coordinator = await make()
    coordinator.start_events()
    await _until(lambda: server.event_streams == 1)
    server.requests.clear()
    server.push("update", {"key": "grades", "fetchedAt": "t"})
    server.push("update", {"key": "homework", "fetchedAt": "t"})
    await _until(lambda: "homework" in _fetched(server))
    await asyncio.sleep(0.15)
    assert _fetched(server) == ["homework"]


async def test_reconnect_refreshes_everything(fake: tuple[FakeLumo, str], make: Make) -> None:
    server, _ = fake
    coordinator = await make()
    coordinator.start_events()
    await _until(lambda: server.event_streams == 1)
    server.requests.clear()
    server.data["homework"] = [{"courseId": "104", "entryId": "1", "done": False}]
    server.close_streams()  # the stream breaks; changes during the gap must not be lost
    await _until(lambda: server.event_streams == 2)
    await _until(lambda: coordinator.data["homework"].data == server.data["homework"])


async def test_homework_write_is_off_by_default(fake: tuple[FakeLumo, str], make: Make) -> None:
    server, _ = fake
    coordinator = await make()
    with pytest.raises(HomeAssistantError):
        await coordinator.async_set_homework_done("104", "2219", True)
    assert server.homework_puts == []


async def test_homework_write_with_option(fake: tuple[FakeLumo, str], make: Make) -> None:
    server, _ = fake
    coordinator = await make(allow_homework_write=True)
    await coordinator.async_set_homework_done("104", "2219", True)
    assert server.homework_puts == [("104", "2219", True)]


async def test_refresh_portal(fake: tuple[FakeLumo, str], make: Make) -> None:
    server, _ = fake
    coordinator = await make()
    await coordinator.async_refresh_portal()
    assert ("POST", "refresh") in server.requests
