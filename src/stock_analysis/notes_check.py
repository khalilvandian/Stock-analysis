"""Checks that Claude's notes are current, sourced and free of events that have passed.

The numbers in the evening run are computed by code; the words (analyses/*/notes.md) are
written by Claude each run. Nothing else checks the words, so this module does
(docs/EVENING_RUN.md, "The notes"):

1. `Updated:` is the run's date.
2. Every required section is present and carries `<!-- reviewed YYYY-MM-DD -->` with the
   run's date: Claude re-read it and rewrote or confirmed it for this run. Text kept from
   an earlier run without a review is how stale text got into the reports (the US midterm
   elections were still described as coming two weeks after they happened).
3. News: each item starts with its date (`- YYYY-MM-DD:`), newest first, none after the
   run, at most MAX_NEWS items, and every item from FORMAT_START on links its source. A
   price move is not news (it goes in "Today").
4. What to watch: every item names a date on or after the run (or a month not yet over),
   or is marked "(ongoing)".
5. Nowhere outside News does a sentence speak of a past date as coming ("ahead of",
   "upcoming", "this week brings", "will report"...).
6. The market notes end with a Sources section of at least MIN_SOURCES links.

`problems(kind, text, run_date)` returns the failures as plain sentences; an empty list
means the notes pass. The application refuses an analysis with failures
(api/operations.py, content_problems).
"""

from __future__ import annotations

import re
from datetime import date, timedelta

FORMAT_START = date(2026, 11, 19)  # news from this date on must link its source
MAX_NEWS = 10
MIN_SOURCES = 3

SECTIONS = {
    "stock": ["Verdict", "Today", "Summary", "Business", "Risks", "News", "What to watch"],
    "market": [
        "Verdict",
        "Summary",
        "What happened",
        "Why it happened",
        "What it means",
        "Stocks to look at",
        "What to watch",
        "Sources",
    ],
    "summaries": ["Verdict", "Analysis"],
}

REVIEWED = re.compile(r"<!--\s*reviewed\s+(\d{4}-\d{2}-\d{2})\s*-->", re.I)
LINK = re.compile(r"\[[^\]]+\]\(https?://[^)\s]+\)|<https?://[^>\s]+>")
ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for m in names
}
_MON = "|".join(sorted(MONTHS, key=len, reverse=True))
DAY_DATE = re.compile(rf"\b({_MON})\.? (\d{{1,2}})(?:st|nd|rd|th)?(?:,? (\d{{4}}))?\b", re.I)
MONTH_DATE = re.compile(rf"\b({_MON})\.? (\d{{4}})\b", re.I)
PART_MONTH = re.compile(rf"\b(?:early|mid|late)[- ]({_MON})\b", re.I)
FUTURE_WORDS = re.compile(
    r"\b(ahead of|upcoming|coming up|this week brings|next week brings|will report|"
    r"reports? (?:on|tonight|tomorrow)|is due|are due|due on|tonight|tomorrow|"
    r"before (?:the|its|their) (?:results|report|vote|election|meeting))\b",
    re.I,
)


def kind_of(subject: str) -> str:
    return subject if subject in ("market", "summaries") else "stock"


def split(text: str) -> tuple[str, dict[str, str]]:
    """(updated, {section: raw text}) of a notes.md, review markers included."""
    m = re.search(r"^Updated:\s*(.+)$", text, re.M)
    parts = re.split(r"^## +(.+)$", text, flags=re.M)
    sections = {parts[i].strip(): parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}
    return (m.group(1).strip() if m else ""), sections


def strip_markers(text: str) -> str:
    return REVIEWED.sub("", text).strip()


def dates_in(text: str, run: date) -> list[tuple[date, bool]]:
    """Dates named in the text as (date, month_only). A day without a year is taken in the
    run's year, or the next one if that would put it more than 60 days in the past."""
    out = []
    for y, mo, d in ISO.findall(text):
        try:
            out.append((date(int(y), int(mo), int(d)), False))
        except ValueError:
            pass
    rest = ISO.sub(" ", text)
    for mon, d, y in DAY_DATE.findall(rest):
        try:
            when = date(int(y) if y else run.year, MONTHS[mon.lower()], int(d))
        except ValueError:
            continue
        if not y and when < run - timedelta(days=60):
            when = when.replace(year=when.year + 1)
        out.append((when, False))
    rest = DAY_DATE.sub(" ", rest)
    for mon, y in MONTH_DATE.findall(rest):
        out.append((date(int(y), MONTHS[mon.lower()], 1), True))
    for mon in PART_MONTH.findall(MONTH_DATE.sub(" ", rest)):  # "late January": the next one
        when = date(run.year, MONTHS[mon.lower()], 1)
        if when.month < run.month:
            when = when.replace(year=run.year + 1)
        out.append((when, True))
    return out


