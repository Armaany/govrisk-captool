"""Authenticated GitHub Actions trigger for running Tool 1 on demand."""

from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import streamlit as st


DEFAULT_REPOSITORY = "Armaany/govrisk-scraper"
DEFAULT_WORKFLOW = "run-opportunity-scan.yml"


class ScraperTriggerError(RuntimeError):
    """Raised when GitHub does not accept an on-demand scan request."""


def get_trigger_token() -> str:
    """Read the protected token from environment or Streamlit secrets."""
    token = os.getenv("TOOL1_GITHUB_TOKEN", "").strip()
    if token:
        return token
    try:
        return str(st.secrets.get("TOOL1_GITHUB_TOKEN", "")).strip()
    except Exception:
        return ""


def workflow_dispatch_url(
    repository: str = DEFAULT_REPOSITORY,
    workflow: str = DEFAULT_WORKFLOW,
) -> str:
    return (
        f"https://api.github.com/repos/{repository}/actions/workflows/"
        f"{workflow}/dispatches"
    )


def dispatch_scraper(
    token: str,
    *,
    repository: str = DEFAULT_REPOSITORY,
    workflow: str = DEFAULT_WORKFLOW,
    ref: str = "main",
    opener=urlopen,
) -> None:
    """Dispatch Tool 1's protected workflow without exposing its token."""
    if not token or not token.strip():
        raise ScraperTriggerError("On-demand scanning is not configured.")

    payload = json.dumps({"ref": ref}).encode("utf-8")
    request = Request(
        workflow_dispatch_url(repository, workflow),
        data=payload,
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token.strip()}",
            "Content-Type": "application/json",
            "User-Agent": "GovRisk-Captool/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with opener(request, timeout=20) as response:
            status = getattr(response, "status", response.getcode())
    except HTTPError as exc:
        raise ScraperTriggerError(
            f"GitHub rejected the scan request (HTTP {exc.code})."
        ) from exc
    except (URLError, TimeoutError) as exc:
        raise ScraperTriggerError(
            "GitHub is temporarily unavailable. Please try again."
        ) from exc

    if status != 204:
        raise ScraperTriggerError(
            f"GitHub returned an unexpected scan response (HTTP {status})."
        )
