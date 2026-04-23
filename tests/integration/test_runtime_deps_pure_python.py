from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists():
            return parent
    raise RuntimeError("failed to locate repo root")


def _read_runtime_dependencies(pyproject_toml: Path) -> list[str]:
    # Keep this logic in tests so any change to runtime deps is validated.
    import tomllib

    data = tomllib.loads(pyproject_toml.read_text(encoding="utf-8"))
    deps = data.get("project", {}).get("dependencies", [])
    if not isinstance(deps, list):
        raise AssertionError(f"expected [project].dependencies to be a list in {pyproject_toml}")
    return [str(d).strip() for d in deps if str(d).strip()]


def _wheel_tags(dist_info_dir: Path) -> list[str]:
    wheel = dist_info_dir / "WHEEL"
    if not wheel.exists():
        return []
    tags: list[str] = []
    for line in wheel.read_text(encoding="utf-8").splitlines():
        if line.startswith("Tag: "):
            tags.append(line[len("Tag: ") :].strip())
    return tags


def test_runtime_dependencies_are_pure_python() -> None:
    """Ensure release assets can be built for any target.

    Our distribution method bundles a downloaded python-build-standalone runtime plus
    a directory of installed dependencies under `venv/site-packages`.

    We build tarballs for non-native targets on a single CI runner by installing
    dependencies with the build-host Python.

    Therefore, runtime dependencies must be pure Python (universal wheels):
    - no compiled extensions (e.g. *.so/*.pyd)
    - wheel tags must be `*-*-any`

    If you need a dependency with native code, this test explains why it breaks.
    The alternative is to redesign the distribution method to build per-target
    (native runners, cross-toolchains, or a different packaging strategy).
    """

    repo_root = _repo_root()
    deps = _read_runtime_dependencies(repo_root / "pyproject.toml")
    assert deps, "expected at least one runtime dependency"

    # Allow local opt-out when iterating offline.
    if os.environ.get("PPT_SKIP_PURE_PYTHON_DEPS_TEST") == "1":
        return

    with tempfile.TemporaryDirectory(prefix="ppt-purepy-") as td:
        site = Path(td) / "site-packages"
        site.mkdir(parents=True)

        env = os.environ.copy()
        env.update(
            {
                "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                "PIP_NO_CACHE_DIR": "1",
                "PYTHONNOUSERSITE": "1",
            }
        )

        # Only accept wheels (sdists could hide platform-specific builds).
        # Use `uv pip` instead of `python -m pip` so this test works under
        # `uv run pytest` even when the ephemeral test interpreter doesn't
        # include pip.
        subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--only-binary",
                ":all:",
                "--target",
                str(site),
                *deps,
            ],
            check=True,
            env=env,
        )

        native_files: list[str] = []
        for path in site.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix in {".so", ".pyd", ".dll", ".dylib"}:
                native_files.append(str(path.relative_to(site)))

        if native_files:
            native_files.sort()
            raise AssertionError(
                "runtime dependencies must be pure Python (no native extensions)\n"
                "found native files under venv/site-packages:\n"
                + "\n".join(f"- {p}" for p in native_files)
                + "\n\n"
                "Why this is not supported:\n"
                "- Our release packaging downloads a target-specific Python runtime, but installs\n"
                "  dependencies using the build host Python so we can build tarballs for multiple\n"
                "  targets on one CI runner. Native extensions would be built/selected for the\n"
                "  build host, not the target platform.\n\n"
                "Alternative:\n"
                "- Redesign the distribution method to build per-target (native runners, proper\n"
                "  cross-compilation, or a different packaging approach).\n"
            )

        non_any_tags: list[str] = []
        for dist_info in site.glob("*.dist-info"):
            tags = _wheel_tags(dist_info)
            # If there is no WHEEL metadata, be conservative.
            if not tags:
                non_any_tags.append(f"{dist_info.name}: <missing WHEEL Tag>")
                continue
            for tag in tags:
                # Tag format: python-abi-platform
                parts = tag.split("-")
                if len(parts) != 3:
                    non_any_tags.append(f"{dist_info.name}: {tag}")
                    continue
                _py, _abi, platform_tag = parts
                if platform_tag != "any":
                    non_any_tags.append(f"{dist_info.name}: {tag}")

        if non_any_tags:
            non_any_tags.sort()
            raise AssertionError(
                "runtime dependencies must be pure Python (universal wheels tagged *-*-any)\n"
                "found non-universal wheel tags:\n"
                + "\n".join(f"- {t}" for t in non_any_tags)
                + "\n\n"
                "Why this is not supported:\n"
                "- Non-universal wheels are platform-specific and cannot be installed once on a\n"
                "  single runner for all target platforms.\n\n"
                "Alternative:\n"
                "- Redesign the distribution method to build per-target (native runners, proper\n"
                "  cross-compilation, or a different packaging approach).\n"
            )
