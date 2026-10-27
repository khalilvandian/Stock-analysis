"""Email the last watch list run, with every PDF attached, through Resend (resend.com).

Reads .cache/watchlist/last_run.json (written by analysis/watchlist.py): the subject, the
HTML body and the PDFs. Sends from Resend's own address, so nothing goes out from a
personal mailbox.

Settings, from the cloud environment (never commit them; this repository is public):
    RESEND_API_KEY   Resend API key. Leave it out if it is stored as a network secret
                     for api.resend.com, which adds it to the request.
    WATCHLIST_EMAIL_TO    the one recipient (or pass --to).
    WATCHLIST_EMAIL_FROM  sender; default "Stock analysis <onboarding@resend.dev>", which
                          Resend allows only to the email address of the Resend account.

Usage:
    uv run python analysis/send_email.py --to someone@example.com [--test]
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
LAST_RUN = ROOT / ".cache/watchlist/last_run.json"
API = "https://api.resend.com/emails"
SENDER = "Stock analysis <onboarding@resend.dev>"


def attachment_name(path: str) -> str:
    """analyses/BSX/2026-10-27_2100.pdf -> BSX_2026-10-27_2100.pdf"""
    p = Path(path)
    return f"{p.parent.name}_{p.name}"


def build_message(run: dict, to: str, sender: str, test: bool = False) -> dict:
    body = (ROOT / run["html"]).read_text()
    subject = run["subject"]
    if test:
        subject = f"[Test] {subject}"
        body = "<p><i>Test of the evening email.</i></p>\n" + body
    return {
        "from": sender,
        "to": [to],
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", default=os.environ.get("WATCHLIST_EMAIL_TO"))
    ap.add_argument("--test", action="store_true", help="mark the email as a test")
    args = ap.parse_args()
    if not args.to:
        sys.exit("No recipient: set WATCHLIST_EMAIL_TO or pass --to")
    run = json.loads(LAST_RUN.read_text())
    sender = os.environ.get("WATCHLIST_EMAIL_FROM", SENDER)
    msg = build_message(run, args.to, sender, args.test)
    result = send(msg, os.environ.get("RESEND_API_KEY", "").strip() or None)
    print(f"Sent {len(msg['attachments'])} PDFs: {result.get('id')}")


if __name__ == "__main__":
    main()
