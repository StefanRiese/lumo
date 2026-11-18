"""Binary sensors: cancellations and the diagnostics (service health, app update)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from . import LumoConfigEntry
from .coordinator import LumoCoordinator, LumoStatusCoordinator
from .entity import LumoEntity, LumoServerEntity, add_when_available
from .util import day_entry, is_cancellation

PARALLEL_UPDATES = 0


def _cancelled(data: dict[str, Any], now: datetime, offset: int) -> list[dict[str, Any]]:
    day = now.date() + timedelta(days=offset)
    entry = day_entry(data["substitutions"].data, day)
    return [e for e in (entry or {}).get("entries", []) if is_cancellation(e)]


@dataclass(frozen=True, kw_only=True)
class LumoCancellationDescription(BinarySensorEntityDescription):
    offset: int


CANCELLATIONS: tuple[LumoCancellationDescription, ...] = (
    LumoCancellationDescription(key="cancelled_today", translation_key="cancelled_today", offset=0),
    LumoCancellationDescription(
        key="cancelled_tomorrow", translation_key="cancelled_tomorrow", offset=1
    ),
)


class LumoCancellationSensor(LumoEntity, BinarySensorEntity):
    """On if the plan has a cancelled lesson on the day (after the server's own filter)."""

    entity_description: LumoCancellationDescription

    def __init__(
        self,
        coordinator: LumoCoordinator,
        entry: ConfigEntry,
        description: LumoCancellationDescription,
    ) -> None:
        super().__init__(coordinator, entry, description.key, "substitutions")
        self.entity_description = description

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        @callback
        def _tick(_now: datetime) -> None:
            self.async_write_ha_state()

        self.async_on_remove(async_track_time_interval(self.hass, _tick, timedelta(minutes=1)))

    @property
    def is_on(self) -> bool | None:
        if self.envelope is None:
            return None
        return bool(
            _cancelled(self.coordinator.data, dt_util.now(), self.entity_description.offset)
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.envelope is None:
            return None
        cancelled = _cancelled(self.coordinator.data, dt_util.now(), self.entity_description.offset)
        return self.freshness() | {
            "cancelled": [{k: v for k, v in e.items() if v not in (None, "")} for e in cancelled]
        }


class LumoServiceSensor(LumoEntity, BinarySensorEntity):
    """Connection of one child's service (Schulportal, Caseda, WebUntis) from `/api/status`."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: LumoCoordinator,
        status: LumoStatusCoordinator,
        entry: ConfigEntry,
        service: str,
    ) -> None:
        super().__init__(coordinator, entry, f"{service}_connection", None)
        self._status = status
        self._service = service

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._status.async_add_listener(self.async_write_ha_state))

    def _service_state(self) -> dict[str, Any] | None:
        status = (self._status.data or {}).get("status") or {}
        for account in status.get("accounts", []):
            if account.get("id") == self.coordinator.account_id:
                for service in account.get("services", []):
                    if service.get("key") == self._service:
                        return service
        return None

    @property
    def available(self) -> bool:
        return self._status.last_update_success and self._service_state() is not None

    @property
    def is_on(self) -> bool | None:
        service = self._service_state()
        if service is None or service.get("state") == "unknown":
            return None
        return service.get("state") == "ok"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        service = self._service_state()
        if service is None:
            return None
        return {
            "state": service.get("state"),
            "detail": service.get("detail"),
            "last_success": service.get("lastSuccess"),
            "failures": service.get("failures"),
        }


class LumoServerServiceSensor(LumoServerEntity[LumoStatusCoordinator], BinarySensorEntity):
    """Connection of a server-wide service (ntfy, update server)."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator: LumoStatusCoordinator, entry: ConfigEntry, service: str
    ) -> None:
        super().__init__(coordinator, entry, f"{service}_connection")
        self._service = service

    def _service_state(self) -> dict[str, Any] | None:
        status = (self.coordinator.data or {}).get("status") or {}
        for service in status.get("services", []):
            if service.get("key") == self._service:
                return service
        return None

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self._service_state() is not None

    @property
    def is_on(self) -> bool | None:
        service = self._service_state()
        if service is None or service.get("state") == "unknown":
            return None
        return service.get("state") == "ok"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        service = self._service_state()
        if service is None:
            return None
        return {"state": service.get("state"), "detail": service.get("detail")}


class LumoUpdateAvailableSensor(LumoServerEntity[LumoStatusCoordinator], BinarySensorEntity):
    """A newer Lumo release exists (`/api/update`)."""

    _attr_device_class = BinarySensorDeviceClass.UPDATE
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: LumoStatusCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "update_available")

    def _update(self) -> dict[str, Any] | None:
        return (self.coordinator.data or {}).get("update")

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self._update() is not None

    @property
    def is_on(self) -> bool | None:
        update = self._update()
        return None if update is None else bool(update.get("available"))

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        update = self._update()
        if update is None:
            return None
        return {
            "installed_version": update.get("current"),
            "latest_version": update.get("latest"),
            "release_url": update.get("url"),
        }


async def async_setup_entry(
    hass: HomeAssistant, entry: LumoConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    runtime = entry.runtime_data
    status = runtime.status_coordinator

    for coordinator in runtime.coordinators.values():
        add_when_available(
            entry,
            async_add_entities,
            coordinator,
            lambda c: [
                LumoCancellationSensor(c, entry, description)
                for description in CANCELLATIONS
                if c.data and c.data.get("substitutions") is not None
            ],
        )

        def build_services(
            _status: LumoStatusCoordinator, c: LumoCoordinator = coordinator
        ) -> list:
            # Only the services the server reports for this child (caseda/untis if set up).
            accounts = ((status.data or {}).get("status") or {}).get("accounts", [])
            keys = [
                service.get("key")
                for account in accounts
                if account.get("id") == c.account_id
                for service in account.get("services", [])
            ]
            return [LumoServiceSensor(c, status, entry, key) for key in keys if key]

        # registered on the status coordinator: the services appear when its data does
        add_when_available(entry, async_add_entities, status, build_services)

    def build_server(c: LumoStatusCoordinator) -> list[LumoServerEntity[Any]]:
        data = c.data or {}
        entities: list[LumoServerEntity[Any]] = []
        for service in (data.get("status") or {}).get("services", []):
            if service.get("key"):
                entities.append(LumoServerServiceSensor(c, entry, service["key"]))
        if data.get("update") is not None:
            entities.append(LumoUpdateAvailableSensor(c, entry))
        return entities

    add_when_available(entry, async_add_entities, status, build_server)
