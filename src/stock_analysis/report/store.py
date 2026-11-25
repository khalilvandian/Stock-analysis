"""Where the PDFs are kept: a private Azure Blob container (issue #60), or a folder (tests, a PC).

    open_store()   # STOCK_REPORTS_URL = https://<account>.blob.core.windows.net/<container>
                   # else the folder STOCK_REPORTS_DIR (default .cache/reports)

Paths are `<SYMBOL|market|summaries>/<YYYY-MM-DD_HHMM>.pdf`, as on the site. Blob is reached over
HTTPS with the job's managed identity (Storage Blob Data Contributor on the container); there
is no key. The Pages workflow copies the PDFs into the site with its own sign-in.
"""

from __future__ import annotations

import os
import re
from email.utils import formatdate
from pathlib import Path

import httpx

from ..db import ROOT
from ..db.azure import managed_identity_token

PATH = re.compile(r"^[A-Za-z0-9.\-]+/[A-Za-z0-9_.\-]+$")
VERSION = "2023-11-03"
STORAGE = "https://storage.azure.com/"
RETRY = (408, 429, 500, 502, 503, 504)


def check_path(path: str) -> str:
    if not PATH.match(path) or ".." in path:
        raise ValueError(f"not a report path: {path!r}")
    return path


class FolderStore:
    def __init__(self, folder: Path):
        self.folder = Path(folder)

    def put(self, path: str, content: bytes) -> None:
        file = self.folder / check_path(path)
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(content)

    def get(self, path: str) -> bytes:
        return (self.folder / check_path(path)).read_bytes()


class BlobStore:
    def __init__(self, url: str, http: httpx.Client | None = None, tries: int = 3):
        self.url, self.tries = url.rstrip("/"), tries
        self.http = http or httpx.Client(timeout=120)

    def _call(self, method: str, path: str, content: bytes | None = None, **headers):
        token = managed_identity_token(self.http, STORAGE)
        if not token:
            raise RuntimeError("Blob storage needs the job's managed identity")
        headers |= {
            "Authorization": f"Bearer {token}",
            "x-ms-version": VERSION,
            "x-ms-date": formatdate(usegmt=True),
        }
        url = f"{self.url}/{check_path(path)}"
        for attempt in range(1, self.tries + 1):  # put and get can be repeated safely
            try:
                r = self.http.request(method, url, content=content, headers=headers)
            except httpx.TransportError:
                if attempt == self.tries:
                    raise
                continue
            if r.status_code not in RETRY or attempt == self.tries:
                break
        if r.status_code >= 300:
            raise RuntimeError(f"Blob {method} {path} answered {r.status_code}: {r.text[:300]}")
        return r

    def put(self, path: str, content: bytes) -> None:
        self._call(
            "PUT",
            path,
            content,
            **{"x-ms-blob-type": "BlockBlob", "Content-Type": "application/pdf"},
        )

    def get(self, path: str) -> bytes:
        return self._call("GET", path).content


def open_store() -> FolderStore | BlobStore:
    if url := os.environ.get("STOCK_REPORTS_URL"):
        return BlobStore(url)
    return FolderStore(Path(os.environ.get("STOCK_REPORTS_DIR") or ROOT / ".cache/reports"))
