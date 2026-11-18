"""Button: ask the server to sync the portal now."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import LumoConfigEntry
from .api import LumoError
from .coordinator import LumoCoordinator
from .entity import LumoEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: LumoConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities(
        LumoRefreshButton(coordinator, entry)
        for coordinator in entry.runtime_data.coordinators.values()
    )


class LumoRefreshButton(LumoEntity, ButtonEntity):
    """Starts a sync of all data of the child; the new data arrives as events."""

    def __init__(self, coordinator: LumoCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "refresh", None)

    async def async_press(self) -> None:
        try:
            await self.coordinator.async_refresh_portal()
        except LumoError as err:
            raise HomeAssistantError(f"Lumo refresh failed: {err}") from err
