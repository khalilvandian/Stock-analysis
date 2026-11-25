"""The application's operations (issue #60, docs/APPLICATION.md): everything Claude does, as named
calls that are checked and logged (ops_api_call). Claude never writes SQL or files.

    GET    /app/runs/current               the newest run that isn't submitted
    GET    /app/runs/{run_key}             a run, its subjects and what is still missing
    GET    /app/numbers/{subject}          the stored numbers: a symbol, or 'market'
    GET    /app/analyses/{subject}         earlier analyses, newest first
    PUT    /app/runs/{run_key}/analyses/{subject}   save an analysis
    POST   /app/runs/{run_key}/submit      hand the run over to Airflow
    POST   /app/requests                   ask for an extra run, or numbers computed again
    GET    /app/watchlist                  the list, with peers and settings
    GET    /app/watchlist/history          its changes
    PUT    /app/watchlist/{symbol}         add or change a stock
    DELETE /app/watchlist/{symbol}         remove a stock
    POST   /app/watchlist/undo/{change_id} put a stock back as it was before a change
    GET    /app/guide                      the standing guide: what every run must know
    PUT    /app/guide                      a new version (the earlier ones are kept)
    POST   /app/query                      one read-only SELECT, logged

Airflow's run keys contain ':' and '+': clients URL-encode them.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import re
from collections.abc import Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

try:  # deployed beside this file (deploy.yml copies it from src/stock_analysis)
    import notes_check
except ImportError:
    from stock_analysis import notes_check

MARKET, SUMMARIES = "market", "summaries"
GUIDE = "guide"  # its versions in out_note
SECTIONS = {k: v for k, v in notes_check.SECTIONS.items() if k != "stock"}
STOCK_SECTIONS = notes_check.SECTIONS["stock"]
SYMBOL = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
MAX_SECTION = 20_000
MAX_PEERS = 25
LOCK = 60_016  # one watch-list change at a time (pg_advisory_xact_lock)


class Correction(BaseModel):
    """An EPS correction for the report: the stored figures never change."""

    reported: dt.date
    eps: float
    reason: str = Field(min_length=5, max_length=1000)
    source: str = Field(min_length=4, max_length=500)


class Analysis(BaseModel):
    reviewed: dt.date
    sections: dict[str, str]
    corrections: list[Correction] = Field(default_factory=list, max_length=20)


class Submit(BaseModel):
    note: str = Field(default="", max_length=4000)


class RunRequest(BaseModel):
    kind: str = Field(default="analysis", pattern="^(analysis|recompute)$")
    subjects: list[str] = Field(default_factory=list, max_length=60)
    reason: str = Field(min_length=3, max_length=1000)


class Stock(BaseModel):
    """A field left out keeps its value."""

    reason: str = Field(min_length=3, max_length=1000)
    peers: list[str] | None = None
    target_pe: float | None = None
    target_note: str | None = Field(default=None, max_length=2000)
    stakes_per_share: float | None = None


class Reason(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


class Guide(BaseModel):
    text: str = Field(min_length=200, max_length=200_000)
    reason: str = Field(min_length=3, max_length=1000)


class ReadQuery(BaseModel):
    sql: str
    params: dict = Field(default_factory=dict)
    limit: int = 5000


def now() -> dt.datetime:
    return dt.datetime.now(dt.UTC).replace(tzinfo=None, microsecond=0)


def refuse(status: int, detail) -> HTTPException:
    return HTTPException(status_code=status, detail=detail)


def rows(conn: Connection, sql: str, **params) -> list[dict]:
    return [dict(r) for r in conn.execute(text(sql), params).mappings()]


def run_state(conn: Connection, run_key: str, lock: bool = False) -> dict:
    found = rows(
        conn,
        "SELECT * FROM out_analysis_run WHERE run_key = :k" + (" FOR UPDATE" if lock else ""),
        k=run_key,
    )
    if not found:
        raise refuse(404, f"no run {run_key}")
    run = found[0]
    run["subjects"] = json.loads(run.pop("subjects_json"))
    saved = {r["subject"] for r in rows(
        conn, "SELECT subject FROM out_analysis WHERE run_key = :k", k=run_key)}  # fmt: skip
    run["saved"] = [s for s in run["subjects"] if s in saved]
    run["missing"] = [s for s in run["subjects"] if s not in saved]
    return run


def check_analysis(subject: str, body: Analysis, trading_day: dt.date) -> dict[str, str]:
    """The sections in order, or 422 with everything that is wrong."""
    wanted = SECTIONS.get(subject, STOCK_SECTIONS)
    given = {k.strip(): v.strip() for k, v in body.sections.items()}
    wrong = [f"section missing or empty: {s}" for s in wanted if not given.get(s)]
    wrong += [f"unknown section: {s}" for s in given if s not in wanted]
    wrong += [f"section too long: {s}" for s, v in given.items() if len(v) > MAX_SECTION]
    today = now().date()
    if not trading_day <= body.reviewed <= today + dt.timedelta(days=1):
        wrong.append(f"reviewed {body.reviewed} is not between {trading_day} and today")
    if body.corrections and subject in SECTIONS:
        wrong.append("corrections belong to a stock")
    wrong += notes_check.content_problems(notes_check.kind_of(subject), given, body.reviewed)
    days = [c.reported for c in body.corrections]
    if len(days) != len(set(days)):
        wrong.append("two corrections for the same report date")
    wrong += [f"{c.reported}: EPS is not a number" for c in body.corrections
              if not math.isfinite(c.eps)]  # fmt: skip
    if wrong:
        raise refuse(422, wrong)
    return {s: given[s] for s in wanted}


# --- the watch list -------------------------------------------------------------------


def stock_settings(conn: Connection, symbol: str) -> dict | None:
    found = rows(conn, "SELECT * FROM user_watchlist WHERE symbol = :s", s=symbol)
    if not found:
        return None
    stock = found[0]
    stock["peers"] = [r["peer"] for r in rows(
        conn, "SELECT peer FROM user_watchlist_peer WHERE symbol = :s ORDER BY position",
        s=symbol)]  # fmt: skip
    stock["eps_override"] = [
        {"reported": r["reported"].isoformat(), "eps": r["eps"], "reason": r["reason"]}
        for r in rows(
            conn,
            "SELECT reported, eps, reason FROM user_eps_override WHERE symbol = :s "
            "ORDER BY reported",
            s=symbol,
        )
    ]
    return stock


def put_stock(conn: Connection, symbol: str, stock: dict | None) -> None:
    """Replace a stock's rows (None: remove it)."""
    for table in ("user_eps_override", "user_watchlist_peer", "user_watchlist"):
        conn.execute(text(f"DELETE FROM {table} WHERE symbol = :s"), {"s": symbol})
    if stock is None:
        return
    conn.execute(
        text(
            "INSERT INTO user_watchlist (symbol, position, target_pe, target_note, "
            "stakes_per_share) VALUES (:symbol, :position, :target_pe, :target_note, "
            ":stakes_per_share)"
        ),
        {k: stock.get(k) for k in
         ("symbol", "position", "target_pe", "target_note", "stakes_per_share")},
    )  # fmt: skip
    for i, peer in enumerate(stock["peers"], 1):
        conn.execute(
            text("INSERT INTO user_watchlist_peer (symbol, peer, position) VALUES (:s, :p, :i)"),
            {"s": symbol, "p": peer, "i": i},
        )
    for o in stock.get("eps_override", []):
        conn.execute(
            text(
                "INSERT INTO user_eps_override (symbol, reported, eps, reason) "
                "VALUES (:s, :reported, :eps, :reason)"
            ),
            {"s": symbol, **o},
        )


