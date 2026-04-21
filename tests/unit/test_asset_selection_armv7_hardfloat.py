from __future__ import annotations

from ppt import __main__ as ppt_main


def test_armv7_prefers_eabihf_and_rejects_armv6() -> None:
    platform_info = ppt_main.PlatformInfo(os_name="linux", vendor="unknown", arch="armv7", env="gnueabihf")
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
