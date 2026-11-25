"""Email a run's reports through Brevo, every PDF attached: one email per person, so nobody sees
the others' addresses and a bad address stops nobody else's.

Who gets it is in the database (user_report_recipient), edited through the application
(`python -m claude app recipients`, `recipient-add`, `recipient-remove`).
Brevo (brevo.com, free: 300 emails a day) delivers to any recipient once the sender address
is verified in Brevo. Settings, from the environment (never commit them; this repository is
public):
    BREVO_API_KEY         Brevo API key (xkeysib-...). Turn off Brevo's "authorized IPs"
                          blocking, since the job's address changes.
    WATCHLIST_EMAIL_FROM  sender, "Name <address>", verified in the Brevo account.

Each person gets a run once: out_report_email is marked before the call. The mark is taken back
only when Brevo refused the email; after a call without an answer it stays, since the email may
have gone out. A repeated step emails only those without a mark.
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


class Refused(RuntimeError):
    """Brevo answered that it did not take the email."""


def attachment_name(path: str) -> str:
    """BSX/2026-10-27_2100.pdf -> BSX_2026-10-27_2100.pdf"""
    p = PurePosixPath(path)
    return f"{p.parent.name}_{p.name}"


def recipients(data) -> list[dict]:
    """Who gets the reports: [{"email", "name"}]"""
    found = data.sql(
        "SELECT email, name FROM user_report_recipient WHERE active ORDER BY changed_at, email"
    )
    return [{k: v for k, v in r.items() if isinstance(v, str)} for r in found.to_dict("records")]


def masked(email: str) -> str:
    """'someone@x.com' -> 's***@x.com': addresses stay out of the logs"""
    name, _, domain = email.partition("@")
    return f"{name[:1]}***@{domain}"


def notices(report: dict) -> str:
    """What must be read first: Claude's note on the run, and failed data checks."""
    parts = []
    if report.get("note"):
        parts.append(f"<p><b>Claude's note on this run:</b> {html.escape(report['note'])}</p>")
    if report.get("checks"):
        items = "".join(f"<li>{html.escape(c)}</li>" for c in report["checks"])
        parts.append(f"<p><b>Failed checks:</b></p><ul>{items}</ul>")
    return "".join(parts)


def build_message(report: dict, store, sender: str) -> dict:
    """The run's email in Brevo's format, without `to`: every PDF attached."""
    name, address = parseaddr(sender)
    return {
        "sender": {"email": address, "name": name} if name else {"email": address},
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
    """Email the run's report to everyone who hasn't got it; returns what happened."""
    key = os.environ.get("BREVO_API_KEY", "").strip()
    sender = os.environ.get("WATCHLIST_EMAIL_FROM", "").strip()
    wanted = {"BREVO_API_KEY": key, "WATCHLIST_EMAIL_FROM": sender}
    if unset := [n for n, v in wanted.items() if not v]:
        raise RuntimeError(f"Not set: {', '.join(unset)}")
    if not run.get("report"):
        raise RuntimeError(f"Run {run['run_key']} is not rendered")
    people = recipients(data)
    if not people:
        raise RuntimeError("No recipient: add one with `python -m claude app recipient-add`")
    message = build_message(run["report"], store, sender)  # before any mark: may fail
    sent, before, failed, refused = 0, 0, [], True
    for person in people:
        mark = {"k": run["run_key"], "e": person["email"]}
        marked = data.write_steps(
            [
                (
                    "INSERT INTO out_report_email (run_key, email, marked_at) "
                    "VALUES (:k, :e, :t) ON CONFLICT DO NOTHING",
                    [{"t": now_utc(), **mark}],
                )
            ]
        )[0]
        if not marked:
            before += 1
            continue
        try:
            message_id = send({**message, "to": [person]}, key)
        except Refused as e:
            data.write_steps(
                [("DELETE FROM out_report_email WHERE run_key = :k AND email = :e", [mark])]
            )
            failed.append(f"{masked(person['email'])}: {e}")
            continue
        except (httpx.HTTPError, RuntimeError) as e:  # no clear answer: stays marked
            refused = False
            failed.append(f"{masked(person['email'])}, may have gone out: {e or type(e).__name__}")
            continue
        data.write_steps(
            [
                (
                    "UPDATE out_report_email SET message_id = :m WHERE run_key = :k AND email = :e",
                    [{"m": message_id or "accepted", **mark}],
                )
            ]
        )
        sent += 1
    told = f"Run {run['run_key']}: emailed to {sent} of {len(people)}"
    told += f", {before} had it already" if before else ""
    if failed:
        raise (Refused if refused else RuntimeError)(f"{told}; failed: " + "; ".join(failed))
    data.write_steps(
        [
            (
                "UPDATE out_analysis_run SET emailed_at = :t "
                "WHERE run_key = :k AND emailed_at IS NULL",
                [{"t": now_utc(), "k": run["run_key"]}],
            )
        ]
    )
    return told
