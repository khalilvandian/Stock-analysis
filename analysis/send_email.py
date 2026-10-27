"""Email the last watch list run, with every PDF attached, through Brevo or Resend.

Reads .cache/watchlist/last_run.json (written by analysis/watchlist.py): the subject, the
HTML body and the PDFs. The PDFs are uploaded with the request as real attachments.

Brevo (brevo.com, free: 300 emails a day) is used when BREVO_API_KEY is set; it delivers
to any recipient once the sender address is verified in Brevo. Otherwise Resend
(resend.com), which without a verified domain delivers only to the account's own address.
Both go over HTTPS: SMTP ports are blocked in the cloud environment.

Settings, from the cloud environment (never commit them; this repository is public):
    BREVO_API_KEY    Brevo API key (xkeysib-...). Turn off Brevo's "authorized IPs"
                     blocking, since the cloud environment's IP changes.
    RESEND_API_KEY   Resend API key. Leave it out if it is stored as a network secret
                     for api.resend.com, which adds it to the request.
    WATCHLIST_EMAIL_TO    recipients, comma separated, up to 5 (or pass --to).
    WATCHLIST_EMAIL_FROM  sender, "Name <address>". For Brevo it must be a sender
                          verified in the Brevo account (required). For Resend the
                          default is "Stock analysis <onboarding@resend.dev>".

Usage:
    uv run python analysis/send_email.py --to a@example.com,b@example.com [--test]
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from email.utils import parseaddr
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
LAST_RUN = ROOT / ".cache/watchlist/last_run.json"
API = "https://api.resend.com/emails"
BREVO_API = "https://api.brevo.com/v3/smtp/email"
SENDER = "Stock analysis <onboarding@resend.dev>"
MAX_RECIPIENTS = 5


def attachment_name(path: str) -> str:
    """analyses/BSX/2026-10-27_2100.pdf -> BSX_2026-10-27_2100.pdf"""
    p = Path(path)
    return f"{p.parent.name}_{p.name}"


def recipients(to: str) -> list[str]:
    """'a@x.com, b@y.com' -> ['a@x.com', 'b@y.com']"""
    out = [a.strip() for a in to.split(",") if a.strip()]
    if not out:
        raise SystemExit("No recipient")
    if len(out) > MAX_RECIPIENTS:
        raise SystemExit(f"At most {MAX_RECIPIENTS} recipients, got {len(out)}")
    return out


def build_message(run: dict, to: str, sender: str, test: bool = False) -> dict:
    body = (ROOT / run["html"]).read_text()
    subject = run["subject"]
    if test:
        subject = f"[Test] {subject}"
        body = "<p><i>Test of the evening email.</i></p>\n" + body
    return {
        "from": sender,
        "to": recipients(to),
        "subject": subject,
        "html": body,
        "attachments": [
            {
                "filename": attachment_name(f),
                "content": base64.b64encode((ROOT / f).read_bytes()).decode(),
            }
            for f in run["files"]
        ],
    }


def send(message: dict, key: str | None) -> dict:
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    r = httpx.post(API, json=message, headers=headers, timeout=60)
    if r.status_code >= 300:
        raise SystemExit(f"Resend refused the email ({r.status_code}): {r.text}")
    return r.json()


def to_brevo(message: dict) -> dict:
    """The Resend-shaped message in Brevo's transactional email format."""
    name, address = parseaddr(message["from"])
    sender = {"email": address, "name": name} if name else {"email": address}
    return {
        "sender": sender,
        "to": [{"email": a} for a in message["to"]],
        "subject": message["subject"],
        "htmlContent": message["html"],
        "attachment": [
            {"name": a["filename"], "content": a["content"]} for a in message["attachments"]
        ],
    }


def send_brevo(message: dict, key: str) -> dict:
    r = httpx.post(
        BREVO_API,
        json=to_brevo(message),
        headers={"api-key": key, "accept": "application/json"},
        timeout=60,
    )
    if r.status_code >= 300:
        raise SystemExit(f"Brevo refused the email ({r.status_code}): {r.text}")
    return {"id": r.json().get("messageId")}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", default=os.environ.get("WATCHLIST_EMAIL_TO"))
    ap.add_argument("--test", action="store_true", help="mark the email as a test")
    args = ap.parse_args()
    if not args.to:
        sys.exit("No recipient: set WATCHLIST_EMAIL_TO or pass --to")
    run = json.loads(LAST_RUN.read_text())
    brevo_key = os.environ.get("BREVO_API_KEY", "").strip()
    sender = os.environ.get("WATCHLIST_EMAIL_FROM", "" if brevo_key else SENDER)
    if not sender:
        sys.exit("Brevo needs WATCHLIST_EMAIL_FROM, a sender verified in the Brevo account")
    msg = build_message(run, args.to, sender, args.test)
    if brevo_key:
        result = send_brevo(msg, brevo_key)
    else:
        result = send(msg, os.environ.get("RESEND_API_KEY", "").strip() or None)
    print(f"Sent {len(msg['attachments'])} PDFs: {result.get('id')}")


if __name__ == "__main__":
    main()
