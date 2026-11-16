"""Tell GitHub to rebuild the site once a run has finished, so the Data page shows the new
coverage within minutes instead of at the next scheduled rebuild.

It starts the Pages workflow (.github/workflows/pages.yml) through GitHub's API
(workflow_dispatch). It needs GITHUB_DISPATCH_TOKEN: a fine-grained personal access token
for this repository only, with the permission "Actions: Read and write". Without the token it
does nothing, and the daily schedule in pages.yml rebuilds the page anyway.
"""

from __future__ import annotations

import os

import httpx

REPOSITORY = "khalilvandian/Stock-analysis"
WORKFLOW = "pages.yml"
DISPATCH_URL = "https://api.github.com/repos/{repo}/actions/workflows/{workflow}/dispatches"


def publish_site(client: httpx.Client | None = None) -> str:
    token = os.environ.get("GITHUB_DISPATCH_TOKEN")
    if not token:
        return "Site: no GITHUB_DISPATCH_TOKEN, so the daily schedule will rebuild it"
    repo = os.environ.get("GITHUB_REPOSITORY_NAME", REPOSITORY)
    url = DISPATCH_URL.format(repo=repo, workflow=WORKFLOW)
    own = client is None
    client = client or httpx.Client(timeout=30)
    try:
        r = client.post(
            url,
            json={"ref": "main"},
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
    except httpx.HTTPError as exc:  # the data is saved either way; the schedule catches up
        return f"Site: could not reach GitHub ({exc}); the daily schedule will rebuild it"
    finally:
        if own:
            client.close()
    if r.status_code == 204:
        return f"Site: started the {WORKFLOW} workflow on GitHub"
    return f"Site: GitHub answered {r.status_code} ({r.text[:200]}); the schedule will rebuild it"