def bullets(text: str) -> list[str]:
    items, cur = [], None
    for line in strip_markers(text).splitlines():
        if re.match(r"^\s*[-*] ", line):
            if cur is not None:
                items.append(cur)
            cur = re.sub(r"^\s*[-*] ", "", line).strip()
        elif cur is not None and line.strip():
            cur += " " + line.strip()
    if cur is not None:
        items.append(cur)
    return items


def sentences(text: str) -> list[str]:
    flat = re.sub(r"\s+", " ", LINK.sub("", strip_markers(text)))
    return [s for s in re.split(r"(?<=[.!?;])\s+|\s+-\s+", flat) if s.strip()]


def check_news(text: str, run: date) -> list[str]:
    out, prev = [], None
    items = bullets(text)
    if len(items) > MAX_NEWS:
        out.append(f"News has {len(items)} items; keep the newest {MAX_NEWS}")
    for item in items:
        m = re.match(r"^(\d{4}-\d{2}-\d{2})", item)
        if not m:
            out.append(f"News item without a date at the start: {item[:60]!r}")
            continue
        when = date.fromisoformat(m.group(1))
        if when > run:
            out.append(f"News item dated after the run ({when}): {item[:60]!r}")
        if prev is not None and when > prev:
            out.append(f"News not newest first: {when} comes after {prev}")
        if when >= FORMAT_START and not LINK.search(item):
            out.append(f"News item from {when} has no source link: {item[:60]!r}")
        prev = when
    return out


def check_watch(text: str, run: date) -> list[str]:
    out = []
    for item in bullets(text):
        if "(ongoing)" in item.lower():
            continue
        found = dates_in(item, run)
        if not found:
            out.append(f"What to watch item has no date (or '(ongoing)'): {item[:60]!r}")
            continue
        past = [
            d
            for d, month_only in found
            if (d.replace(day=28) + timedelta(days=4)).replace(day=1) <= run
            or (not month_only and d < run)
        ]
        if past:
            out.append(f"What to watch item names a past date ({past[0]}): {item[:60]!r}")
    return out


def check_past_as_future(name: str, text: str, run: date) -> list[str]:
    out = []
    for s in sentences(text):
        if not FUTURE_WORDS.search(s):
            continue
        past = [d for d, month_only in dates_in(s, run) if not month_only and d < run]
        if past:
            out.append(f"{name} speaks of {past[0]} as still to come: {s[:80]!r}")
    return out


def problems(kind: str, text: str, run: date) -> list[str]:
    updated, sections = split(text)
    out = []
    if updated[:10] != run.isoformat():
        out.append(f"Updated: is {updated or 'missing'}, not {run}")
    for name in SECTIONS[kind]:
        if name not in sections:
            out.append(f"section '{name}' is missing")
            continue
        body = sections[name]
        seen = REVIEWED.findall(body)
        if not seen:
            out.append(f"section '{name}' has no <!-- reviewed {run} --> marker")
        elif max(seen) != run.isoformat():
            out.append(f"section '{name}' was last reviewed {max(seen)}, not {run}")
        if not strip_markers(body):
            out.append(f"section '{name}' is empty")
    return out + content_problems(kind, sections, run)


def content_problems(kind: str, sections: dict[str, str], run: date) -> list[str]:
    """Rules 3 to 6: what the sections say."""
    out = []
    for name, body in sections.items():
        if name == "News":
            out += check_news(body, run)
        elif name == "What to watch":
            out += check_watch(body, run)
        if name not in ("News", "Sources"):
            out += check_past_as_future(name, body, run)
    if kind == "market" and "Sources" in sections:
        n = len(LINK.findall(sections["Sources"]))
        if n < MIN_SOURCES:
            out.append(f"Sources has {n} links; at least {MIN_SOURCES} are needed")
    return out
