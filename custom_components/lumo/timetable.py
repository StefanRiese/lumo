"""Lessons of the regular timetable on concrete days (A/B weeks, local time)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any


@dataclass(frozen=True)
class LessonInstance:
    subject: str | None
    room: str | None
    teacher: str | None
    start: datetime
    end: datetime


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def week_of(timetable: dict[str, Any], day: date, today: date) -> str | None:
    """`A`/`B` of a date for alternating timetables (`currentWeek` is the week of today)."""
    current = timetable.get("currentWeek")
    if current not in ("A", "B"):
        return None
    weeks = (_monday(day) - _monday(today)).days // 7
    if weeks % 2 == 0:
        return current
    return "B" if current == "A" else "A"


def _hm(text: str) -> time:
    hour, minute = text.split(":")[:2]
    return time(int(hour), int(minute))


def lessons_on(
    timetable: dict[str, Any] | None, day: date, today: date, now: datetime
) -> list[LessonInstance]:
    """Lessons of a date, ordered by start; `now` only provides the time zone."""
    if not timetable:
        return []
    week = week_of(timetable, day, today)
    found: list[LessonInstance] = []
    for lesson in timetable.get("lessons", []):
        if lesson.get("weekday") != day.isoweekday():
            continue
        if week and lesson.get("week") and lesson["week"] != week:
            continue
        try:
            start = datetime.combine(day, _hm(lesson["start"]), tzinfo=now.tzinfo)
            end = datetime.combine(day, _hm(lesson["end"]), tzinfo=now.tzinfo)
        except (KeyError, ValueError, AttributeError):
            continue
        found.append(
            LessonInstance(
                lesson.get("subject"), lesson.get("room"), lesson.get("teacher"), start, end
            )
        )
    return sorted(found, key=lambda item: item.start)


def next_lesson(timetable: dict[str, Any] | None, now: datetime) -> LessonInstance | None:
    """The first lesson that starts after `now` (looks two weeks ahead for holidays)."""
    today = now.date()
    for offset in range(15):
        for lesson in lessons_on(timetable, today + timedelta(days=offset), today, now):
            if lesson.start > now:
                return lesson
    return None


def first_lesson_on(
    timetable: dict[str, Any] | None, day: date, now: datetime
) -> LessonInstance | None:
    lessons = lessons_on(timetable, day, now.date(), now)
    return lessons[0] if lessons else None
