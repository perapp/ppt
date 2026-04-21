# Contributing

This document is for developers contributing changes to `ppt`.
User-facing usage lives in `README.md`.

## Development Setup

This project uses `uv` for running tests locally.

Python requirement: `>=3.12` (see `pyproject.toml`).

Create/update the local environment:

```bash
uv sync
```

Run the unit test suite:

```bash
uv run pytest
```

Run integration tests:

```bash
uv run pytest tests/integration
```

Run container integration tests:

```bash
uv run pytest tests/integration -m container
```

## Dev Sandbox Container

For a quick, ephemeral Ubuntu sandbox with ppt installed, run:

```bash
./sandbox.sh
```

Notes:
 - The sandbox image is rebuilt automatically when `dev/Containerfile.sandbox` changes.
 - To force rebuild, use `./sandbox.sh --rebuild`

## CI Config Validation

We validate YAML syntax for all `*.yml` / `*.yaml` files in the repository and do a lightweight structural check of `.gitlab-ci.yml`.

In addition, there is an optional GitLab CI Lint API test that can catch semantic errors that still produce valid YAML.

### GitLab CI Lint API Test

The test is implemented in `tests/integration/test_gitlab_ci_lint_api.py`.

It is marked `gitlab_api` and runs as part of the integration suite.

Why opt-in:
- Some GitLab instances do not allow CI lint via `CI_JOB_TOKEN`.
- We want local development to work without requiring network access.

To enable the online check locally:

1. Create a **Project access token** for this project.
2. Set role: `Developer`.
3. Set scopes: `api` (recommended) and optionally `read_api`.
4. Put it in a local `.env` file in the repo root (it is gitignored):

```text
GITLAB_TOKEN=***
```

`uv run pytest` will auto-load `.env` for tests.

```bash
uv run pytest -q tests/integration -m gitlab_api -rs
```

To enable the online check in GitLab CI:

1. Add the token as a masked CI/CD variable named `GITLAB_TOKEN`.
2. Keep it protected if you only want it to run on protected branches/tags.

Security notes:
- Treat access tokens as secrets. Do not paste them into chat or commit them to the repo.
- Prefer short expirations and rotate when needed.
