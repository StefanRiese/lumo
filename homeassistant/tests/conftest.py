"""Shared fixtures."""

from __future__ import annotations

from collections.abc import AsyncIterator

import aiohttp
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lumo.api import LumoClient
from custom_components.lumo.const import DOMAIN

from .fake_server import PASSWORD, FakeLumo


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Lets Home Assistant load custom_components/lumo."""


@pytest.fixture
async def fake(socket_enabled: None) -> AsyncIterator[tuple[FakeLumo, str]]:
    server = FakeLumo()
    url = await server.start()
    yield server, url
    await server.stop()


@pytest.fixture
async def client(fake: tuple[FakeLumo, str]) -> AsyncIterator[LumoClient]:
    _, url = fake
    async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as session:
        yield LumoClient(session, url, PASSWORD, timeout=5)


@pytest.fixture
def config_entry() -> MockConfigEntry:
    return MockConfigEntry(domain=DOMAIN, data={}, title="Lumo")
