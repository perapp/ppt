from __future__ import annotations

from pathlib import Path

import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ppt import __main__ as ppt_main


def test_selects_musl_asset_on_musl_platform() -> None:
    platform_info = ppt_main.PlatformInfo(os_name="linux", arch="x86_64", libc="musl")
    release = {
        "tag_name": "v0",
        "assets": [
            {"name": "tool-x86_64-unknown-linux-gnu.tar.gz", "browser_download_url": ""},
            {"name": "tool-x86_64-unknown-linux-musl.tar.gz", "browser_download_url": ""},
        ],
    }
    asset = ppt_main.select_asset("https://github.com/example/tool", release, platform_info)
    assert asset is not None
    assert asset["name"].endswith("musl.tar.gz")


def test_prefers_glibc_asset_on_glibc_platform() -> None:
    platform_info = ppt_main.PlatformInfo(os_name="linux", arch="x86_64", libc="glibc")
    release = {
        "tag_name": "v0",
        "assets": [
            {"name": "tool-x86_64-unknown-linux-musl.tar.gz", "browser_download_url": ""},
            {"name": "tool-x86_64-unknown-linux-gnu.tar.gz", "browser_download_url": ""},
        ],
    }
    asset = ppt_main.select_asset("https://github.com/example/tool", release, platform_info)
    assert asset is not None
    assert asset["name"].endswith("gnu.tar.gz")


def test_rejects_wrong_architecture_assets() -> None:
    platform_info = ppt_main.PlatformInfo(os_name="linux", arch="x86_64", libc="glibc")
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


def test_prefers_tar_gz_over_tar_xz() -> None:
    platform_info = ppt_main.PlatformInfo(os_name="linux", arch="x86_64", libc="glibc")
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
