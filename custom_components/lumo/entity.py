"""Base entities and the helper that adds entities when their data shows up."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .const import CONF_HOST, DOMAIN
from .coordinator import LumoCoordinator


def server_device(entry: ConfigEntry) -> DeviceInfo:
    """The Lumo server: parent of the children, carries the diagnostics."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=f"Lumo ({entry.data[CONF_HOST]})",
        manufacturer="Lumo",
        entry_type=DeviceEntryType.SERVICE,
    )


class LumoServerEntity[C: DataUpdateCoordinator](CoordinatorEntity[C]):
    """Entity of the server device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: C, entry: ConfigEntry, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_server_{key}"
        self._attr_translation_key = key
        self._attr_device_info = server_device(entry)


class LumoEntity(CoordinatorEntity[LumoCoordinator]):
    """Entity of one child; `data_key` is the coordinator key it shows."""

    _attr_has_entity_name = True
    # Lists of lessons, homework, grades, … are large and personal: not for the recorder.
    _unrecorded_attributes = frozenset(
        {"entries", "notices", "homework", "courses", "orders", "cancelled", "next_orders"}
    )

    def __init__(
        self,
        coordinator: LumoCoordinator,
        entry: ConfigEntry,
        key: str,
        data_key: str | None,
    ) -> None:
        super().__init__(coordinator)
        self.data_key = data_key
        self._attr_unique_id = f"{entry.entry_id}_{coordinator.account_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{coordinator.account_id}")},
            name=f"Lumo {coordinator.account_name}",
            manufacturer="Lumo",
            model="Schulportal Hessen",
            via_device=(DOMAIN, entry.entry_id),
        )

    @property
    def envelope(self) -> Any:
        """The envelope of this entity's data key (None if it has none)."""
        if self.data_key is None or not self.coordinator.data:
            return None
        return self.coordinator.data.get(self.data_key)

    @property
    def payload(self) -> Any:
        envelope = self.envelope
        return None if envelope is None else envelope.data

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        return self.data_key is None or self.envelope is not None

    def freshness(self) -> dict[str, Any]:
        """`fetched_at` and `stale` (the server could not refresh from the portal)."""
        envelope = self.envelope
        if envelope is None:
            return {}
        return {"fetched_at": envelope.fetched_at, "stale": envelope.stale}


def add_when_available[C: DataUpdateCoordinator](
    entry: ConfigEntry,
    add: AddConfigEntryEntitiesCallback,
    coordinator: C,
    build: Callable[[C], list[Entity]],
) -> None:
    """Adds the entities `build` returns now and those whose data appears later.

    `build` returns the entities that can exist for the current data (e.g. no meals before
    the Caseda login is set up); unique ids that were added already are skipped.
    """
    known: set[str] = set()

    @callback
    def _check() -> None:
        new = [e for e in build(coordinator) if e.unique_id not in known]
        known.update(e.unique_id for e in new if e.unique_id)
        if new:
            add(new)

    _check()
    entry.async_on_unload(coordinator.async_add_listener(_check))
