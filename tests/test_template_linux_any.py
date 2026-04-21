from __future__ import annotations

from pathlib import Path

import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ppt import __main__ as ppt_main


def test_accepts_arch_agnostic_linux_asset_as_fallback() -> None:
    platform_info = ppt_main.PlatformInfo(os_name="linux", arch="x86_64", libc="glibc")
    release = {
        "tag_name": "v0",
        "assets": [
            {"name": "tool-linux-any.tar.gz", "browser_download_url": ""},
        ],
    }
    asset = ppt_main.select_asset("https://gitlab.com/group/tool", release, platform_info)
    assert asset is not None
    assert asset["name"] == "tool-linux-any.tar.gz"


def test_prefers_arch_specific_over_arch_agnostic() -> None:
    platform_info = ppt_main.PlatformInfo(os_name="linux", arch="x86_64", libc="glibc")
    release = {
        "tag_name": "v0",
        "assets": [
            {"name": "tool-linux-any.tar.gz", "browser_download_url": ""},
            {"name": "tool-linux-x86_64.tar.gz", "browser_download_url": ""},
        ],
    }
    asset = ppt_main.select_asset("https://github.com/example/tool", release, platform_info)
    assert asset is not None
    assert asset["name"] == "tool-linux-x86_64.tar.gz"
