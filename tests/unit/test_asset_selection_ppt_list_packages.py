from __future__ import annotations

from ppt import __main__ as ppt_main


PLATFORMS = [
    ppt_main.PlatformInfo(os_name="linux", vendor="unknown", arch="x86_64", env="gnu"),
    ppt_main.PlatformInfo(os_name="linux", vendor="unknown", arch="x86_64", env="musl"),
    ppt_main.PlatformInfo(os_name="linux", vendor="unknown", arch="aarch64", env="gnu"),
    ppt_main.PlatformInfo(os_name="linux", vendor="unknown", arch="aarch64", env="musl"),
    ppt_main.PlatformInfo(os_name="linux", vendor="unknown", arch="armv7", env="gnueabihf"),
    ppt_main.PlatformInfo(os_name="linux", vendor="unknown", arch="armv7", env="musleabihf"),
    ppt_main.PlatformInfo(os_name="darwin", vendor="apple", arch="x86_64", env=None),
    ppt_main.PlatformInfo(os_name="darwin", vendor="apple", arch="aarch64", env=None),
]


def make_release(tag: str, asset_names: list[str]) -> dict:
    return {
        "tag_name": tag,
        "assets": [{"name": name, "browser_download_url": ""} for name in asset_names],
    }


def assert_expected(repo: str, release: dict, expected_by_platform: dict[str, str | None]) -> None:
    for platform in PLATFORMS:
        asset = ppt_main.select_asset(repo, release, platform)
        got = asset["name"] if asset else None
        assert got == expected_by_platform.get(platform.key), (repo, platform.key, got)


def test_asset_selection_burntsushi_ripgrep() -> None:
    repo = "https://github.com/BurntSushi/ripgrep"
    release = make_release(
        "15.1.0",
        [
            "ripgrep-15.1.0-x86_64-unknown-linux-musl.tar.gz",
            "ripgrep-15.1.0-aarch64-unknown-linux-gnu.tar.gz",
            "ripgrep-15.1.0-armv7-unknown-linux-gnueabihf.tar.gz",
            "ripgrep-15.1.0-armv7-unknown-linux-musleabihf.tar.gz",
            "ripgrep-15.1.0-x86_64-apple-darwin.tar.gz",
            "ripgrep-15.1.0-aarch64-apple-darwin.tar.gz",
        ],
    )

    assert_expected(
        repo,
        release,
        {
            "x86_64-unknown-linux-gnu": "ripgrep-15.1.0-x86_64-unknown-linux-musl.tar.gz",
            "x86_64-unknown-linux-musl": "ripgrep-15.1.0-x86_64-unknown-linux-musl.tar.gz",
            "aarch64-unknown-linux-gnu": "ripgrep-15.1.0-aarch64-unknown-linux-gnu.tar.gz",
            "aarch64-unknown-linux-musl": None,
            "armv7-unknown-linux-gnueabihf": "ripgrep-15.1.0-armv7-unknown-linux-gnueabihf.tar.gz",
            "armv7-unknown-linux-musleabihf": "ripgrep-15.1.0-armv7-unknown-linux-musleabihf.tar.gz",
            "x86_64-apple-darwin": "ripgrep-15.1.0-x86_64-apple-darwin.tar.gz",
            "aarch64-apple-darwin": "ripgrep-15.1.0-aarch64-apple-darwin.tar.gz",
        },
    )