def log_change(conn, by, action, symbol, reason, before, after) -> int:
    return conn.execute(
        text(
            "INSERT INTO user_watchlist_change (at, by, action, symbol, reason, before_json, "
            "after_json) VALUES (:at, :by, :action, :symbol, :reason, :before, :after) "
            "RETURNING change_id"
        ),
        {
            "at": now(), "by": by, "action": action, "symbol": symbol, "reason": reason,
            "before": json.dumps(before) if before else None,
            "after": json.dumps(after) if after else None,
        },
    ).scalar_one()  # fmt: skip


def check_stock(symbol: str, stock: dict) -> None:
    wrong = []
    if not SYMBOL.match(symbol):
        wrong.append(f"not a symbol: {symbol}")
    peers = stock["peers"]
    if not 1 <= len(peers) <= MAX_PEERS:
        wrong.append(f"1 to {MAX_PEERS} peers, got {len(peers)}")
    wrong += [f"not a symbol: {p}" for p in peers if not SYMBOL.match(p)]
    if symbol in peers or len(peers) != len(set(peers)):
        wrong.append("a peer is repeated, or is the stock itself")
    target, stakes = stock.get("target_pe"), stock.get("stakes_per_share")
    if target is not None and (not math.isfinite(target) or not 1 <= target <= 200):
        wrong.append("target_pe must be between 1 and 200, or null for no target")
    if stakes is not None and (not math.isfinite(stakes) or not 0 <= stakes <= 100_000):
        wrong.append("stakes_per_share must be 0 or more")
    if wrong:
        raise refuse(422, wrong)


