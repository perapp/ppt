from __future__ import annotations

from pathlib import Path

import pytest
from ruamel.yaml import YAML


def iter_yaml_files(repo_root: Path) -> list[Path]:
    paths: list[Path] = []
    for p in repo_root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix not in {".yml", ".yaml"}:
            continue
        # Avoid scanning generated / vendored content.
        parts = set(p.parts)
        if parts & {".git", ".venv", ".tmp", "node_modules", "dist", "build", "target", "__pycache__"}:
            continue
        paths.append(p)
    return sorted(paths)


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists():
            return parent
    raise RuntimeError("failed to locate repo root")


@pytest.mark.parametrize("path", iter_yaml_files(_repo_root()))
def test_yaml_files_parse(path: Path) -> None:
    yaml = YAML(typ="safe")
    text = path.read_text(encoding="utf-8")
    yaml.load(text)
