from __future__ import annotations

from pathlib import Path


def pytest_configure() -> None:
    """Load optional local env vars for tests.

    This lets developers keep tokens/secrets in a local `.env` without exporting
    them globally. The file is intentionally gitignored.
    """

    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return

    try:
        from dotenv import load_dotenv
    except Exception:
        # If python-dotenv isn't installed, just don't load anything.
        return

    # If a token var is present but empty, allow `.env` to populate it.
    import os

    for key in ("GITLAB_TOKEN", "GL_TOKEN"):
        if key in os.environ and not os.environ[key]:
            del os.environ[key]

    load_dotenv(env_path, override=False)
