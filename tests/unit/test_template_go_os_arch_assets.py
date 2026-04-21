from __future__ import annotations

from ppt import __main__ as ppt_main


def test_go_style_linux_amd64_is_accepted() -> None:
    platform_info = ppt_main.PlatformInfo(os_name="linux", arch="x86_64", libc="glibc")
    release = {
        "tag_name": "v0",
        "assets": [
            {"name": "tool_linux_amd64.tar.gz", "browser_download_url": ""},
        ],
    }
    asset = ppt_main.select_asset("https://github.com/example/tool", release, platform_info)
    assert asset is not None
    assert asset["name"] == "tool_linux_amd64.tar.gz"


def test_go_style_linux_arm64_is_rejected_on_x86_64() -> None:
    platform_info = ppt_main.PlatformInfo(os_name="linux", arch="x86_64", libc="glibc")
    release = {
        "tag_name": "v0",
        "assets": [
            {"name": "tool_linux_arm64.tar.gz", "browser_download_url": ""},
        ],
    }
    asset = ppt_main.select_asset("https://github.com/example/tool", release, platform_info)
    assert asset is None
