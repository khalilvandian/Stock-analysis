"""Claude's notes: current, sourced, no past events spoken of as coming (notes_check)."""

from datetime import date

from stock_analysis import notes_check as n

RUN = date(2026, 11, 19)
R = "<!-- reviewed 2026-11-19 -->"


def notes(sections: dict[str, str], updated: str = "2026-11-19") -> str:
    body = "\n\n".join(f"## {k}\n\n{v}" for k, v in sections.items())
    return f"# X\n\nUpdated: {updated}\n\n{body}\n"


def stock(**over) -> str:
    s = {
        "Verdict": f"{R}\n**Cheap.**",
        "Today": f"{R}\nThe stock fell 2% with the market.",
        "Summary": f"{R}\n- cheap",
        "Business": f"{R}\nTravel.",
        "Risks": f"{R}\nAI agents.",
        "News": f"{R}\n- 2026-11-18: results ([Reuters](https://reuters.com/a)).\n"
        "- 2026-11-03: Q3 beat.",
        "What to watch": f"{R}\n- Q4 results on 2027-02-24.\n- AI traffic (ongoing).",
    }
    s.update(over)
    return notes(s)


def test_current_sourced_notes_pass():
    assert n.problems("stock", stock(), RUN) == []


def test_a_section_kept_from_an_earlier_run_fails():
    old = stock(Risks="<!-- reviewed 2026-11-04 -->\nAI agents.")
    assert any("last reviewed 2026-11-04" in p for p in n.problems("stock", old, RUN))
    assert any("Updated:" in p for p in n.problems("stock", notes({}, "2026-11-04"), RUN))


def test_news_needs_dates_order_and_a_source_link():
    bad = stock(News=f"{R}\n- 2026-11-18: rose 2%.\n- 2026-11-19: later.\n- no date")
    found = n.problems("stock", bad, RUN)
    assert any("no source link" in p for p in found)
    assert any("not newest first" in p for p in found)
    assert any("without a date" in p for p in found)


def test_watch_items_must_be_still_to_come():
    bad = stock(**{"What to watch": f"{R}\n- The midterms (Nov 3).\n- Margins."})
    found = n.problems("stock", bad, RUN)
    assert any("past date (2026-11-03)" in p for p in found)
    assert any("no date" in p for p in found)
    ok = stock(**{"What to watch": f"{R}\n- Results in late January.\n- Jan 19 report."})
    assert n.problems("stock", ok, RUN) == []


def test_a_past_event_described_as_coming_fails():
    bad = stock(Today=f"{R}\nThis week brings the US midterm elections (Nov 3).")
    assert any("as still to come" in p for p in n.problems("stock", bad, RUN))


def test_market_needs_its_sections_and_sources():
    found = n.problems("market", notes({"Verdict": f"{R}\nCalm."}), RUN)
    assert any("'What happened' is missing" in p for p in found)
    assert any("'Sources' is missing" in p for p in found)


def test_dates_without_a_year_roll_into_next_year():
    assert (date(2027, 1, 19), False) in n.dates_in("report on Jan 19", RUN)
    assert (date(2026, 11, 3), False) in n.dates_in("on Nov 3", RUN)
