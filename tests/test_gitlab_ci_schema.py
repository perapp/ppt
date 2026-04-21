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


@pytest.mark.skipif(
    not ("CI_API_V4_URL" in os.environ and "CI_PROJECT_ID" in os.environ),
    reason="CI environment vars not present",
)
def test_gitlab_ci_lint_api_validates_config_when_available() -> None:
    """Optional online check using GitLab CI Lint API.

    This catches semantic errors that still produce valid YAML.
    """

    import json
    import urllib.request

    api = os.environ["CI_API_V4_URL"].rstrip("/")
    project_id = os.environ["CI_PROJECT_ID"]
    url = f"{api}/projects/{project_id}/ci/lint"

    token = os.environ.get("CI_JOB_TOKEN") or os.environ.get("GITLAB_TOKEN") or os.environ.get("GL_TOKEN")
    if not token:
        pytest.skip("no CI_JOB_TOKEN/GITLAB_TOKEN/GL_TOKEN available")

    content = (Path(__file__).resolve().parents[1] / ".gitlab-ci.yml").read_text(encoding="utf-8")
    body = json.dumps({"content": content}).encode("utf-8")
    headers = {"Content-Type": "application/json"}

    # In CI, CI_JOB_TOKEN is preferred.
    if os.environ.get("CI_JOB_TOKEN"):
        headers["JOB-TOKEN"] = token
    else:
        headers["PRIVATE-TOKEN"] = token

    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    assert payload.get("valid") is True, payload