def test_asset_selection_clementtsang_bottom() -> None:
    repo = "https://github.com/ClementTsang/bottom"
    release = make_release(
        "0.12.3",
        [
            "bottom_x86_64-unknown-linux-gnu-2-17.tar.gz",
            "bottom_x86_64-unknown-linux-musl.tar.gz",
            "bottom_aarch64-unknown-linux-gnu.tar.gz",
            "bottom_aarch64-unknown-linux-musl.tar.gz",
            "bottom_armv7-unknown-linux-gnueabihf.tar.gz",
            "bottom_armv7-unknown-linux-musleabihf.tar.gz",
            "bottom_x86_64-apple-darwin.tar.gz",
            "bottom_aarch64-apple-darwin.tar.gz",
        ],
    )
    assert_expected(
        repo,
        release,
        {
            "x86_64-unknown-linux-gnu": "bottom_x86_64-unknown-linux-gnu-2-17.tar.gz",
            "x86_64-unknown-linux-musl": "bottom_x86_64-unknown-linux-musl.tar.gz",
            "aarch64-unknown-linux-gnu": "bottom_aarch64-unknown-linux-gnu.tar.gz",
            "aarch64-unknown-linux-musl": "bottom_aarch64-unknown-linux-musl.tar.gz",
            "armv7-unknown-linux-gnueabihf": "bottom_armv7-unknown-linux-gnueabihf.tar.gz",
            "armv7-unknown-linux-musleabihf": "bottom_armv7-unknown-linux-musleabihf.tar.gz",
            "x86_64-apple-darwin": "bottom_x86_64-apple-darwin.tar.gz",
            "aarch64-apple-darwin": "bottom_aarch64-apple-darwin.tar.gz",
        },
    )


def test_asset_selection_aristocratos_btop() -> None:
    repo = "https://github.com/aristocratos/btop"
    release = make_release(
        "v1.4.6",
        [
            "btop-x86_64-unknown-linux-musl.tbz",
            "btop-aarch64-unknown-linux-musl.tbz",
            "btop-armv7-unknown-linux-musleabi.tbz",
        ],
    )
    assert_expected(
        repo,
        release,
        {
            "x86_64-unknown-linux-gnu": "btop-x86_64-unknown-linux-musl.tbz",
            "x86_64-unknown-linux-musl": "btop-x86_64-unknown-linux-musl.tbz",
            "aarch64-unknown-linux-gnu": "btop-aarch64-unknown-linux-musl.tbz",
            "aarch64-unknown-linux-musl": "btop-aarch64-unknown-linux-musl.tbz",
            "armv7-unknown-linux-gnueabihf": "btop-armv7-unknown-linux-musleabi.tbz",
            "armv7-unknown-linux-musleabihf": "btop-armv7-unknown-linux-musleabi.tbz",
            "x86_64-apple-darwin": None,
            "aarch64-apple-darwin": None,
        },
    )


def test_asset_selection_astral_sh_uv() -> None:
    repo = "https://github.com/astral-sh/uv"
    release = make_release(
        "0.11.7",
        [
            "uv-x86_64-unknown-linux-gnu.tar.gz",
            "uv-x86_64-unknown-linux-musl.tar.gz",
            "uv-aarch64-unknown-linux-gnu.tar.gz",
            "uv-aarch64-unknown-linux-musl.tar.gz",
            "uv-armv7-unknown-linux-gnueabihf.tar.gz",
            "uv-arm-unknown-linux-musleabihf.tar.gz",
            "uv-x86_64-apple-darwin.tar.gz",
            "uv-aarch64-apple-darwin.tar.gz",
        ],
    )
    assert_expected(
        repo,
        release,
        {
            "x86_64-unknown-linux-gnu": "uv-x86_64-unknown-linux-gnu.tar.gz",
            "x86_64-unknown-linux-musl": "uv-x86_64-unknown-linux-musl.tar.gz",
            "aarch64-unknown-linux-gnu": "uv-aarch64-unknown-linux-gnu.tar.gz",
            "aarch64-unknown-linux-musl": "uv-aarch64-unknown-linux-musl.tar.gz",
            "armv7-unknown-linux-gnueabihf": "uv-armv7-unknown-linux-gnueabihf.tar.gz",
            "armv7-unknown-linux-musleabihf": "uv-arm-unknown-linux-musleabihf.tar.gz",
            "x86_64-apple-darwin": "uv-x86_64-apple-darwin.tar.gz",
            "aarch64-apple-darwin": "uv-aarch64-apple-darwin.tar.gz",
        },
    )


