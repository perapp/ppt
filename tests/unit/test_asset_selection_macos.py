from __future__ import annotations

from ppt import __main__ as ppt_main


def test_selects_darwin_x86_64_asset() -> None:
    platform_info = ppt_main.PlatformInfo(os_name="darwin", vendor="apple", arch="x86_64", env=None)
    release = {
        "tag_name": "v0",
        "assets": [
            {"name": "tool-aarch64-apple-darwin.tar.gz", "browser_download_url": ""},
            {"name": "tool-x86_64-apple-darwin.tar.gz", "browser_download_url": ""},
        ],
    }
    asset = ppt_main.select_asset("https://github.com/example/tool", release, platform_info)
    assert asset is not None
    assert asset["name"].endswith("x86_64-apple-darwin.tar.gz")


def test_rejects_linux_assets_on_darwin() -> None:
    platform_info = ppt_main.PlatformInfo(os_name="darwin", vendor="apple", arch="x86_64", env=None)
    release = {
        "tag_name": "v0",
        "assets": [
            {"name": "tool-x86_64-unknown-linux-gnu.tar.gz", "browser_download_url": ""},
        ],
    }
    asset = ppt_main.select_asset("https://github.com/example/tool", release, platform_info)
    assert asset is None


def test_accepts_macos_token_as_darwin() -> None:
    platform_info = ppt_main.PlatformInfo(os_name="darwin", vendor="apple", arch="aarch64", env=None)
    release = {
        "tag_name": "v0",
        "assets": [
            {"name": "tool-macos-arm64.tar.gz", "browser_download_url": ""},
        ],
    }
    asset = ppt_main.select_asset("https://github.com/example/tool", release, platform_info)
    assert asset is not None
    assert asset["name"] == "tool-macos-arm64.tar.gz"
