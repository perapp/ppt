from __future__ import annotations

from pathlib import Path

import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ppt import __main__ as ppt_main


def test_ignores_sha256_named_archives() -> None:
    platform_info = ppt_main.PlatformInfo(os_name="linux", arch="x86_64", libc="glibc")
    release = {
        "tag_name": "v0",
        "assets": [
            {"name": "tool-linux-x86_64-sha256.tar.gz", "browser_download_url": ""},
            {"name": "tool-linux-x86_64.tar.gz", "browser_download_url": ""},
        ],
    }
    asset = ppt_main.select_asset("https://github.com/example/tool", release, platform_info)
    assert asset is not None
    assert asset["name"].endswith("linux-x86_64.tar.gz")
