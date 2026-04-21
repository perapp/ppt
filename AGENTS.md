# Agent Instructions

This file is intentionally minimal and only contains repo-specific constraints for agents.

## Git Operations

- Do not create commits.
- Do not stage files (`git add`, `git rm`, etc.) unless explicitly asked.
- Avoid git operations that change repository state unless explicitly requested.

## Secrets

- Do not open/read `.env` (or other credential files) unless the user explicitly asks.
- Do not paste tokens/secrets into chat or logs.

## Dev Workflow

- For test commands and contribution workflow, see `CONTRIBUTING.md`.
