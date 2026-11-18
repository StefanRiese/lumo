"""Small helpers: HTML to text, dates."""

from __future__ import annotations

import html
import re
from datetime import date
from typing import Any

_BREAKS = re.compile(r"<\s*br\s*/?\s*>|<\s*/\s*(?:p|div|li|tr)\s*>", re.IGNORECASE)
_TAGS = re.compile(r"<[^>]*>")


def html_to_text(value: str | None) -> str:
    """Portal HTML (`<br>`, `<b>`, links) as plain text; never passes markup on."""
    if not value:
        return ""
    text = html.unescape(_TAGS.sub("", _BREAKS.sub("\n", value)))
    lines = (re.sub(r"[ \t\xa0]+", " ", line).strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def day_entry(days: list[dict[str, Any]] | None, day: date) -> dict[str, Any] | None:
    """The SubstitutionDay of a date, if the plan contains it."""
    for entry in days or []:
        if entry.get("date") == day.isoformat():
            return entry
    return None


def is_cancellation(entry: dict[str, Any]) -> bool:
    """A substitution entry that cancels the lesson („Entfall“, „Fällt aus“)."""
    kind = str(entry.get("type") or "").lower()
    return "entfall" in kind or "fällt aus" in kind or "faellt aus" in kind
