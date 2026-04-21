from __future__ import annotations

from pathlib import Path

import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ppt import __main__ as ppt_main


def test_armv7_prefers_eabihf_and_rejects_armv6() -> None:
    platform_info = ppt_main.PlatformInfo(os_name="linux", arch="armv7", libc="glibc")
    release = {
        "tag_name": "v0",
        "assets": [
            {"name": "tool-linux-armv6.tar.gz", "browser_download_url": ""},
            {"name": "tool-linux-armv7-eabihf.tar.gz", "browser_download_url": ""},
            {"name": "tool-linux-armv7.tar.gz", "browser_download_url": ""},
        ],
    }
    asset = ppt_main.select_asset("https://github.com/example/tool", release, platform_info)
    assert asset is not None
    assert "armv7" in asset["name"]
    assert "armv6" not in asset["name"]
