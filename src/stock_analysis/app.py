"""The application's client (issue #60, docs/APPLICATION.md): what Claude uses to read the numbers,
save its analyses and edit the watch list. Every command is one operation of the web API
(api/operations.py); answers are JSON.

    python -m stock_analysis.app run [RUN_KEY]             # a run (default: the open one)
    python -m stock_analysis.app numbers market|SYMBOL
    python -m stock_analysis.app analyses SUBJECT [--limit N]
    python -m stock_analysis.app save RUN_KEY SUBJECT FILE.json
    python -m stock_analysis.app submit RUN_KEY [--note TEXT]
    python -m stock_analysis.app request analysis|recompute [SUBJECT ...] --reason TEXT
    python -m stock_analysis.app watchlist
    python -m stock_analysis.app watchlist-history [SYMBOL]
    python -m stock_analysis.app watchlist-set SYMBOL --reason TEXT [--target-pe X | --no-target]
        [--peers A B ...] [--target-note TEXT] [--stakes X]
    python -m stock_analysis.app watchlist-remove SYMBOL --reason TEXT
    python -m stock_analysis.app watchlist-undo CHANGE_ID --reason TEXT
    python -m stock_analysis.app recipients                # who gets the reports (STOCK_API_KEY)
    python -m stock_analysis.app recipient-add EMAIL --reason TEXT [--name NAME]
    python -m stock_analysis.app recipient-remove EMAIL --reason TEXT
    python -m stock_analysis.app guide                     # what every run must know
    python -m stock_analysis.app guide-set FILE.md --reason TEXT
    python -m stock_analysis.app query "SELECT ..."

FILE.json: {"reviewed": "YYYY-MM-DD", "sections": {"Verdict": "...", ...}, "corrections":
[{"reported": "YYYY-MM-DD", "eps": 1.23, "reason": "...", "source": "..."}]}.

Settings: STOCK_API_URL (default: the deployed API) and CLAUDE_API_KEY, else STOCK_API_KEY; in
Claude's cloud environment the network attaches the key. A refusal prints why and exits 1.
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
from pathlib import Path
from urllib.parse import quote

import httpx

API_URL = "https://stock-api-bk.azurewebsites.net"


class Refused(RuntimeError):
    """The application answered with an error; the message says what is wrong."""


class App:
    def __init__(self, url: str | None = None, key: str | None = None, client=None):
        if client is None:
            key = key or os.environ.get("CLAUDE_API_KEY") or os.environ.get("STOCK_API_KEY")
            client = httpx.Client(
                base_url=(url or os.environ.get("STOCK_API_URL") or API_URL).rstrip("/"),
                headers={"X-API-Key": key} if key else {},
                timeout=120,
                verify=os.environ.get("SSL_CERT_FILE") or ssl.create_default_context(),
            )
        self.client = client

    def call(self, method: str, path: str, body: dict | None = None, **params):
        params = {k: v for k, v in params.items() if v is not None}
        answer = self.client.request(method, f"/app/{path}", json=body, params=params)
        if answer.status_code != 200:
            try:
                detail = answer.json().get("detail", answer.text)
            except ValueError:
                detail = answer.text
            lines = detail if isinstance(detail, list) else [detail]
            raise Refused(f"{answer.status_code}: " + "; ".join(str(x) for x in lines))
        return answer.json()

    def run(self, run_key: str = "current"):
        return self.call("GET", f"runs/{quote(run_key, safe='')}")

    def numbers(self, subject: str):
        answer = self.call("GET", f"numbers/{subject}")
        answer["payload"] = json.loads(answer.pop("payload_json"))
        return answer

    def analyses(self, subject: str, limit: int = 1):
        return self.call("GET", f"analyses/{subject}", limit=limit)

    def save(self, run_key: str, subject: str, analysis: dict):
        return self.call("PUT", f"runs/{quote(run_key, safe='')}/analyses/{subject}", analysis)

    def submit(self, run_key: str, note: str = ""):
        return self.call("POST", f"runs/{quote(run_key, safe='')}/submit", {"note": note})

    def request(self, kind: str, subjects: list[str], reason: str):
        body = {"kind": kind, "subjects": subjects, "reason": reason}
        return self.call("POST", "requests", body)

    def watchlist(self):
        return self.call("GET", "watchlist")

    def watchlist_history(self, symbol: str | None = None):
        return self.call("GET", "watchlist/history", symbol=symbol)

    def watchlist_set(self, symbol: str, reason: str, **fields):
        return self.call("PUT", f"watchlist/{symbol}", {"reason": reason, **fields})

    def watchlist_remove(self, symbol: str, reason: str):
        return self.call("DELETE", f"watchlist/{symbol}", {"reason": reason})

    def watchlist_undo(self, change_id: int, reason: str):
        return self.call("POST", f"watchlist/undo/{change_id}", {"reason": reason})

    def recipients(self):
        return self.call("GET", "recipients")

    def recipient_add(self, email: str, reason: str, name: str | None = None):
        return self.call("PUT", "recipients", {"email": email, "reason": reason, "name": name})

    def recipient_remove(self, email: str, reason: str):
        return self.call("DELETE", "recipients", {"email": email, "reason": reason})

    def guide(self):
        return self.call("GET", "guide")

    def guide_set(self, text: str, reason: str):
        return self.call("PUT", "guide", {"text": text, "reason": reason})

    def query(self, sql: str, limit: int = 5000):
        return self.call("POST", "query", {"sql": sql, "limit": limit})


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="stock_analysis.app")
    sub = ap.add_subparsers(dest="command", required=True)
    add = sub.add_parser
    p = add("run")
    p.add_argument("run_key", nargs="?", default="current")
    p = add("numbers")
    p.add_argument("subject")
    p = add("analyses")
    p.add_argument("subject")
    p.add_argument("--limit", type=int, default=1)
    p = add("save")
    p.add_argument("run_key")
    p.add_argument("subject")
    p.add_argument("file", type=Path)
    p = add("submit")
    p.add_argument("run_key")
    p.add_argument("--note", default="")
    p = add("request")
    p.add_argument("kind", choices=["analysis", "recompute"])
    p.add_argument("subjects", nargs="*")
    p.add_argument("--reason", required=True)
    add("watchlist")
    p = add("watchlist-history")
    p.add_argument("symbol", nargs="?")
    p = add("watchlist-set")
    p.add_argument("symbol")
    p.add_argument("--reason", required=True)
    target = p.add_mutually_exclusive_group()
    target.add_argument("--target-pe", type=float)
    target.add_argument("--no-target", action="store_true")
    p.add_argument("--peers", nargs="+")
    p.add_argument("--target-note")
    p.add_argument("--stakes", type=float, dest="stakes_per_share")
    p = add("watchlist-remove")
    p.add_argument("symbol")
    p.add_argument("--reason", required=True)
    p = add("watchlist-undo")
    p.add_argument("change_id", type=int)
    p.add_argument("--reason", required=True)
    add("recipients")
    p = add("recipient-add")
    p.add_argument("email")
    p.add_argument("--reason", required=True)
    p.add_argument("--name")
    p = add("recipient-remove")
    p.add_argument("email")
    p.add_argument("--reason", required=True)
    add("guide")
    p = add("guide-set")
    p.add_argument("file", type=Path)
    p.add_argument("--reason", required=True)
    p = add("query")
    p.add_argument("sql")
    return ap


def main(argv: list[str] | None = None, app: App | None = None) -> int:
    args = vars(parser().parse_args(argv))
    command = args.pop("command").replace("-", "_")
    if command == "save":
        args["analysis"] = json.loads(args.pop("file").read_text(encoding="utf-8"))
    if command == "guide_set":
        args["text"] = args.pop("file").read_text(encoding="utf-8")
    if command == "watchlist_set":
        no_target = args.pop("no_target")
        args = {k: v for k, v in args.items() if v is not None}
        if no_target:
            args["target_pe"] = None  # sent as null: no target, no entry price
    # The recipients are Babak's: Claude's key is refused, so the scripts' key is used
    key = os.environ.get("STOCK_API_KEY") if command.startswith("recipient") else None
    try:
        answer = getattr(app or App(key=key), command)(**args)
    except Refused as exc:
        print(exc, file=sys.stderr)
        return 1
    if command == "guide":
        print(answer["text"])
    else:
        print(json.dumps(answer, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    from dotenv import load_dotenv

    from .db import ROOT

    load_dotenv(ROOT / ".env")
    if hasattr(sys.stdout, "reconfigure"):  # a Windows console may not be UTF-8
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
