from __future__ import annotations

import sys
from pathlib import Path


def pytest_configure() -> None:
    """Load optional local env vars for tests.

    This lets developers keep tokens/secrets in a local `.env` without exporting
    them globally. The file is intentionally gitignored.
    """

    repo_root = _repo_root()

    # Ensure `import ppt` works regardless of test file location.
    src_dir = repo_root / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

    env_path = repo_root / ".env"
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


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / "pyproject.toml").exists():
            return parent
    # Fallback: repository root is expected to be one level above tests/
    return here.parents[1]
