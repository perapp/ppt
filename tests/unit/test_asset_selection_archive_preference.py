from __future__ import annotations

from ppt import __main__ as ppt_main


def test_prefers_tar_gz_over_tar_xz() -> None:
    platform_info = ppt_main.PlatformInfo(os_name="linux", vendor="unknown", arch="x86_64", env="gnu")
    release = {
        "tag_name": "v0",
        "assets": [
            {"name": "tool-linux-x86_64.tar.xz", "browser_download_url": ""},
            {"name": "tool-linux-x86_64.tar.gz", "browser_download_url": ""},
        ],
    }
    asset = ppt_main.select_asset("https://github.com/example/tool", release, platform_info)
    assert asset is not None
    assert asset["name"].endswith(".tar.gz")


def test_accepts_zip_assets() -> None:
    platform_info = ppt_main.PlatformInfo(os_name="linux", vendor="unknown", arch="x86_64", env="gnu")
    release = {
        "tag_name": "v0",
        "assets": [
            {"name": "tool-linux-x86_64.zip", "browser_download_url": ""},
        ],
    }
    asset = ppt_main.select_asset("https://github.com/example/tool", release, platform_info)
    assert asset is not None
    assert asset["name"].endswith(".zip")
