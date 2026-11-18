"""Data coordinator of one Lumo account (child): fetching plus live updates over SSE."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    Envelope,
    LumoAuthError,
    LumoClient,
    LumoConnectionError,
    LumoError,
    LumoNotFoundError,
    LumoRateLimitedError,
)
from .changes import new_items
from .const import (
    DOMAIN,
    ENDPOINTS,
    EVENT_DEBOUNCE,
    EVENT_NEW_ITEM,
    FALLBACK_INTERVAL,
    FEATURE_OF,
    MAX_EVENTS_PER_UPDATE,
    RECONNECT_DELAY,
    STATUS_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

# Coordinator data: data key -> envelope; None = not available for this account
# (portal area not enabled, no Caseda login, grades switched off).
type LumoData = dict[str, Envelope | None]


def data_key_for(cache_key: str) -> str | None:
    """Maps a cache key of an `update` event to a data key of the coordinator."""
    if cache_key in ENDPOINTS:
        return cache_key
    if cache_key.startswith("calendar:"):
        return "calendar"
    # course:<id>, homework:all, untis, …: not used by the integration
    return None


class LumoCoordinator(DataUpdateCoordinator[LumoData]):
    """Keeps the data of one child up to date.

    The server syncs the portal in the background; this coordinator only reads the server's
    cache (never `?refresh=1`). Changes arrive over the event stream, a slow poll is the
    fallback when the stream is down.
    """

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        client: LumoClient,
        account: dict[str, Any],
        *,
        enable_grades: bool = False,
        allow_homework_write: bool = False,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN} {account['id']}",
            update_interval=FALLBACK_INTERVAL,
        )
        self.client = client
        self.account = account
        self.account_id: str = account["id"]
        self.enable_grades = enable_grades
        self.allow_homework_write = allow_homework_write
        self._features: set[str] | None = None
        self._pending: set[str] = set()
        self._flush_handle: asyncio.TimerHandle | None = None
        self._events_task: asyncio.Task[None] | None = None

    @property
    def account_name(self) -> str:
        return self.account.get("name") or self.account_id

    @property
    def keys(self) -> list[str]:
        """Data keys that are fetched for this account."""
        keys = [k for k in ENDPOINTS if k != "account"]
        if not self.enable_grades:
            keys.remove("grades")
        if self._features is not None:
            keys = [k for k in keys if FEATURE_OF.get(k) is None or FEATURE_OF[k] in self._features]
        return keys

    # --- fetching -------------------------------------------------------------------

    async def _fetch(self, key: str) -> Envelope | None:
        try:
            return await self.client.get(self.account_id, ENDPOINTS[key])
        except LumoNotFoundError:
            # feature_disabled / meals_disabled: the area does not exist for this child
            return None

    async def _async_update_data(self) -> LumoData:
        previous = self.data or {}
        try:
            account = await self.client.get(self.account_id, ENDPOINTS["account"])
            info = account.data if isinstance(account.data, dict) else {}
            self._features = set(info.get("features", []))
            keys = self.keys
            results = await asyncio.gather(*(self._fetch(k) for k in keys), return_exceptions=True)
        except LumoAuthError as err:
            raise ConfigEntryAuthFailed("Lumo password rejected") from err
        except LumoRateLimitedError as err:
            raise UpdateFailed("Lumo server: too many attempts") from err
        except LumoError as err:
            raise UpdateFailed(f"Lumo server error: {err}") from err

        data: LumoData = {"account": account}
        failures: list[BaseException] = []
        for key, result in zip(keys, results, strict=True):
            if isinstance(result, LumoAuthError):
                raise ConfigEntryAuthFailed("Lumo password rejected") from result
            if isinstance(result, BaseException):
                failures.append(result)
                data[key] = previous.get(key)  # keep the last data of this area
                _LOGGER.debug("Fetching %s failed: %s", key, result)
            else:
                data[key] = result
        if failures and len(failures) == len(keys):
            raise UpdateFailed(f"Lumo server error: {failures[0]}")
        self._fire_new_items(data)
        return data

    # --- live updates ---------------------------------------------------------------

    def start_events(self) -> None:
        """Starts listening to the event stream (idempotent)."""
        if self._events_task is None or self._events_task.done():
            self._events_task = self.config_entry.async_create_background_task(
                self.hass, self._events_loop(), f"lumo events {self.account_id}"
            )

    async def stop_events(self) -> None:
        if self._flush_handle is not None:
            self._flush_handle.cancel()
            self._flush_handle = None
        task, self._events_task = self._events_task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, LumoError):
                await task

    async def _events_loop(self) -> None:
        connected_before = False
        while True:
            try:
                if connected_before:
                    # Changes may have been missed while the stream was down.
                    self.hass.async_create_task(self.async_request_refresh())
                connected_before = True
                async for event in self.client.events(self.account_id):
                    if event.event == "update":
                        self._on_update_event(str(event.data.get("key", "")))
                _LOGGER.debug("Event stream of %s closed by the server", self.account_id)
            except LumoConnectionError as err:
                _LOGGER.debug("Event stream of %s lost: %s", self.account_id, err)
            except LumoAuthError:
                _LOGGER.warning("Lumo session rejected while listening to events")
                self.config_entry.async_start_reauth(self.hass)
                return
            except LumoError as err:
                _LOGGER.debug("Event stream of %s failed: %s", self.account_id, err)
            await asyncio.sleep(RECONNECT_DELAY)

    def _on_update_event(self, cache_key: str) -> None:
        data_key = data_key_for(cache_key)
        if data_key is None or data_key not in self.keys + ["account"]:
            return
        self._pending.add(data_key)
        if self._flush_handle is not None:
            self._flush_handle.cancel()
        self._flush_handle = self.hass.loop.call_later(
            EVENT_DEBOUNCE, lambda: self.hass.async_create_task(self._flush_pending())
        )

    async def _flush_pending(self) -> None:
        self._flush_handle = None
        pending, self._pending = self._pending, set()
        if not pending or self.data is None:
            return
        data = dict(self.data)
        for key in pending:
            try:
                data[key] = await self._fetch(key)
            except LumoAuthError:
                self.config_entry.async_start_reauth(self.hass)
                return
            except LumoError as err:
                _LOGGER.debug("Fetching %s after an event failed: %s", key, err)
        self._fire_new_items(data)
        self.async_set_updated_data(data)

    def _fire_new_items(self, data: LumoData) -> None:
        """Fires `lumo_new_item` for what is new compared with the data held so far."""
        if self.data is None:  # first load: everything would be "new"
            return
        items = new_items(self.data, data)
        if len(items) > MAX_EVENTS_PER_UPDATE:
            _LOGGER.debug("%d new items, firing the first %d", len(items), MAX_EVENTS_PER_UPDATE)
        for item in items[:MAX_EVENTS_PER_UPDATE]:
            self.hass.bus.async_fire(
                EVENT_NEW_ITEM,
                {"account_id": self.account_id, "account_name": self.account_name, **item},
            )

    # --- actions --------------------------------------------------------------------

    async def async_refresh_portal(self) -> None:
        """Asks the server to sync the portal now (the result arrives as events)."""
        await self.client.refresh(self.account_id)

    async def async_set_homework_done(self, course_id: str, entry_id: str, done: bool) -> None:
        """Marks homework as done. Only with the option "allow_homework_write"."""
        if not self.allow_homework_write:
            raise HomeAssistantError("Marking homework as done is switched off in the options")
        await self.client.set_homework_done(self.account_id, course_id, entry_id, done)
        await self.async_request_refresh()


class LumoStatusCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Health of the services (`/api/status`) and app update (`/api/update`) of the server.

    Server-wide, polled slowly: it only feeds the diagnostic entities.
    """

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry, client: LumoClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN} status",
            update_interval=STATUS_INTERVAL,
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, Any]:
        status, update = await asyncio.gather(
            self.client.status(), self.client.update_info(), return_exceptions=True
        )
        for result in (status, update):
            if isinstance(result, LumoAuthError):
                raise ConfigEntryAuthFailed("Lumo password rejected") from result
        if isinstance(status, BaseException) and isinstance(update, BaseException):
            raise UpdateFailed(f"Lumo server error: {status}")
        previous = self.data or {}
        return {
            "status": previous.get("status") if isinstance(status, BaseException) else status,
            "update": previous.get("update") if isinstance(update, BaseException) else update,
        }
