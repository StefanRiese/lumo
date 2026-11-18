"""Homework as a to-do list. Ticking an item writes to the real Schulportal (opt-in)."""

from __future__ import annotations

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import LumoConfigEntry
from .api import LumoError
from .coordinator import LumoCoordinator
from .entity import LumoEntity, add_when_available
from .util import html_to_text

PARALLEL_UPDATES = 1


def _uid(item: dict) -> str:
    return f"{item.get('courseId')}/{item.get('entryId')}"


async def async_setup_entry(
    hass: HomeAssistant, entry: LumoConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    for coordinator in entry.runtime_data.coordinators.values():
        add_when_available(
            entry,
            async_add_entities,
            coordinator,
            lambda c: (
                [LumoHomeworkList(c, entry)]
                if c.data and c.data.get("homework") is not None
                else []
            ),
        )


class LumoHomeworkList(LumoEntity, TodoListEntity):
    """The homework of the portal's overview (the latest lesson per course)."""

    def __init__(self, coordinator: LumoCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "homework", "homework")

    @property
    def supported_features(self) -> TodoListEntityFeature:
        # Read-only unless the option "allow marking homework as done" is on.
        if self.coordinator.allow_homework_write:
            return TodoListEntityFeature.UPDATE_TODO_ITEM
        return TodoListEntityFeature(0)

    @property
    def todo_items(self) -> list[TodoItem] | None:
        if self.envelope is None:
            return None
        homework = sorted(self.payload or [], key=lambda h: h.get("date") or "", reverse=True)
        items = [
            TodoItem(
                uid=_uid(h),
                summary=f"{h.get('courseName') or '?'}: {h.get('topic') or '–'}",
                description=html_to_text(h.get("description")) or None,
                status=TodoItemStatus.COMPLETED if h.get("done") else TodoItemStatus.NEEDS_ACTION,
            )
            for h in homework
        ]
        # open homework first
        return sorted(items, key=lambda i: i.status == TodoItemStatus.COMPLETED)

    async def async_update_todo_item(self, item: TodoItem) -> None:
        if item.uid is None or "/" not in item.uid:
            raise HomeAssistantError("Unknown homework item")
        course_id, entry_id = item.uid.split("/", 1)
        known = {_uid(h) for h in self.payload or []}
        if item.uid not in known:
            raise HomeAssistantError("This homework no longer exists")
        try:
            await self.coordinator.async_set_homework_done(
                course_id, entry_id, item.status == TodoItemStatus.COMPLETED
            )
        except LumoError as err:
            raise HomeAssistantError(f"Could not update the homework: {err}") from err
