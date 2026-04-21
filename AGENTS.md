# Agent Instructions

## Git Operations

- Never create commits.
- Never stage files (`git add`, `git rm`, etc.) unless explicitly asked.
- Avoid any git operation that changes repository state unless explicitly requested.
- `git status` and `git log` are allowed when needed, but avoid running them unnecessarily.

## Secrets

- Never open/read `.env` (or other credential files) during support unless the user explicitly asks.
- Never paste tokens/secrets into chat or logs.

## Tests

- Default `uv run pytest` runs the unit suite in `tests/unit`.
- To run integration tests: `uv run pytest tests/integration`
- To run container integration tests: `uv run pytest tests/integration -m container`
- To run GitLab API integration tests: `uv run pytest tests/integration -m gitlab_api`
