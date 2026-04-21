# Agent Instructions

This file is intentionally minimal and only contains repo-specific constraints for agents.

## Git Operations

- Do not create commits.
- Do not stage files (`git add`, `git rm`, etc.) unless explicitly asked.
- Avoid git operations that change repository state unless explicitly requested.

## CI Debugging

- When diagnosing pipeline failures, prefer reading the failing job trace and reproducing the exact command locally.
- If using GitLab API tokens (`GITLAB_TOKEN`/`GL_TOKEN`), do not print tokens or include them in logs.

### GitLab API Snippets

Fetch latest pipeline for `main`:

```bash
curl -fsSL \
  --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "https://gitlab.com/api/v4/projects/perapp%2Fppt/pipelines?ref=main&per_page=1"
```

Fetch jobs for a pipeline ID:

```bash
curl -fsSL \
  --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "https://gitlab.com/api/v4/projects/perapp%2Fppt/pipelines/<pipeline_id>/jobs"
```

Fetch the trace for a job ID:

```bash
curl -fsSL \
  --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "https://gitlab.com/api/v4/projects/perapp%2Fppt/jobs/<job_id>/trace"
```

### docker:dind Bind Mount Pitfall

In CI jobs using `docker:dind` (remote Docker daemon), bind mounts like `-v /tmp/...:/workspace` refer to paths on the *daemon container*, not the job container. If a test creates a temp directory in the job container and tries to mount it into `docker run`, the container won’t see it.

Fix patterns:

1. Use `docker build` with a temporary build context (`COPY` the needed files into an image) rather than bind mounting.
2. Use CI artifacts to persist files between jobs/steps.
3. Avoid relying on host paths; write the minimal required files inside the container at runtime.

## Secrets

- Do not open/read `.env` (or other credential files) unless the user explicitly asks.
- Do not paste tokens/secrets into chat or logs.

## Dev Workflow

- For test commands and contribution workflow, see `CONTRIBUTING.md`.
