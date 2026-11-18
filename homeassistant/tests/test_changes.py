"""Tests of the diff behind the `lumo_new_item` event."""

from __future__ import annotations

from typing import Any

from custom_components.lumo.api import Envelope
from custom_components.lumo.changes import new_items


def _env(data: Any) -> Envelope:
    return Envelope(
        data=data, key=None, fetched_at=None, cached=True, stale=False, refreshing=False, extra={}
    )


def _entry(**kw: Any) -> dict[str, Any]:
    return {"period": "1", "type": "Vertretung", "subject": "D", "className": "08b", **kw}


def _plan(*entries: dict[str, Any], date: str = "2026-11-10") -> Envelope:
    return _env([{"date": date, "entries": list(entries), "notices": []}])


def _hw(entry_id: str, done: bool = False) -> dict[str, Any]:
    return {
        "courseId": "104",
        "courseName": "Mathematik 08b",
        "entryId": entry_id,
        "date": "2026-11-09",
        "topic": "Brüche",
        "description": "S. 45<br>Nr. 3",
        "done": done,
    }


def test_new_and_changed_substitutions() -> None:
    old = {"substitutions": _plan(_entry())}
    new = {"substitutions": _plan(_entry(), _entry(period="3", type="Entfall"), _entry(room="A9"))}
    items = new_items(old, new)
    assert [(i["kind"], i["period"], i.get("room")) for i in items] == [
        ("substitution", "3", None),
        ("substitution", "1", "A9"),  # a changed entry counts as new
    ]
    assert items[0]["date"] == "2026-11-10"
    assert "note" not in items[0]  # empty fields are left out


def test_unchanged_data_has_no_new_items() -> None:
    data = {"substitutions": _plan(_entry()), "homework": _env([_hw("1")])}
    assert new_items(data, dict(data)) == []


def test_new_homework_only_when_open() -> None:
    old = {"homework": _env([_hw("1")])}
    new = {"homework": _env([_hw("1"), _hw("2"), _hw("3", done=True)])}
    items = new_items(old, new)
    assert len(items) == 1
    assert items[0]["kind"] == "homework"
    assert items[0]["description"] == "S. 45\nNr. 3"  # HTML as text


def test_homework_marked_undone_again_is_not_new() -> None:
    old = {"homework": _env([_hw("1", done=True)])}
    new = {"homework": _env([_hw("1", done=False)])}
    assert new_items(old, new) == []


def test_new_grades() -> None:
    course = {"course": {"id": "104", "name": "Mathematik 08b"}}
    first = {**course, "grades": [{"name": "1. KA", "date": "12.09.2026", "mark": "2"}]}
    second = {
        **course,
        "grades": first["grades"] + [{"name": "2. KA", "date": "3.12.", "mark": "1"}],
    }
    items = new_items({"grades": _env([first])}, {"grades": _env([second])})
    assert items == [
        {"kind": "grade", "course": "Mathematik 08b", "name": "2. KA", "date": "3.12.", "mark": "1"}
    ]


def test_areas_missing_on_one_side_are_skipped() -> None:
    # e.g. the area was unavailable before (kept as None) or grades were just switched on
    assert new_items({"substitutions": None}, {"substitutions": _plan(_entry())}) == []
    assert new_items({}, {"grades": _env([{"course": {}, "grades": [{"name": "x"}]}])}) == []
