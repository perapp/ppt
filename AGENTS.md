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

- Default `uv run pytest` is configured to skip tests marked `slow`.
- To run the full suite: `uv run pytest -q -o addopts=''`
- To run only slow tests: `uv run pytest -m slow`
