# Contributing

## Development Setup

This project uses `uv` for running tests locally.

Run the test suite:

```bash
uv run pytest
```

By default, `pytest` is configured to skip tests marked as `slow`.

Run the full suite (including slow tests):

```bash
uv run pytest -q -o addopts=''
```

Run only slow tests:

```bash
uv run pytest -m slow
```

## CI Config Validation

We validate YAML syntax for all `*.yml` / `*.yaml` files in the repository and do a lightweight structural check of `.gitlab-ci.yml`.

In addition, there is an optional GitLab CI Lint API test that can catch semantic errors that still produce valid YAML.

### GitLab CI Lint API Test

The test is implemented in `tests/test_gitlab_ci_schema.py` and is **opt-in**.

It is also marked `slow`/`network`, so it is skipped by default unless you run
the full suite or explicitly include it.

Why opt-in:
- Some GitLab instances do not allow CI lint via `CI_JOB_TOKEN`.
- We want local development to work without requiring network access.

To enable the online check locally:

1. Create a **Project access token** for this project.
2. Set role: `Developer`.
3. Set scopes: `api` (recommended) and optionally `read_api`.
4. Export it as `GITLAB_TOKEN` in your shell.

```bash
export GITLAB_TOKEN=***
uv run pytest -q tests/test_gitlab_ci_schema.py::test_gitlab_ci_lint_api_validates_config_when_available -rs
```

Alternatively, you can put the token in a local `.env` file in the repo root
(it is gitignored). `uv run pytest` will auto-load it for tests.

To enable the online check in GitLab CI:

1. Add the token as a masked CI/CD variable named `GITLAB_TOKEN`.
2. Keep it protected if you only want it to run on protected branches/tags.

Security notes:
- Treat access tokens as secrets. Do not paste them into chat or commit them to the repo.
- Prefer short expirations and rotate when needed.
