"""Lumo – Home Assistant integration for the self-hosted Schulportal Hessen client."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr

from .api import LumoAuthError, LumoClient, LumoError
from .const import (
    CONF_ACCOUNTS,
    CONF_ALLOW_HOMEWORK_WRITE,
    CONF_ENABLE_GRADES,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SSL,
    DEFAULT_PORT,
)
from .coordinator import LumoCoordinator, LumoStatusCoordinator
from .entity import server_device

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CALENDAR,
    Platform.SENSOR,
    Platform.TODO,
]


@dataclass
class LumoRuntimeData:
    """What a loaded config entry keeps."""

    client: LumoClient
    status_coordinator: LumoStatusCoordinator
    # All children of the server (id -> account dict), also those not selected.
    server_accounts: dict[str, dict[str, Any]]
    # One coordinator per selected child, by account id.
    coordinators: dict[str, LumoCoordinator] = field(default_factory=dict)


type LumoConfigEntry = ConfigEntry[LumoRuntimeData]


def base_url(host: str, port: int, ssl: bool) -> str:
    """`http(s)://host:port`; IPv6 literals get brackets."""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{'https' if ssl else 'http'}://{host}:{port}"


async def async_setup_entry(hass: HomeAssistant, entry: LumoConfigEntry) -> bool:
    data = entry.data
    # Own session and cookie jar (closed on unload): the login cookie must not mix with other
    # integrations, and a reload must not leak sessions. Home Assistant's shared sessions
    # cannot be closed, so this does not use them.
    session = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True))
    entry.async_on_unload(session.close)
    client = LumoClient(
        session,
        base_url(data[CONF_HOST], data.get(CONF_PORT, DEFAULT_PORT), data.get(CONF_SSL, False)),
        data[CONF_PASSWORD],
    )
    try:
        await client.login()
        accounts = await client.accounts()
    except LumoAuthError as err:
        raise ConfigEntryAuthFailed("Lumo password rejected") from err
    except LumoError as err:  # connection, rate limit, setup required, …
        raise ConfigEntryNotReady(f"Lumo server not ready: {err}") from err

    status_coordinator = LumoStatusCoordinator(hass, entry, client)
    await status_coordinator.async_refresh()  # a failure only makes the diagnostics unavailable
    runtime = LumoRuntimeData(client, status_coordinator, {a["id"]: a for a in accounts})
    entry.runtime_data = runtime

    selected: list[str] = entry.options.get(CONF_ACCOUNTS, list(runtime.server_accounts))
    for account_id in selected:
        account = runtime.server_accounts.get(account_id)
        if account is None:
            _LOGGER.warning("Lumo account %s no longer exists on the server", account_id)
            continue
        coordinator = LumoCoordinator(
            hass,
            entry,
            client,
            account,
            enable_grades=entry.options.get(CONF_ENABLE_GRADES, False),
            allow_homework_write=entry.options.get(CONF_ALLOW_HOMEWORK_WRITE, False),
        )
        await coordinator.async_config_entry_first_refresh()
        runtime.coordinators[account_id] = coordinator

    for coordinator in runtime.coordinators.values():
        coordinator.start_events()
        entry.async_on_unload(coordinator.stop_events)

    # The server device must exist before the children refer to it with via_device.
    dr.async_get(hass).async_get_or_create(config_entry_id=entry.entry_id, **server_device(entry))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: LumoConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: LumoConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
