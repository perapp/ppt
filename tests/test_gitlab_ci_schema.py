from __future__ import annotations

from pathlib import Path
from typing import Any

import os
import pytest
from pydantic import BaseModel, ConfigDict, Field
from ruamel.yaml import YAML


class Rule(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    if_: str = Field(alias="if")


class Job(BaseModel):
    model_config = ConfigDict(extra="allow")

    stage: str | None = None
    image: str | dict[str, Any] | None = None
    script: list[str] | str | None = None
    rules: list[Rule] | None = None
    needs: list[str | dict[str, Any]] | None = None
    artifacts: dict[str, Any] | None = None


def test_gitlab_ci_yaml_schema_is_reasonable() -> None:
    path = Path(__file__).resolve().parents[1] / ".gitlab-ci.yml"
    yaml = YAML(typ="safe")
    config = yaml.load(path.read_text(encoding="utf-8"))
    assert isinstance(config, dict)

    stages = config.get("stages")
    assert isinstance(stages, list)
    assert all(isinstance(s, str) and s for s in stages)

    reserved = {
        "stages",
        "workflow",
        "default",
        "include",
        "variables",
        "image",
        "services",
        "before_script",
        "after_script",
        "cache",
    }

    jobs: dict[str, Any] = {k: v for k, v in config.items() if k not in reserved}
    assert "test" in jobs

    # Validate a subset of job structure (this is not a full GitLab semantics checker).
    errors: list[str] = []
    for name, raw in jobs.items():
        if raw is None:
            continue
        if not isinstance(raw, dict):
            errors.append(f"job {name!r} should be a mapping")
            continue
        try:
            Job.model_validate(raw)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"job {name!r}: {exc}")

    assert not errors, "\n".join(errors)


@pytest.mark.slow
@pytest.mark.network
def test_gitlab_ci_lint_api_validates_config_when_available() -> None:
    """Optional online check using GitLab CI Lint API.

    This catches semantic errors that still produce valid YAML.
    """

    import json
    import urllib.request

    # This test is optional and may be run:
    # - in GitLab CI (CI_API_V4_URL + CI_PROJECT_ID are set)
    # - locally (provide GITLAB_TOKEN and either GITLAB_PROJECT_ID or GITLAB_PROJECT_PATH)
    api = (os.environ.get("CI_API_V4_URL") or os.environ.get("GITLAB_API_V4_URL") or "https://gitlab.com/api/v4").rstrip(
        "/"
    )

    project_ident = os.environ.get("CI_PROJECT_ID") or os.environ.get("GITLAB_PROJECT_ID")
    if not project_ident:
        project_path = os.environ.get("CI_PROJECT_PATH") or os.environ.get("GITLAB_PROJECT_PATH")
        if not project_path:
            # Best-effort inference from git remote, if available.
            try:
                import subprocess

                remote = subprocess.check_output(
                    ["git", "config", "--get", "remote.origin.url"],
                    text=True,
                    stderr=subprocess.DEVNULL,
                ).strip()
            except Exception:
                remote = ""
            if remote.startswith("http://") or remote.startswith("https://"):
                from urllib.parse import urlparse

                parsed = urlparse(remote)
                parts = [p for p in parsed.path.split("/") if p]
                if parts and parts[-1].endswith(".git"):
                    parts[-1] = parts[-1][:-4]
                if len(parts) >= 2:
                    project_path = "/".join(parts)
            else:
                # SSH remote form: git@gitlab.com:group/project.git
                m = __import__("re").match(r"^[^@]+@[^:]+:(.+)$", remote)
                if m:
                    candidate = m.group(1)
                    if candidate.endswith(".git"):
                        candidate = candidate[:-4]
                    if "/" in candidate:
                        project_path = candidate

        if not project_path:
            pytest.skip(
                "GitLab CI lint API test disabled (missing CI_PROJECT_ID/GITLAB_PROJECT_ID or "
                "CI_PROJECT_PATH/GITLAB_PROJECT_PATH). See CONTRIBUTING.md#gitlab-ci-lint-api-test"
            )
        from urllib.parse import quote

        project_ident = quote(project_path, safe="")

    url = f"{api}/projects/{project_ident}/ci/lint"

    # GitLab CI_JOB_TOKEN access to CI lint varies by instance/settings. Keep this
    # check opt-in via a personal/project token.
    token = os.environ.get("GITLAB_TOKEN") or os.environ.get("GL_TOKEN")
    if not token:
        pytest.skip(
            "GitLab CI lint API test disabled (set GITLAB_TOKEN/GL_TOKEN). "
            "See CONTRIBUTING.md#gitlab-ci-lint-api-test"
        )

    content = (Path(__file__).resolve().parents[1] / ".gitlab-ci.yml").read_text(encoding="utf-8")
    body = json.dumps({"content": content}).encode("utf-8")
    headers = {"Content-Type": "application/json"}

    headers["PRIVATE-TOKEN"] = token

    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        # Avoid breaking CI on instances where lint API is forbidden.
        try:
            import urllib.error

            if isinstance(exc, urllib.error.HTTPError) and exc.code in (401, 403):
                pytest.skip(
                    f"GitLab CI lint API forbidden ({exc.code}). "
                    "See CONTRIBUTING.md#gitlab-ci-lint-api-test"
                )
        except Exception:
            pass
        raise

    assert payload.get("valid") is True, payload