def test_asset_selection_dandavison_delta() -> None:
    repo = "https://github.com/dandavison/delta"
    release = make_release(
        "0.19.2",
        [
            "delta-0.19.2-x86_64-unknown-linux-gnu.tar.gz",
            "delta-0.19.2-x86_64-unknown-linux-musl.tar.gz",
            "delta-0.19.2-aarch64-unknown-linux-gnu.tar.gz",
            "delta-0.19.2-arm-unknown-linux-gnueabihf.tar.gz",
            "delta-0.19.2-aarch64-apple-darwin.tar.gz",
        ],
    )
    assert_expected(
        repo,
        release,
        {
            "x86_64-unknown-linux-gnu": "delta-0.19.2-x86_64-unknown-linux-gnu.tar.gz",
            "x86_64-unknown-linux-musl": "delta-0.19.2-x86_64-unknown-linux-musl.tar.gz",
            "aarch64-unknown-linux-gnu": "delta-0.19.2-aarch64-unknown-linux-gnu.tar.gz",
            "aarch64-unknown-linux-musl": None,
            "armv7-unknown-linux-gnueabihf": "delta-0.19.2-arm-unknown-linux-gnueabihf.tar.gz",
            "armv7-unknown-linux-musleabihf": None,
            "x86_64-apple-darwin": None,
            "aarch64-apple-darwin": "delta-0.19.2-aarch64-apple-darwin.tar.gz",
        },
    )


def test_asset_selection_dundee_gdu() -> None:
    repo = "https://github.com/dundee/gdu"
    release = make_release(
        "v5.35.0",
        [
            "gdu_linux_amd64.tgz",
            "gdu_linux_arm64.tgz",
            "gdu_linux_armv7l.tgz",
            "gdu_darwin_amd64.tgz",
            "gdu_darwin_arm64.tgz",
        ],
    )
    assert_expected(
        repo,
        release,
        {
            "x86_64-unknown-linux-gnu": "gdu_linux_amd64.tgz",
            "x86_64-unknown-linux-musl": "gdu_linux_amd64.tgz",
            "aarch64-unknown-linux-gnu": "gdu_linux_arm64.tgz",
            "aarch64-unknown-linux-musl": "gdu_linux_arm64.tgz",
            "armv7-unknown-linux-gnueabihf": "gdu_linux_armv7l.tgz",
            "armv7-unknown-linux-musleabihf": "gdu_linux_armv7l.tgz",
            "x86_64-apple-darwin": "gdu_darwin_amd64.tgz",
            "aarch64-apple-darwin": "gdu_darwin_arm64.tgz",
        },
    )


def test_asset_selection_eza_community_eza() -> None:
    repo = "https://github.com/eza-community/eza"
    release = make_release(
        "v0.23.4",
        [
            "eza_x86_64-unknown-linux-gnu.tar.gz",
            "eza_x86_64-unknown-linux-musl.tar.gz",
            "eza_aarch64-unknown-linux-gnu.tar.gz",
            "eza_arm-unknown-linux-gnueabihf.tar.gz",
        ],
    )
    assert_expected(
        repo,
        release,
        {
            "x86_64-unknown-linux-gnu": "eza_x86_64-unknown-linux-gnu.tar.gz",
            "x86_64-unknown-linux-musl": "eza_x86_64-unknown-linux-musl.tar.gz",
            "aarch64-unknown-linux-gnu": "eza_aarch64-unknown-linux-gnu.tar.gz",
            "aarch64-unknown-linux-musl": None,
            "armv7-unknown-linux-gnueabihf": "eza_arm-unknown-linux-gnueabihf.tar.gz",
            "armv7-unknown-linux-musleabihf": None,
            "x86_64-apple-darwin": None,
            "aarch64-apple-darwin": None,
        },
    )


def test_asset_selection_fastfetch_cli_fastfetch() -> None:
    repo = "https://github.com/fastfetch-cli/fastfetch"
    release = make_release(
        "2.61.0",
        [
            "fastfetch-linux-amd64-polyfilled.tar.gz",
            "fastfetch-linux-aarch64-polyfilled.tar.gz",
            "fastfetch-linux-armv7l.tar.gz",
            "fastfetch-macos-amd64.tar.gz",
            "fastfetch-macos-aarch64.tar.gz",
        ],
    )
    assert_expected(
        repo,
        release,
        {
            "x86_64-unknown-linux-gnu": "fastfetch-linux-amd64-polyfilled.tar.gz",
            "x86_64-unknown-linux-musl": "fastfetch-linux-amd64-polyfilled.tar.gz",
            "aarch64-unknown-linux-gnu": "fastfetch-linux-aarch64-polyfilled.tar.gz",
            "aarch64-unknown-linux-musl": "fastfetch-linux-aarch64-polyfilled.tar.gz",
            "armv7-unknown-linux-gnueabihf": "fastfetch-linux-armv7l.tar.gz",
            "armv7-unknown-linux-musleabihf": "fastfetch-linux-armv7l.tar.gz",
            "x86_64-apple-darwin": "fastfetch-macos-amd64.tar.gz",
            "aarch64-apple-darwin": "fastfetch-macos-aarch64.tar.gz",
        },
    )


