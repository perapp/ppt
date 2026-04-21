#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Read asset list JSON files created by fetch_asset_list.py and produce a CSV matrix "
            "of which release asset ppt would select for each supported platform."
        )
    )
    ap.add_argument(
        "--base-dir",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="Base directory containing asset-lists/ (default: directory containing this script)",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="CSV output path (default: <base-dir>/asset-matrix.csv)",
    )
    args = ap.parse_args()

    base_dir: Path = args.base_dir
    out_path: Path = args.out or (base_dir / "asset-matrix.csv")

    _ensure_ppt_importable()
    from ppt import __main__ as ppt_main  # noqa: PLC0415

    platforms = supported_platforms(ppt_main)

    rows: list[dict[str, str]] = []
    for json_path in sorted((base_dir / "asset-lists").rglob("*.json")):
        record = analyze_one(json_path, ppt_main, platforms)
        if record is not None:
            rows.append(record)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "repo",
                "status",
                "release_tag",
                "asset_count",
                *[p.key for p in platforms],
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    return 0


def _ensure_ppt_importable() -> None:
    """Ensure `import ppt` works when running from this dev directory.

    Prefer importing from the repo's `src/` directory. This keeps the report script
    runnable even when `ppt` isn't installed into the current interpreter.
    """

    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / "pyproject.toml").exists():
            src = parent / "src"
            if src.exists():
                sys.path.insert(0, str(src))
            return


@dataclass(frozen=True)
class Platform:
    key: str
    info: object


def supported_platforms(ppt_main) -> list[Platform]:
    """Enumerate ppt platforms we want to score assets against."""

    def p(os_name: str, vendor: str, arch: str, env: str | None) -> Platform:
        info = ppt_main.PlatformInfo(os_name=os_name, vendor=vendor, arch=arch, env=env)
        return Platform(key=info.key, info=info)

    return [
        p("linux", "unknown", "x86_64", "gnu"),
        p("linux", "unknown", "x86_64", "musl"),
        p("linux", "unknown", "aarch64", "gnu"),
        p("linux", "unknown", "aarch64", "musl"),
        p("linux", "unknown", "armv7", "gnueabihf"),
        p("linux", "unknown", "armv7", "musleabihf"),
        p("darwin", "apple", "x86_64", None),
        p("darwin", "apple", "aarch64", None),
    ]


def analyze_one(json_path: Path, ppt_main, platforms: list[Platform]) -> dict[str, str] | None:
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        repo = infer_repo_url_from_asset_list_path(json_path)
        if not repo:
            return None
        return {
            "repo": repo,
            "status": "invalid_json",
            "release_tag": "",
            "asset_count": "0",
            **{p.key: "" for p in platforms},
        }

    meta = payload.get("__meta__") or {}
    repo = str(meta.get("repo") or "").strip() or infer_repo_url_from_asset_list_path(json_path)
    status = str(meta.get("status") or "").strip() or "unknown"
    release_tag = str(meta.get("release_tag") or "").strip()

    # If the downloader didn't record the repo URL, skip: we don't have a stable row key.
    if not repo:
        return None

    assets: list[dict[str, str]] = []
    for name, info in payload.items():
        if name == "__meta__":
            continue
        if not isinstance(info, dict):
            continue
        url = info.get("url") or ""
        assets.append({"name": str(name), "browser_download_url": str(url)})

    release = {"tag_name": release_tag or "", "assets": assets}

    out: dict[str, str] = {
        "repo": repo,
        "status": status,
        "release_tag": release_tag,
        "asset_count": str(len(assets)),
    }
    for platform in platforms:
        selected = ppt_main.select_asset(repo, release, platform.info)
        out[platform.key] = (selected or {}).get("name", "")
    return out


def infer_repo_url_from_asset_list_path(json_path: Path) -> str:
    """Best-effort repo URL from asset-lists/<host>/.../<name>.json path."""

    parts = list(json_path.parts)
    if "asset-lists" not in parts:
        return ""
    idx = parts.index("asset-lists")
    rel = parts[idx + 1 :]
    if len(rel) < 2:
        return ""
    host = rel[0]
    tail = list(rel[1:])
    if not tail:
        return ""
    tail[-1] = Path(tail[-1]).stem
    return f"https://{host}/" + "/".join(tail)


if __name__ == "__main__":
    raise SystemExit(main())