def router(
    engine: Callable[[str], Engine],
    caller_of: Callable[[str | None], str],
    run_query: Callable[[str, dict, int], dict],
) -> APIRouter:
    """The operations, on app.py's database engines, keys and read-only query."""

    def log_call(caller: str, request: Request, status: int, detail: str | None) -> None:
        with engine("DATABASE_WRITER_URL").begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO ops_api_call (at, caller, operation, status, detail) "
                    "VALUES (:at, :caller, :operation, :status, :detail)"
                ),
                {
                    "at": now(), "caller": caller, "status": status,
                    "operation": f"{request.method} {request.url.path}"[:500],
                    "detail": detail[:4000] if detail else None,
                },
            )  # fmt: skip

    def call(request: Request, x_api_key: str | None = Header(default=None)):
        """Who calls; the call is logged with its result, also when it is refused."""
        caller = caller_of(x_api_key)
        request.state.detail = None
        try:
            yield caller
        except HTTPException as exc:
            log_call(caller, request, exc.status_code, json.dumps(exc.detail))
            raise
        except Exception as exc:
            log_call(caller, request, 500, type(exc).__name__)
            raise
        log_call(caller, request, 200, request.state.detail)

    api = APIRouter(prefix="/app")

    def read() -> Connection:
        return engine("DATABASE_URL").connect()

    def write():
        return engine("DATABASE_WRITER_URL").begin()

    # Runs and analyses ------------------------------------------------------------------
    @api.get("/runs/current")
    def current_run(caller: str = Depends(call)) -> dict:
        with read() as conn:
            found = rows(
                conn,
                "SELECT run_key FROM out_analysis_run WHERE submitted_at IS NULL "
                "ORDER BY opened_at DESC LIMIT 1",
            )
            if not found:
                raise refuse(404, "no open run")
            return run_state(conn, found[0]["run_key"])

    @api.get("/runs/{run_key}")
    def get_run(run_key: str, caller: str = Depends(call)) -> dict:
        with read() as conn:
            run = run_state(conn, run_key)
        run["sections"] = {s: SECTIONS.get(s, STOCK_SECTIONS) for s in run["subjects"]}
        return run

    @api.get("/numbers/{subject}")
    def numbers(subject: str, caller: str = Depends(call)) -> dict:
        if subject == MARKET:
            sql = "SELECT * FROM out_market_numbers ORDER BY as_of DESC LIMIT 1"
        else:
            sql = "SELECT * FROM out_stock_numbers WHERE symbol = :s ORDER BY as_of DESC LIMIT 1"
        with read() as conn:
            found = rows(conn, sql, **({} if subject == MARKET else {"s": subject.upper()}))
        if not found:
            raise refuse(404, f"no stored numbers for {subject}")
        # As text: the stored JSON may hold NaN and Infinity (a ratio of zero debt)
        return {k: (v.isoformat() if isinstance(v, dt.date) else v) for k, v in found[0].items()}

    @api.get("/analyses/{subject}")
    def analyses(
        subject: str, limit: int = Query(default=1, ge=1, le=50), caller: str = Depends(call)
    ) -> list[dict]:
        with read() as conn:
            found = rows(
                conn,
                "SELECT a.*, r.trading_day FROM out_analysis a JOIN out_analysis_run r "
                "USING (run_key) WHERE subject = :s ORDER BY saved_at DESC LIMIT :n",
                s=subject if subject in SECTIONS else subject.upper(),
                n=limit,
            )
        for r in found:
            r["sections"] = json.loads(r.pop("sections_json"))
            r["corrections"] = json.loads(r.pop("corrections_json"))
        return found

    @api.put("/runs/{run_key}/analyses/{subject}")
    def save_analysis(
        run_key: str, subject: str, body: Analysis, caller: str = Depends(call)
    ) -> dict:
        with write() as conn:
            run = run_state(conn, run_key, lock=True)
            if run["submitted_at"]:
                raise refuse(409, "the run is already submitted")
            if subject not in run["subjects"]:
                raise refuse(422, f"{subject} is not in this run: {run['subjects']}")
            sections = check_analysis(subject, body, run["trading_day"])
            corrections = [c.model_dump(mode="json") for c in body.corrections]
            conn.execute(
                text(
                    "INSERT INTO out_analysis (run_key, subject, reviewed, sections_json, "
                    "corrections_json, saved_at, saved_by) VALUES (:k, :s, :r, :j, :c, :t, :b) "
                    "ON CONFLICT (run_key, subject) DO UPDATE SET reviewed = EXCLUDED.reviewed, "
                    "sections_json = EXCLUDED.sections_json, corrections_json = "
                    "EXCLUDED.corrections_json, saved_at = EXCLUDED.saved_at, "
                    "saved_by = EXCLUDED.saved_by"
                ),
                {
                    "k": run_key, "s": subject, "r": body.reviewed, "j": json.dumps(sections),
                    "c": json.dumps(corrections), "t": now(), "b": caller,
                },
            )  # fmt: skip
            return {"saved": subject, "missing": [s for s in run["missing"] if s != subject]}

    @api.post("/runs/{run_key}/submit")
    def submit(run_key: str, body: Submit, caller: str = Depends(call)) -> dict:
        with write() as conn:
            run = run_state(conn, run_key, lock=True)
            if run["missing"]:
                raise refuse(409, f"not saved yet: {', '.join(run['missing'])}")
            if not run["submitted_at"]:  # a second submit changes nothing
                conn.execute(
                    text(
                        "UPDATE out_analysis_run SET submitted_at = :t, submit_note = :n "
                        "WHERE run_key = :k"
                    ),
                    {"t": now(), "n": body.note, "k": run_key},
                )
            return {"submitted": run_key}

    @api.post("/requests")
    def request_run(body: RunRequest, caller: str = Depends(call)) -> dict:
        subjects = [s if s in SECTIONS else s.upper() for s in body.subjects]
        with write() as conn:
            listed = {r["symbol"] for r in rows(conn, "SELECT symbol FROM user_watchlist")}
            unknown = [s for s in subjects if s not in listed | set(SECTIONS)]
            if unknown:
                raise refuse(422, f"not on the watch list: {', '.join(unknown)}")
            request_id = conn.execute(
                text(
                    "INSERT INTO ops_run_request (at, by, kind, subjects_json, reason) "
                    "VALUES (:at, :by, :kind, :subjects, :reason) RETURNING request_id"
                ),
                {
                    "at": now(), "by": caller, "kind": body.kind, "reason": body.reason,
                    "subjects": json.dumps(subjects),
                },
            ).scalar_one()  # fmt: skip
        return {"request_id": request_id}

    # The watch list ---------------------------------------------------------------------
    @api.get("/watchlist")
    def watchlist(caller: str = Depends(call)) -> list[dict]:
        with read() as conn:
            listed = rows(conn, "SELECT symbol FROM user_watchlist ORDER BY position")
            return [stock_settings(conn, r["symbol"]) for r in listed]

    @api.get("/watchlist/history")
    def history(
        symbol: str | None = None,
        limit: int = Query(default=50, ge=1, le=500),
        caller: str = Depends(call),
    ) -> list[dict]:
        with read() as conn:
            found = rows(
                conn,
                "SELECT * FROM user_watchlist_change WHERE CAST(:s AS TEXT) IS NULL "
                "OR symbol = CAST(:s AS TEXT) ORDER BY change_id DESC LIMIT :n",
                s=symbol.upper() if symbol else None,
                n=limit,
            )
        for r in found:
            for side in ("before", "after"):
                value = r.pop(f"{side}_json")
                r[side] = json.loads(value) if value else None
        return found

    @api.put("/watchlist/{symbol}")
    def set_stock(symbol: str, body: Stock, caller: str = Depends(call)) -> dict:
        symbol = symbol.upper()
        with write() as conn:
            conn.execute(text("SELECT pg_advisory_xact_lock(:n)"), {"n": LOCK})
            before = stock_settings(conn, symbol)
            last = rows(conn, "SELECT COALESCE(MAX(position), 0) AS n FROM user_watchlist")
            base = before or {
                "symbol": symbol, "position": last[0]["n"] + 1, "target_pe": None,
                "target_note": None, "stakes_per_share": None, "peers": [], "eps_override": [],
            }  # fmt: skip
            given = body.model_dump(exclude_unset=True, exclude={"reason"})
            if given.get("peers") is not None:
                given["peers"] = [p.upper() for p in given["peers"]]
            else:
                given.pop("peers", None)
            after = {**base, **given}
            check_stock(symbol, after)
            if after == before:
                return {"changed": False, "stock": after}
            put_stock(conn, symbol, after)
            action = "change" if before else "add"
            change = log_change(conn, caller, action, symbol, body.reason, before, after)
            known = rows(conn, "SELECT 1 FROM core_company WHERE symbol = :s", s=symbol)
        answer = {"changed": True, "change_id": change, "stock": after}
        if not known:
            answer["warning"] = (
                f"{symbol} is not in the database yet: the next ingest fetches it. If it finds "
                "nothing, check that the symbol exists."
            )
        return answer

    @api.delete("/watchlist/{symbol}")
    def remove_stock(symbol: str, body: Reason, caller: str = Depends(call)) -> dict:
        symbol = symbol.upper()
        with write() as conn:
            conn.execute(text("SELECT pg_advisory_xact_lock(:n)"), {"n": LOCK})
            before = stock_settings(conn, symbol)
            if before is None:
                raise refuse(404, f"{symbol} is not on the watch list")
            put_stock(conn, symbol, None)
            change = log_change(conn, caller, "remove", symbol, body.reason, before, None)
        return {"changed": True, "change_id": change}

    @api.post("/watchlist/undo/{change_id}")
    def undo(change_id: int, body: Reason, caller: str = Depends(call)) -> dict:
        with write() as conn:
            conn.execute(text("SELECT pg_advisory_xact_lock(:n)"), {"n": LOCK})
            found = rows(
                conn, "SELECT * FROM user_watchlist_change WHERE change_id = :c", c=change_id
            )
            if not found:
                raise refuse(404, f"no change {change_id}")
            symbol, old = found[0]["symbol"], found[0]["before_json"]
            newer = rows(
                conn,
                "SELECT change_id FROM user_watchlist_change WHERE symbol = :s AND change_id > :c",
                s=symbol,
                c=change_id,
            )
            if newer:
                raise refuse(409, f"{symbol} changed again since: undo change "
                             f"{max(r['change_id'] for r in newer)} first")  # fmt: skip
            before, after = stock_settings(conn, symbol), json.loads(old) if old else None
            put_stock(conn, symbol, after)
            change = log_change(conn, caller, "undo", symbol, body.reason, before, after)
        return {"changed": True, "change_id": change, "stock": after}

    # The standing guide -----------------------------------------------------------------
    def newest_guide(conn: Connection) -> dict | None:
        found = rows(
            conn,
            "SELECT updated_at, text, source FROM out_note WHERE subject = :s "
            "ORDER BY updated_at DESC LIMIT 1",
            s=GUIDE,
        )
        return found[0] if found else None

    @api.get("/guide")
    def get_guide(caller: str = Depends(call)) -> dict:
        with read() as conn:
            guide = newest_guide(conn)
        if guide is None:
            raise refuse(404, "no guide yet")
        return guide

    @api.put("/guide")
    def put_guide(body: Guide, request: Request, caller: str = Depends(call)) -> dict:
        request.state.detail = body.reason
        with write() as conn:
            conn.execute(text("SELECT pg_advisory_xact_lock(:n)"), {"n": LOCK})
            before = newest_guide(conn)
            if before and before["text"] == body.text:
                return {"changed": False, "length": len(body.text)}
            if before and len(body.text) < len(before["text"]) / 2:
                raise refuse(422, "shorter than half the present guide: send the whole text")
            at = now()
            if before and before["updated_at"] >= at:  # one version a second
                at = before["updated_at"] + dt.timedelta(seconds=1)
            conn.execute(
                text(
                    "INSERT INTO out_note (subject, updated_at, text, source) "
                    "VALUES (:s, :at, :text, :source)"
                ),
                {"s": GUIDE, "at": at, "text": body.text,
                 "source": f"{caller}: {body.reason}"},
            )  # fmt: skip
        return {"changed": True, "length": len(body.text)}

    # Ad hoc reads -----------------------------------------------------------------------
    @api.post("/query")
    def query(body: ReadQuery, request: Request, caller: str = Depends(call)) -> dict:
        request.state.detail = body.sql
        return run_query(body.sql, body.params, body.limit)

    return api
