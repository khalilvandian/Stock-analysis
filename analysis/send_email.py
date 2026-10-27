"""Email the last watch list run, with every PDF attached, through Brevo.

Reads .cache/watchlist/last_run.json (written by analysis/watchlist.py): the subject, the
HTML body and the PDFs. The PDFs are uploaded with the request as real attachments.

Brevo (brevo.com, free: 300 emails a day) delivers to any recipient once the sender address
is verified in Brevo. It goes over HTTPS: SMTP ports are blocked in the cloud environment.

Settings, from the cloud environment (never commit them; this repository is public):
    BREVO_API_KEY         Brevo API key (xkeysib-...). Turn off Brevo's "authorized IPs"
                          blocking, since the cloud environment's IP changes.
    WATCHLIST_EMAIL_FROM  sender, "Name <address>", verified in the Brevo account.
    WATCHLIST_EMAIL_TO    recipients, comma separated, up to 5 (or pass --to).

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
API = "https://api.brevo.com/v3/smtp/email"
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
    """The run's email in Brevo's transactional email format, every PDF attached."""
    body = (ROOT / run["html"]).read_text()
    subject = run["subject"]
    if test:
        subject = f"[Test] {subject}"
        body = "<p><i>Test of the evening email.</i></p>\n" + body
    name, address = parseaddr(sender)
    return {
        "sender": {"email": address, "name": name} if name else {"email": address},
        "to": [{"email": a} for a in recipients(to)],
        "subject": subject,
        "htmlContent": body,
        "attachment": [
            {
                "name": attachment_name(f),
                "content": base64.b64encode((ROOT / f).read_bytes()).decode(),
            }
            for f in run["files"]
        ],
    }


def send(message: dict, key: str) -> dict:
    r = httpx.post(
        API,
        json=message,
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
    key = os.environ.get("BREVO_API_KEY", "").strip()
    sender = os.environ.get("WATCHLIST_EMAIL_FROM", "").strip()
    if not key:
        sys.exit("BREVO_API_KEY is not set")
    if not sender:
        sys.exit("WATCHLIST_EMAIL_FROM is not set (a sender verified in the Brevo account)")
    run = json.loads(LAST_RUN.read_text())
    msg = build_message(run, args.to, sender, args.test)
    result = send(msg, key)
    print(f"Sent {len(msg['attachment'])} PDFs: {result.get('id')}")


if __name__ == "__main__":
    main()
