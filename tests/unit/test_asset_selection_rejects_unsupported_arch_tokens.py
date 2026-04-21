from __future__ import annotations

from ppt import __main__ as ppt_main


def test_rejects_s390x_asset_as_arch_agnostic_fallback() -> None:
    platform_info = ppt_main.PlatformInfo(
        os_name="linux",
        vendor="unknown",
        arch="x86_64",
        env="gnu",
    )
    release = {
        "tag_name": "v0",
        "assets": [
            {"name": "tool-linux-s390x.tar.gz", "browser_download_url": ""},
        ],
    }
    asset = ppt_main.select_asset("https://github.com/example/tool", release, platform_info)
    assert asset is None


def test_rejects_ppc64le_asset_as_arch_agnostic_fallback() -> None:
    platform_info = ppt_main.PlatformInfo(
        os_name="linux",
        vendor="unknown",
        arch="aarch64",
        env="musl",
    )
    release = {
        "tag_name": "v0",
        "assets": [
            {"name": "tool-linux-ppc64le.tar.gz", "browser_download_url": ""},
        ],
    }
    asset = ppt_main.select_asset("https://github.com/example/tool", release, platform_info)
    assert asset is None
