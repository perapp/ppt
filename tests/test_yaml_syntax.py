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


@pytest.mark.parametrize("path", iter_yaml_files(Path(__file__).resolve().parents[1]))
def test_yaml_files_parse(path: Path) -> None:
    yaml = YAML(typ="safe")
    text = path.read_text(encoding="utf-8")
    yaml.load(text)
