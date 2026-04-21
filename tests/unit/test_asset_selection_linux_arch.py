from __future__ import annotations

from ppt import __main__ as ppt_main


def test_rejects_wrong_architecture_assets() -> None:
    platform_info = ppt_main.PlatformInfo(os_name="linux", vendor="unknown", arch="x86_64", env="gnu")
    release = {
        "tag_name": "v0",
        "assets": [
            {"name": "tool-linux-aarch64.tar.gz", "browser_download_url": ""},
            {"name": "tool-linux-x86_64.tar.gz", "browser_download_url": ""},
        ],
    }
    asset = ppt_main.select_asset("https://github.com/example/tool", release, platform_info)
    assert asset is not None
    assert "x86_64" in asset["name"]


def test_x86_64_accepts_linux64_alias() -> None:
    platform_info = ppt_main.PlatformInfo(os_name="linux", vendor="unknown", arch="x86_64", env="gnu")
    release = {
        "tag_name": "v0",
        "assets": [
            {"name": "tool-linux64.tar.gz", "browser_download_url": ""},
        ],
    }
    asset = ppt_main.select_asset("https://github.com/example/tool", release, platform_info)
    assert asset is not None
    assert asset["name"] == "tool-linux64.tar.gz"
