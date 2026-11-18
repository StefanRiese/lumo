"""Tests of the pure helpers: HTML to text, timetable weeks, calendar events."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from custom_components.lumo.calendar import to_event
from custom_components.lumo.timetable import first_lesson_on, lessons_on, next_lesson, week_of
from custom_components.lumo.util import day_entry, html_to_text, is_cancellation


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, ""),
        ("S. 45 Nr. 3&ndash;5", "S. 45 Nr. 3–5"),
        (
            "Zeile 1<br>Zeile 2<BR/>  <b>fett</b>  &amp; <a href='x'>Link</a>",
            "Zeile 1\nZeile 2\nfett & Link",
        ),
        ("<p>Absatz</p><p>Zwei</p>", "Absatz\nZwei"),
        ("<script>alert(1)</script>Text", "alert(1)Text"),  # markup is dropped, never passed on
    ],
)
def test_html_to_text(raw: str | None, expected: str) -> None:
    assert html_to_text(raw) == expected


def test_cancellations() -> None:
    assert is_cancellation({"type": "Entfall"})
    assert is_cancellation({"type": "Fällt aus"})
    assert not is_cancellation({"type": "Vertretung"})
    assert not is_cancellation({"type": None})


def test_day_entry() -> None:
    days = [{"date": "2026-11-10"}, {"date": "2026-11-11"}]
    assert day_entry(days, date(2026, 11, 11)) == {"date": "2026-11-11"}
    assert day_entry(days, date(2026, 11, 12)) is None
    assert day_entry(None, date(2026, 11, 12)) is None


def _lesson(weekday: int, start: str, end: str, subject: str, week: str | None = None) -> dict:
    return {
        "weekday": weekday,
        "start": start,
        "end": end,
        "subject": subject,
        "week": week,
        "room": "A1",
        "teacher": "Becker",
        "period": 1,
        "duration": 1,
    }


# 2026-11-10 is a Tuesday
NOW = datetime(2026, 11, 10, 8, 0, tzinfo=UTC)
TIMETABLE = {
    "currentWeek": "A",
    "lessons": [
        _lesson(2, "07:50", "08:35", "M"),
        _lesson(2, "09:55", "10:40", "D"),
        _lesson(3, "07:50", "08:35", "E", week="A"),
        _lesson(3, "07:50", "08:35", "F", week="B"),
    ],
}


def test_week_alternates() -> None:
    today = NOW.date()
    assert week_of(TIMETABLE, today, today) == "A"
    assert week_of(TIMETABLE, date(2026, 11, 15), today) == "A"  # Sunday, same week
    assert week_of(TIMETABLE, date(2026, 11, 16), today) == "B"
    assert week_of(TIMETABLE, date(2026, 11, 23), today) == "A"
    assert week_of({"currentWeek": None}, today, today) is None


def test_next_lesson_skips_started_lessons() -> None:
    lesson = next_lesson(TIMETABLE, NOW)
    assert lesson is not None
    assert (lesson.subject, lesson.start.hour, lesson.start.minute) == ("D", 9, 55)


def test_next_lesson_uses_the_week_of_the_day() -> None:
    late = NOW.replace(hour=12)
    lesson = next_lesson(TIMETABLE, late)
    assert lesson is not None
    assert lesson.subject == "E"  # Wednesday of week A
    after = next_lesson(TIMETABLE, NOW.replace(day=12, hour=12))  # Thursday: next Tuesday
    assert after is not None and after.subject == "M" and after.start.date() == date(2026, 11, 17)


def test_week_b_lesson_on_next_wednesday() -> None:
    wednesday_next = date(2026, 11, 18)
    lessons = lessons_on(TIMETABLE, wednesday_next, NOW.date(), NOW)
    assert [item.subject for item in lessons] == ["F"]


def test_first_lesson_tomorrow_and_weekend() -> None:
    first = first_lesson_on(TIMETABLE, date(2026, 11, 11), NOW)
    assert first is not None and first.subject == "E"
    assert first_lesson_on(TIMETABLE, date(2026, 11, 14), NOW) is None  # Saturday


def test_no_lessons() -> None:
    assert next_lesson(None, NOW) is None
    assert next_lesson({"currentWeek": None, "lessons": []}, NOW) is None


def test_to_event_timed_and_all_day() -> None:
    timed = to_event(
        {
            "id": "1",
            "title": "Eltern&shy;abend",
            "description": "A<br>B",
            "start": "2026-11-20T16:00:00.000",
            "end": "2026-11-20T19:00:00.000",
            "allDay": False,
            "place": "Aula",
        }
    )
    assert timed is not None
    assert (timed.start.hour, timed.end.hour, timed.location, timed.uid) == (16, 19, "Aula", "1")
    assert timed.description == "A\nB"
    assert timed.start.tzinfo is not None

    all_day = to_event(
        {
            "id": 2,
            "title": "Ferien",
            "start": "2026-11-23T00:00:00.000",
            "end": "2026-11-24T00:00:00.000",
            "allDay": True,
        }
    )
    assert all_day is not None
    assert (all_day.start, all_day.end) == (date(2026, 11, 23), date(2026, 11, 24))

    same_day = to_event(
        {
            "id": 3,
            "title": "x",
            "start": "2026-11-23T00:00:00.000",
            "end": "2026-11-23T00:00:00.000",
            "allDay": True,
        }
    )
    assert same_day is not None and same_day.end == date(2026, 11, 24)
    assert to_event({"title": "no start"}) is None
