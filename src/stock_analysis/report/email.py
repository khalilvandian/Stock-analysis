"""Email a run's reports, once, through Brevo, with every PDF attached.

Brevo (brevo.com, free: 300 emails a day) delivers to any recipient once the sender address
is verified in Brevo. Settings, from the environment (never commit them; this repository is
public):
    BREVO_API_KEY         Brevo API key (xkeysib-...). Turn off Brevo's "authorized IPs"
                          blocking, since the job's address changes.
    WATCHLIST_EMAIL_FROM  sender, "Name <address>", verified in the Brevo account.
    WATCHLIST_EMAIL_TO    recipients, comma separated, up to 5.

A run is emailed once: it is marked before the call. The mark is taken back only when Brevo
refused the email; after a call without an answer it stays, since the email may have gone out.
"""

from __future__ import annotations

import base64
import html
import os
from email.utils import parseaddr
from pathlib import PurePosixPath

import httpx

from ..data import now_utc

API = "https://api.brevo.com/v3/smtp/email"
MAX_RECIPIENTS = 5


class Refused(RuntimeError):
    """Brevo answered that it did not take the email."""


def attachment_name(path: str) -> str:
    """BSX/2026-10-27_2100.pdf -> BSX_2026-10-27_2100.pdf"""
    p = PurePosixPath(path)
    return f"{p.parent.name}_{p.name}"


def recipients(to: str) -> list[str]:
    """'a@x.com, b@y.com' -> ['a@x.com', 'b@y.com']"""
    out = [a.strip() for a in to.split(",") if a.strip()]
    if not out:
        raise ValueError("No recipient")
    if len(out) > MAX_RECIPIENTS:
        raise ValueError(f"At most {MAX_RECIPIENTS} recipients, got {len(out)}")
    return out


def notices(report: dict) -> str:
    """What must be read first: Claude's note on the run, and failed data checks."""
    parts = []
    if report.get("note"):
        parts.append(f"<p><b>Claude's note on this run:</b> {html.escape(report['note'])}</p>")
    if report.get("checks"):
        items = "".join(f"<li>{html.escape(c)}</li>" for c in report["checks"])
        parts.append(f"<p><b>Failed checks:</b></p><ul>{items}</ul>")
    return "".join(parts)


def build_message(report: dict, store, to: str, sender: str) -> dict:
    """The run's email in Brevo's transactional email format, every PDF attached."""
    name, address = parseaddr(sender)
    return {
        "sender": {"email": address, "name": name} if name else {"email": address},
        "to": [{"email": a} for a in recipients(to)],
        "subject": report["subject"],
        "htmlContent": notices(report) + report["html"],
        "attachment": [
            {"name": attachment_name(f), "content": base64.b64encode(store.get(f)).decode()}
            for f in report["files"]
        ],
    }


def send(message: dict, key: str) -> str | None:
    r = httpx.post(
        API,
        json=message,
        headers={"api-key": key, "accept": "application/json"},
        timeout=60,
    )
    if 400 <= r.status_code < 500:
        raise Refused(f"Brevo refused the email ({r.status_code}): {r.text}")
    if r.status_code >= 300:
        raise RuntimeError(f"Brevo failed ({r.status_code}): {r.text}")
    return r.json().get("messageId")


def send_run(data, run: dict, store) -> str:
    """Email the run's report unless it was emailed already; returns what happened."""
    key = os.environ.get("BREVO_API_KEY", "").strip()
    sender = os.environ.get("WATCHLIST_EMAIL_FROM", "").strip()
    to = os.environ.get("WATCHLIST_EMAIL_TO", "").strip()
    wanted = {"BREVO_API_KEY": key, "WATCHLIST_EMAIL_FROM": sender, "WATCHLIST_EMAIL_TO": to}
    if unset := [n for n, v in wanted.items() if not v]:
        raise RuntimeError(f"Not set: {', '.join(unset)}")
    if not run.get("report"):
        raise RuntimeError(f"Run {run['run_key']} is not rendered")
    message = build_message(run["report"], store, to, sender)  # before the mark: may fail
    run_key = {"k": run["run_key"]}
    marked = data.write_steps(
        [
            (
                "UPDATE out_analysis_run SET emailed_at = :t "
                "WHERE run_key = :k AND emailed_at IS NULL",
                [{"t": now_utc(), **run_key}],
            )
        ]
    )[0]
    if not marked:
        return f"Run {run['run_key']} was emailed already"
    try:
        sent = send(message, key)
    except Refused:
        data.write_steps(
            [("UPDATE out_analysis_run SET emailed_at = NULL WHERE run_key = :k", [run_key])]
        )
        raise
    return f"Sent {len(message['attachment'])} PDFs: {sent}"