def test_asset_selection_helix_editor_helix() -> None:
    repo = "https://github.com/helix-editor/helix"
    release = make_release(
        "25.07.1",
        [
            "helix-25.07.1-x86_64-linux.tar.xz",
            "helix-25.07.1-aarch64-linux.tar.xz",
            "helix-25.07.1-x86_64-macos.tar.xz",
            "helix-25.07.1-aarch64-macos.tar.xz",
        ],
    )
    assert_expected(
        repo,
        release,
        {
            "x86_64-unknown-linux-gnu": "helix-25.07.1-x86_64-linux.tar.xz",
            "x86_64-unknown-linux-musl": "helix-25.07.1-x86_64-linux.tar.xz",
            "aarch64-unknown-linux-gnu": "helix-25.07.1-aarch64-linux.tar.xz",
            "aarch64-unknown-linux-musl": "helix-25.07.1-aarch64-linux.tar.xz",
            "armv7-unknown-linux-gnueabihf": None,
            "armv7-unknown-linux-musleabihf": None,
            "x86_64-apple-darwin": "helix-25.07.1-x86_64-macos.tar.xz",
            "aarch64-apple-darwin": "helix-25.07.1-aarch64-macos.tar.xz",
        },
    )


def test_asset_selection_junegunn_fzf() -> None:
    repo = "https://github.com/junegunn/fzf"
    release = make_release(
        "v0.71.0",
        [
            "fzf-0.71.0-linux_amd64.tar.gz",
            "fzf-0.71.0-linux_arm64.tar.gz",
            "fzf-0.71.0-linux_armv7.tar.gz",
            "fzf-0.71.0-darwin_amd64.tar.gz",
            "fzf-0.71.0-darwin_arm64.tar.gz",
        ],
    )
    assert_expected(
        repo,
        release,
        {
            "x86_64-unknown-linux-gnu": "fzf-0.71.0-linux_amd64.tar.gz",
            "x86_64-unknown-linux-musl": "fzf-0.71.0-linux_amd64.tar.gz",
            "aarch64-unknown-linux-gnu": "fzf-0.71.0-linux_arm64.tar.gz",
            "aarch64-unknown-linux-musl": "fzf-0.71.0-linux_arm64.tar.gz",
            "armv7-unknown-linux-gnueabihf": "fzf-0.71.0-linux_armv7.tar.gz",
            "armv7-unknown-linux-musleabihf": "fzf-0.71.0-linux_armv7.tar.gz",
            "x86_64-apple-darwin": "fzf-0.71.0-darwin_amd64.tar.gz",
            "aarch64-apple-darwin": "fzf-0.71.0-darwin_arm64.tar.gz",
        },
    )


def test_asset_selection_neovim_neovim() -> None:
    repo = "https://github.com/neovim/neovim"
    release = make_release(
        "v0.12.1",
        [
            "nvim-linux-x86_64.tar.gz",
            "nvim-linux-arm64.tar.gz",
            "nvim-macos-x86_64.tar.gz",
            "nvim-macos-arm64.tar.gz",
        ],
    )
    assert_expected(
        repo,
        release,
        {
            "x86_64-unknown-linux-gnu": "nvim-linux-x86_64.tar.gz",
            "x86_64-unknown-linux-musl": "nvim-linux-x86_64.tar.gz",
            "aarch64-unknown-linux-gnu": "nvim-linux-arm64.tar.gz",
            "aarch64-unknown-linux-musl": "nvim-linux-arm64.tar.gz",
            "armv7-unknown-linux-gnueabihf": None,
            "armv7-unknown-linux-musleabihf": None,
            "x86_64-apple-darwin": "nvim-macos-x86_64.tar.gz",
            "aarch64-apple-darwin": "nvim-macos-arm64.tar.gz",
        },
    )


