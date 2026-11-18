"""Finds what is new between two coordinator data sets (for the `lumo_new_item` event)."""

from __future__ import annotations

from typing import Any

from .util import html_to_text

type LumoData = dict[str, Any]

_SUBSTITUTION_FIELDS = (
    "period",
    "type",
    "subject",
    "previousSubject",
    "teacher",
    "substitute",
    "room",
    "previousRoom",
    "className",
    "note",
)


def _payload(data: LumoData, key: str) -> Any | None:
    envelope = data.get(key)
    return None if envelope is None else envelope.data


def _substitution_key(day: str, entry: dict[str, Any]) -> tuple[Any, ...]:
    return (day, *(entry.get(field) for field in _SUBSTITUTION_FIELDS))


def _homework_key(item: dict[str, Any]) -> str:
    return f"{item.get('courseId')}/{item.get('entryId')}"


def _grade_key(course: dict[str, Any], grade: dict[str, Any]) -> tuple[Any, ...]:
    return ((course.get("course") or {}).get("id"), grade.get("name"), grade.get("date"))


def new_items(previous: LumoData, current: LumoData) -> list[dict[str, Any]]:
    """New or changed substitution entries, new open homework, new grades.

    Compares only areas that exist in both data sets; the first load (no `previous`)
    produces nothing. An entry that changed (e.g. another room) counts as new.
    """
    items: list[dict[str, Any]] = []

    old_days, new_days = _payload(previous, "substitutions"), _payload(current, "substitutions")
    if old_days is not None and new_days is not None:
        seen = {
            _substitution_key(day["date"], e) for day in old_days for e in day.get("entries", [])
        }
        for day in new_days:
            for entry in day.get("entries", []):
                if _substitution_key(day["date"], entry) not in seen:
                    items.append(
                        {
                            "kind": "substitution",
                            "date": day["date"],
                            **{k: v for k, v in entry.items() if v not in (None, "")},
                        }
                    )

    old_homework, new_homework = _payload(previous, "homework"), _payload(current, "homework")
    if old_homework is not None and new_homework is not None:
        seen_homework = {_homework_key(h) for h in old_homework}
        for item in new_homework:
            if _homework_key(item) not in seen_homework and not item.get("done"):
                items.append(
                    {
                        "kind": "homework",
                        "course": item.get("courseName"),
                        "date": item.get("date"),
                        "topic": item.get("topic"),
                        "description": html_to_text(item.get("description")),
                    }
                )

    old_grades, new_grades = _payload(previous, "grades"), _payload(current, "grades")
    if old_grades is not None and new_grades is not None:
        seen_grades = {_grade_key(c, g) for c in old_grades for g in c.get("grades", [])}
        for course in new_grades:
            for grade in course.get("grades", []):
                if _grade_key(course, grade) not in seen_grades:
                    items.append(
                        {
                            "kind": "grade",
                            "course": (course.get("course") or {}).get("name"),
                            "name": grade.get("name"),
                            "date": grade.get("date"),
                            "mark": grade.get("mark"),
                        }
                    )
    return items
