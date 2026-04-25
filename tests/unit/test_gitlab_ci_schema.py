from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from ruamel.yaml import YAML


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists():
            return parent
    raise RuntimeError("failed to locate repo root")


class Rule(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    # GitLab allows rules entries that omit `if` (e.g. `- when: manual`).
    if_: str | None = Field(default=None, alias="if")


class Job(BaseModel):
    model_config = ConfigDict(extra="allow")

    stage: str | None = None
    image: str | dict[str, Any] | None = None
    script: list[str] | str | None = None
    rules: list[Rule] | None = None
    needs: list[str | dict[str, Any]] | None = None
    artifacts: dict[str, Any] | None = None


def test_gitlab_ci_yaml_schema_is_reasonable() -> None:
    path = _repo_root() / ".gitlab-ci.yml"
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
    assert "test:unit" in jobs

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


def test_gitlab_release_builds_and_links_all_supported_dist_targets() -> None:
    path = _repo_root() / ".gitlab-ci.yml"
    yaml = YAML(typ="safe")
    config = yaml.load(path.read_text(encoding="utf-8"))

    supported_targets = [
        "x86_64-unknown-linux-gnu",
        "x86_64-unknown-linux-musl",
        "aarch64-unknown-linux-gnu",
        "aarch64-unknown-linux-musl",
        "armv7-unknown-linux-gnueabihf",
        "x86_64-apple-darwin",
        "aarch64-apple-darwin",
    ]

    release_job = config["create_gitlab_release"]
    release_needs = set(release_job["needs"])
    release_script = "\n".join(release_job["script"])

    for target in supported_targets:
        job_name = f"build_dist:{target}"
        assert job_name in config
        assert job_name in release_needs
        assert f"ppt-${{VERSION}}-{target}.tar.gz" in release_script
        assert f"job={job_name}" in release_script

        tag_rule = config[job_name]["rules"][0]
        assert tag_rule["if"] == "$CI_COMMIT_TAG && $CI_COMMIT_TAG =~ /^v/"
        assert tag_rule.get("when") != "manual"

    unsupported_job = config["build_dist:armv7-unknown-linux-musleabihf"]
    assert unsupported_job["allow_failure"] is True
    assert unsupported_job["rules"][0].get("when") == "manual"