def test_asset_selection_perapp_ppt_gitlab() -> None:
    repo = "https://gitlab.com/perapp/ppt"
    release = make_release(
        "v0.0.4",
        [
            "ppt-linux.tar.gz",
        ],
    )
    assert_expected(
        repo,
        release,
        {
            "x86_64-unknown-linux-gnu": "ppt-linux.tar.gz",
            "x86_64-unknown-linux-musl": "ppt-linux.tar.gz",
            "aarch64-unknown-linux-gnu": "ppt-linux.tar.gz",
            "aarch64-unknown-linux-musl": "ppt-linux.tar.gz",
            "armv7-unknown-linux-gnueabihf": "ppt-linux.tar.gz",
            "armv7-unknown-linux-musleabihf": "ppt-linux.tar.gz",
            "x86_64-apple-darwin": None,
            "aarch64-apple-darwin": None,
        },
    )


def test_asset_selection_sharkdp_bat() -> None:
    repo = "https://github.com/sharkdp/bat"
    release = make_release(
        "v0.26.1",
        [
            "bat-v0.26.1-x86_64-unknown-linux-gnu.tar.gz",
            "bat-v0.26.1-x86_64-unknown-linux-musl.tar.gz",
            "bat-v0.26.1-aarch64-unknown-linux-gnu.tar.gz",
            "bat-v0.26.1-aarch64-unknown-linux-musl.tar.gz",
            "bat-v0.26.1-arm-unknown-linux-gnueabihf.tar.gz",
            "bat-v0.26.1-arm-unknown-linux-musleabihf.tar.gz",
            "bat-v0.26.1-x86_64-apple-darwin.tar.gz",
            "bat-v0.26.1-aarch64-apple-darwin.tar.gz",
        ],
    )
    assert_expected(
        repo,
        release,
        {
            "x86_64-unknown-linux-gnu": "bat-v0.26.1-x86_64-unknown-linux-gnu.tar.gz",
            "x86_64-unknown-linux-musl": "bat-v0.26.1-x86_64-unknown-linux-musl.tar.gz",
            "aarch64-unknown-linux-gnu": "bat-v0.26.1-aarch64-unknown-linux-gnu.tar.gz",
            "aarch64-unknown-linux-musl": "bat-v0.26.1-aarch64-unknown-linux-musl.tar.gz",
            "armv7-unknown-linux-gnueabihf": "bat-v0.26.1-arm-unknown-linux-gnueabihf.tar.gz",
            "armv7-unknown-linux-musleabihf": "bat-v0.26.1-arm-unknown-linux-musleabihf.tar.gz",
            "x86_64-apple-darwin": "bat-v0.26.1-x86_64-apple-darwin.tar.gz",
            "aarch64-apple-darwin": "bat-v0.26.1-aarch64-apple-darwin.tar.gz",
        },
    )


def test_asset_selection_zellij_org_zellij() -> None:
    repo = "https://github.com/zellij-org/zellij"
    release = make_release(
        "v0.44.1",
        [
            "zellij-no-web-x86_64-unknown-linux-musl.tar.gz",
            "zellij-aarch64-unknown-linux-musl.tar.gz",
            "zellij-no-web-x86_64-apple-darwin.tar.gz",
            "zellij-aarch64-apple-darwin.tar.gz",
        ],
    )
    assert_expected(
        repo,
        release,
        {
            "x86_64-unknown-linux-gnu": "zellij-no-web-x86_64-unknown-linux-musl.tar.gz",
            "x86_64-unknown-linux-musl": "zellij-no-web-x86_64-unknown-linux-musl.tar.gz",
            "aarch64-unknown-linux-gnu": "zellij-aarch64-unknown-linux-musl.tar.gz",
            "aarch64-unknown-linux-musl": "zellij-aarch64-unknown-linux-musl.tar.gz",
            "armv7-unknown-linux-gnueabihf": None,
            "armv7-unknown-linux-musleabihf": None,
            "x86_64-apple-darwin": "zellij-no-web-x86_64-apple-darwin.tar.gz",
            "aarch64-apple-darwin": "zellij-aarch64-apple-darwin.tar.gz",
        },
    )
