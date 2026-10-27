import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "analysis"))
import watchlist  # noqa: E402


def _dates(rows: list[tuple[str, float | None]]) -> pd.DataFrame:
    idx = pd.to_datetime([d for d, _ in rows]).tz_localize("America/New_York")
    return pd.DataFrame({"EPS Estimate": 1.0, "Reported EPS": [e for _, e in rows]}, index=idx)


def test_config_has_what_each_stock_needs():
    cfg = watchlist.load_watchlist()
    assert cfg["stock"], "the watch list is empty"
    for s in cfg["stock"]:
        assert s["symbol"].isupper() and s["peers"] and s["target_pe"] > 0


def test_quarterly_eps_drops_duplicates_and_applies_overrides():
    d = _dates(
        [
            ("2026-01-20", 1.0),
            ("2026-01-20", 1.0),  # same report listed twice
            ("2026-04-16", 9.0),  # one-off, overridden below
            ("2026-07-16", 1.2),
            ("2026-10-20", 1.3),
            ("2027-01-19", None),  # future report
        ]
    )
    q = watchlist.quarterly_eps(d, [{"reported": "2026-04-16", "eps": 1.1}])
    assert list(q.round(2)) == [1.0, 1.1, 1.2, 1.3]
    assert watchlist.trailing_eps(q).iloc[-1] == 4.6


def test_trailing_eps_needs_four_consecutive_quarters():
    q = pd.Series(
        [1.0, 1.0, 1.0, 1.0],
        index=pd.to_datetime(["2020-01-20", "2020-04-20", "2022-07-20", "2022-10-20"]),
    )
    assert watchlist.trailing_eps(q).empty


def test_yearly_pe_uses_eps_at_the_q4_report_and_average_price():
    days = pd.bdate_range("2024-01-01", "2026-06-30")
    prices = pd.Series(100.0, index=days)
    ttm = pd.Series(
        [4.0, 5.0], index=pd.to_datetime(["2025-02-10", "2026-02-10"])
    )  # FY2024 and FY2025 EPS
    y = watchlist.yearly_pe(prices, ttm)
    assert y.loc[2024, "pe"] == 25.0
    assert y.loc[2025, "pe"] == 20.0


def test_split_adjust_rescales_pre_split_eps_and_shares():
    hist = pd.DataFrame(
        {
            "symbol": "X",
            "fiscal_year_end": pd.to_datetime(["2024-12-31"] * 2 + ["2026-12-31"] * 2),
            "column": ["_shares", "eps", "_shares", "eps"],
            "value": [40.0, 100.0, 1000.0, 4.0],
        }
    )
    splits = pd.Series([25.0], index=pd.to_datetime(["2025-06-01"]).tz_localize("UTC"))
    out = watchlist.split_adjust(hist, splits, shares_now=1000.0)
    assert list(out["value"]) == [1000.0, 4.0, 1000.0, 4.0]


def test_notes_sections_and_first_sentence(tmp_path, monkeypatch):
    monkeypatch.setattr(watchlist, "OUT", tmp_path)
    (tmp_path / "X").mkdir()
    (tmp_path / "X/notes.md").write_text(
        "# X\n\nUpdated: 2026-10-27\n\n## Verdict\n\n**Cheap. Buy below $10.**\n\n## Risks\n\n- a\n"
    )
    updated, notes = watchlist.read_notes("X")
    assert updated == "2026-10-27"
    assert notes["Risks"] == "- a"
    assert watchlist.first_sentence(notes["Verdict"]) == "Cheap."


def test_new_pdf_never_overwrites(tmp_path):
    first = watchlist.new_pdf(tmp_path, "2026-10-27_2100")
    first.write_bytes(b"x")
    assert watchlist.new_pdf(tmp_path, "2026-10-27_2100").name == "2026-10-27_2100-2.pdf"


def test_formatting():
    assert watchlist.times(np.nan) == "–"
    assert watchlist.pct(-0.0712) == "-7.1%"


def test_email_attaches_every_pdf_and_sends_once(tmp_path, monkeypatch):
    import httpx
    import respx
    import send_email

    (tmp_path / "analyses/BSX").mkdir(parents=True)
    (tmp_path / "analyses/BSX/2026-10-27_2100.pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / "email.html").write_text("<p>hi</p>")
    monkeypatch.setattr(send_email, "ROOT", tmp_path)
    run = {"subject": "S", "html": "email.html", "files": ["analyses/BSX/2026-10-27_2100.pdf"]}
    msg = send_email.build_message(run, "to@example.com", send_email.SENDER, test=True)
    assert msg["to"] == ["to@example.com"] and msg["subject"] == "[Test] S"
    assert msg["attachments"][0]["filename"] == "BSX_2026-10-27_2100.pdf"
    with respx.mock:
        route = respx.post(send_email.API).mock(return_value=httpx.Response(200, json={"id": "e1"}))
        assert send_email.send(msg, "key")["id"] == "e1"
        assert route.calls[0].request.headers["Authorization"] == "Bearer key"
