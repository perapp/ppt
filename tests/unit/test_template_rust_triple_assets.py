from __future__ import annotations

from ppt import __main__ as ppt_main


def test_rust_target_triple_is_recognized() -> None:
    platform_info = ppt_main.PlatformInfo(os_name="linux", arch="x86_64", libc="glibc")
    release = {
        "tag_name": "v0",
        "assets": [
            {"name": "tool-x86_64-unknown-linux-gnu.tar.gz", "browser_download_url": ""},
            {"name": "tool-aarch64-unknown-linux-gnu.tar.gz", "browser_download_url": ""},
        ],
    }
    asset = ppt_main.select_asset("https://github.com/example/tool", release, platform_info)
    assert asset is not None
    assert asset["name"].endswith("x86_64-unknown-linux-gnu.tar.gz")
