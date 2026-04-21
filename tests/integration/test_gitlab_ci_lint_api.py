from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

import pytest


pytestmark = pytest.mark.gitlab_api


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists():
            return parent
    raise RuntimeError("failed to locate repo root")


def _project_identifier() -> str:
    # Prefer CI-provided identifiers.
    if os.environ.get("CI_PROJECT_ID"):
        return os.environ["CI_PROJECT_ID"]

    if os.environ.get("GITLAB_PROJECT_ID"):
        return os.environ["GITLAB_PROJECT_ID"]

    project_path = os.environ.get("CI_PROJECT_PATH") or os.environ.get("GITLAB_PROJECT_PATH")
    if project_path:
        return quote(project_path, safe="")

    # Best-effort inference from git remote.
    try:
        remote = subprocess.check_output(
            ["git", "config", "--get", "remote.origin.url"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        remote = ""

    if remote.startswith("http://") or remote.startswith("https://"):
        parsed = urlparse(remote)
        parts = [p for p in parsed.path.split("/") if p]
        if parts and parts[-1].endswith(".git"):
            parts[-1] = parts[-1][:-4]
        if len(parts) >= 2:
            return quote("/".join(parts), safe="")

    # SSH remote form: git@gitlab.com:group/project.git
    m = re.match(r"^[^@]+@[^:]+:(.+)$", remote)
    if m:
        candidate = m.group(1)
        if candidate.endswith(".git"):
            candidate = candidate[:-4]
        if "/" in candidate:
            return quote(candidate, safe="")

    raise RuntimeError("missing project identifier")


def test_gitlab_ci_lint_api_validates_ci_config() -> None:
    api = (os.environ.get("CI_API_V4_URL") or os.environ.get("GITLAB_API_V4_URL") or "https://gitlab.com/api/v4").rstrip(
        "/"
    )
    project_ident = _project_identifier()
    url = f"{api}/projects/{project_ident}/ci/lint"

    token = os.environ.get("GITLAB_TOKEN") or os.environ.get("GL_TOKEN")
    if not token:
        if os.environ.get("CI"):
            pytest.fail(
                "GITLAB_TOKEN/GL_TOKEN is required to run GitLab CI lint API test in CI. "
                "See CONTRIBUTING.md#gitlab-ci-lint-api-test"
            )
        pytest.skip(
            "GitLab CI lint API test disabled (set GITLAB_TOKEN/GL_TOKEN). "
            "See CONTRIBUTING.md#gitlab-ci-lint-api-test"
        )

    content = (_repo_root() / ".gitlab-ci.yml").read_text(encoding="utf-8")
    body = json.dumps({"content": content}).encode("utf-8")
    headers = {"Content-Type": "application/json", "PRIVATE-TOKEN": token}

    req = Request(url, data=body, headers=headers, method="POST")
    try:
        with urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        try:
            import urllib.error

            if isinstance(exc, urllib.error.HTTPError):
                pytest.fail(f"GitLab CI lint API failed: HTTP {exc.code}")
        except Exception:
            pass
        raise

    assert payload.get("valid") is True, payload
