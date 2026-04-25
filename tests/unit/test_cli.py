from __future__ import annotations

import io
import os
import sys
import tarfile
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from ppt import __main__ as ppt_main


class FakeReleaseStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.latest: dict[str, str] = {}
        self.archives: dict[tuple[str, str], Path] = {}

    def add_release(
        self,
        repo: str,
        version: str,
        binaries: dict[str, str],
        *,
        asset_name: str | None = None,
    ) -> None:
        slug = repo.split("/")[-1]
        archive_name = asset_name or f"{slug}-{version}-linux-x86_64.tar.gz"
        archive_path = self.root / archive_name
        create_archive(archive_path, slug, binaries)
        self.archives[(repo, version)] = archive_path
        self.latest[repo] = version

    def fetch_release(self, repo: str, version: str | None) -> dict:
        resolved_version = version or self.latest[repo]
        archive_path = self.archives[(repo, resolved_version)]
        return {
            "tag_name": resolved_version,
            "assets": [
                {
                    "name": archive_path.name,
                    "browser_download_url": f"https://example.invalid/{archive_path.name}",
                }
            ],
        }

    def download_asset(self, _cache_dir: Path, asset: dict) -> Path:
        return self.root / asset["name"]


def create_archive(archive_path: Path, slug: str, binaries: dict[str, str]) -> None:
    with tarfile.open(archive_path, "w:gz") as archive:
        root_dir = f"{slug}"
        root_info = tarfile.TarInfo(root_dir)
        root_info.type = tarfile.DIRTYPE
        root_info.mode = 0o755
        archive.addfile(root_info)

        dir_info = tarfile.TarInfo(f"{root_dir}/bin")
        dir_info.type = tarfile.DIRTYPE
        dir_info.mode = 0o755
        archive.addfile(dir_info)

        for name, body in binaries.items():
            data = body.encode("utf-8")
            info = tarfile.TarInfo(f"{root_dir}/bin/{name}")
            info.size = len(data)
            info.mode = 0o755
            archive.addfile(info, io.BytesIO(data))


class CliTestCase(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.home = self.root / "home"
        self.config = self.root / "config"
        self.home.mkdir()
        self.config.mkdir()
        self.releases = FakeReleaseStore(self.root / "releases")
        self.releases.root.mkdir()
        self.platform = ppt_main.PlatformInfo(os_name="linux", vendor="unknown", arch="x86_64", env="gnu")

    def run_ppt(self, *args: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        env = {
            "PPT_HOME": str(self.home),
            "PPT_CONFIG_DIR": str(self.config),
        }
        with patch.dict(os.environ, env, clear=False):
            with patch.object(sys, "argv", ["ppt", *args]):
                with patch.object(ppt_main, "detect_platform", return_value=self.platform):
                    with patch.object(ppt_main, "fetch_release", side_effect=self.releases.fetch_release):
                        with patch.object(
                            ppt_main,
                            "download_asset",
                            side_effect=self.releases.download_asset,
                        ):
                            with redirect_stdout(stdout), redirect_stderr(stderr):
                                code = ppt_main.main()
        return code, stdout.getvalue(), stderr.getvalue()

    def assert_link_target_contains(self, link_path: Path, fragment: str) -> None:
        self.assertTrue(link_path.is_symlink(), f"{link_path} is not a symlink")
        target = link_path.resolve(strict=True)
        self.assertIn(fragment, str(target))


class TestCliFlows(CliTestCase):
    def test_platform_prints_rust_style_quadruple(self) -> None:
        code, stdout, stderr = self.run_ppt("platform")

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(stdout.strip(), "x86_64-unknown-linux-gnu")

    def test_add_installs_and_records_lock(self) -> None:
        repo = "https://github.com/neovim/neovim"
        self.releases.add_release(repo, "v1.0.0", {"nvim": "#!/bin/sh\necho nvim v1\n"})

        code, stdout, stderr = self.run_ppt("add", repo)

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertIn("installed neovim v1.0.0", stdout)
        self.assertIn('locked = "v1.0.0"', (self.config / "packages.toml").read_text())
        self.assert_link_target_contains(self.home / "bin" / "nvim", "v1.0.0")

    def test_add_accepts_constraint_and_prefix_short_options(self) -> None:
        repo = "https://github.com/neovim/neovim"
        self.releases.add_release(repo, "v1.0.0", {"nvim": "#!/bin/sh\necho nvim v1\n"})

        code, stdout, stderr = self.run_ppt("add", repo, "-c", "v1.0.0", "-p", "src-")

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertIn("installed neovim v1.0.0", stdout)
        config = (self.config / "packages.toml").read_text()
        self.assertIn('constraint = "v1.0.0"', config)
        self.assertIn('prefix = "src-"', config)
        self.assert_link_target_contains(self.home / "bin" / "src-nvim", "v1.0.0")

    def test_prefix_relinks_existing_install(self) -> None:
        repo = "https://github.com/neovim/neovim"
        self.releases.add_release(repo, "v1.0.0", {"nvim": "#!/bin/sh\necho nvim v1\n"})
        self.run_ppt("add", repo)

        code, stdout, stderr = self.run_ppt("prefix", repo, "src-")

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertIn("set prefix", stdout)
        self.assertFalse((self.home / "bin" / "nvim").exists())
        self.assert_link_target_contains(self.home / "bin" / "src-nvim", "v1.0.0")
        self.assertIn('prefix = "src-"', (self.config / "packages.toml").read_text())

    def test_sync_installs_from_shared_config(self) -> None:
        repo = "https://github.com/neovim/neovim"
        self.releases.add_release(repo, "v2.0.0", {"nvim": "#!/bin/sh\necho nvim v2\n"})
        (self.config / "packages.toml").write_text(
            '# Managed by ppt\n\n[[package]]\nrepo = "https://github.com/neovim/neovim"\nlocked = "v2.0.0"\nprefix = "src-"\n',
            encoding="utf-8",
        )

        code, stdout, stderr = self.run_ppt("sync")

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertIn("installed neovim v2.0.0", stdout)
        self.assert_link_target_contains(self.home / "bin" / "src-nvim", "v2.0.0")

    def test_sync_suspends_progress_while_installing(self) -> None:
        repo = "https://github.com/neovim/neovim"
        (self.config / "packages.toml").write_text(
            '# Managed by ppt\n\n[[package]]\nrepo = "https://github.com/neovim/neovim"\nlocked = "v2.0.0"\n',
            encoding="utf-8",
        )

        class FakeProgress:
            def __init__(self) -> None:
                self.running = True
                self.events: list[str] = []

            def __enter__(self) -> "FakeProgress":
                return self

            def __exit__(self, *exc: object) -> None:
                self.running = False

            def add_task(self, *_args: object, **_kwargs: object) -> int:
                return 1

            def update(self, *_args: object, **_kwargs: object) -> None:
                pass

            def advance(self, *_args: object, **_kwargs: object) -> None:
                pass

            def stop(self) -> None:
                self.events.append("stop")
                self.running = False

            def start(self) -> None:
                self.events.append("start")
                self.running = True

        progress = FakeProgress()
        installing_states: list[bool] = []

        def fake_install(*_args: object, **_kwargs: object) -> str:
            installing_states.append(progress.running)
            return "installed neovim v2.0.0"

        with patch.object(ppt_main, "package_progress", return_value=progress):
            with patch.object(ppt_main, "install_package", side_effect=fake_install):
                code, stdout, stderr = self.run_ppt("sync")

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertIn("installed neovim v2.0.0", stdout)
        self.assertEqual(installing_states, [False])
        self.assertEqual(progress.events, ["stop", "start"])

    def test_upgrade_moves_unconstrained_package_to_new_release(self) -> None:
        repo = "https://github.com/neovim/neovim"
        self.releases.add_release(repo, "v1.0.0", {"nvim": "#!/bin/sh\necho nvim v1\n"})
        self.run_ppt("add", repo)
        self.releases.add_release(repo, "v2.0.0", {"nvim": "#!/bin/sh\necho nvim v2\n"})

        code, stdout, stderr = self.run_ppt("upgrade")

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertIn("installed neovim v2.0.0", stdout)
        self.assertIn('locked = "v2.0.0"', (self.config / "packages.toml").read_text())
        self.assert_link_target_contains(self.home / "bin" / "nvim", "v2.0.0")

    def test_remove_uninstalls_and_cleans_state(self) -> None:
        repo = "https://github.com/neovim/neovim"
        self.releases.add_release(repo, "v1.0.0", {"nvim": "#!/bin/sh\necho nvim v1\n"})
        self.run_ppt("add", repo)

        code, stdout, stderr = self.run_ppt("remove", "neovim")

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertIn("removed https://github.com/neovim/neovim", stdout)
        self.assertFalse((self.home / "bin" / "nvim").exists())
        self.assertFalse((self.home / "packages" / "neovim--neovim").exists())
        self.assertEqual((self.config / "packages.toml").read_text(), "# Managed by ppt\n")

    def test_update_populates_available_versions_and_list_upgradable(self) -> None:
        repo = "https://github.com/neovim/neovim"
        self.releases.add_release(repo, "v1.0.0", {"nvim": "#!/bin/sh\necho nvim v1\n"})
        self.run_ppt("add", repo)
        self.releases.add_release(repo, "v2.0.0", {"nvim": "#!/bin/sh\necho nvim v2\n"})

        code, stdout, stderr = self.run_ppt("update")
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertIn("updated neovim/neovim", stdout)
        self.assertIn("available v2.0.0", stdout)

        code, stdout, stderr = self.run_ppt("list", "--upgradable")
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertIn("PACKAGE", stdout)
        self.assertIn("AVAILABLE", stdout)
        self.assertIn("neovim/neovim", stdout)
        self.assertIn("v1.0.0", stdout)
        self.assertIn("v2.0.0", stdout)

        code, stdout, stderr = self.run_ppt("info", "neovim")
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertIn("# https://github.com/neovim/neovim", stdout)
        self.assertIn("available", stdout)
        self.assertIn("v2.0.0", stdout)
        self.assertIn("latest", stdout)
        self.assertIn("## Bin links", stdout)
        self.assertIn(f"  - {self.home / 'bin' / 'nvim'}", stdout)

    def test_info_all_platforms_shows_asset_matrix_for_locked_version(self) -> None:
        repo = "https://github.com/neovim/neovim"
        self.releases.add_release(repo, "v1.0.0", {"nvim": "#!/bin/sh\necho nvim v1\n"})
        self.run_ppt("add", repo)

        code, stdout, stderr = self.run_ppt("info", "neovim", "--all-platforms")
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertIn("# https://github.com/neovim/neovim", stdout)
        self.assertIn("## Locked assets", stdout)
        self.assertIn("PLATFORM", stdout)
        self.assertIn("ASSET", stdout)
        self.assertIn("x86_64-unknown-linux-gnu", stdout)
        # At least one platform should match the linux asset in the fake store.
        self.assertIn("neovim-v1.0.0-linux-x86_64.tar.gz", stdout)

    def test_info_without_args_shows_all_configured_packages(self) -> None:
        repo1 = "https://github.com/neovim/neovim"
        repo2 = "https://github.com/sharkdp/bat"
        self.releases.add_release(repo1, "v1.0.0", {"nvim": "#!/bin/sh\necho nvim v1\n"})
        self.releases.add_release(repo2, "v0.1.0", {"bat": "#!/bin/sh\necho bat\n"})
        self.run_ppt("add", repo1)
        self.run_ppt("add", repo2)

        code, stdout, stderr = self.run_ppt("info")
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertIn(f"# {repo1}", stdout)
        self.assertIn(f"# {repo2}", stdout)

    def test_list_default_only_shows_installed(self) -> None:
        (self.config / "packages.toml").write_text(
            '# Managed by ppt\n\n[[package]]\nrepo = "https://github.com/neovim/neovim"\n',
            encoding="utf-8",
        )
        code, stdout, stderr = self.run_ppt("list")
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(stdout.strip(), "no installed packages")

    def test_add_installs_zellij(self) -> None:
        repo = "https://github.com/zellij-org/zellij"
        self.releases.add_release(
            repo,
            "v0.44.1",
            {"zellij": "#!/bin/sh\necho zellij\n"},
            asset_name="zellij-no-web-x86_64-unknown-linux-musl.tar.gz",
        )

        code, stdout, stderr = self.run_ppt("add", repo)

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertIn("installed zellij v0.44.1", stdout)
        self.assertTrue((self.home / "bin" / "zellij").is_symlink())


class TestPackageRefResolution(CliTestCase):
    def test_remove_ambiguous_short_name_suggests_owner_repo(self) -> None:
        (self.config / "packages.toml").write_text(
            '# Managed by ppt\n\n[[package]]\nrepo = "https://github.com/perapp/bat"\n\n[[package]]\nrepo = "https://github.com/sharkdp/bat"\n',
            encoding="utf-8",
        )

        code, stdout, stderr = self.run_ppt("remove", "bat")

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("package reference is ambiguous: bat", stderr)
        self.assertIn("perapp/bat", stderr)
        self.assertIn("sharkdp/bat", stderr)
        self.assertIn("ppt remove", stderr)

    def test_remove_owner_repo_disambiguates(self) -> None:
        (self.config / "packages.toml").write_text(
            '# Managed by ppt\n\n[[package]]\nrepo = "https://github.com/perapp/bat"\n\n[[package]]\nrepo = "https://github.com/sharkdp/bat"\n',
            encoding="utf-8",
        )

        code, stdout, stderr = self.run_ppt("remove", "perapp/bat")

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertIn("removed https://github.com/perapp/bat", stdout)
        config_text = (self.config / "packages.toml").read_text(encoding="utf-8")
        self.assertIn("https://github.com/sharkdp/bat", config_text)
        self.assertNotIn("https://github.com/perapp/bat", config_text)


class TestUnlistedPackages(CliTestCase):
    def test_add_installs_unlisted_repo_by_auto_discovering_executables(self) -> None:
        repo = "https://github.com/example/hello"
        self.releases.add_release(repo, "v1.0.0", {"hello": "#!/bin/sh\necho hello\n"})

        code, stdout, stderr = self.run_ppt("add", repo)

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertIn("installed hello v1.0.0", stdout)
        self.assertTrue((self.home / "bin" / "hello").is_symlink())


class TestSourceBuilds(unittest.TestCase):
    def test_build_from_source_supports_rust_cargo_projects(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "src"
            out = root / "out"
            fake_bin = root / "fake-bin"
            log = root / "cargo-args.txt"
            src.mkdir()
            fake_bin.mkdir()
            (src / "Cargo.toml").write_text(
                '[package]\nname = "ripgrep"\nversion = "0.1.0"\nedition = "2021"\n',
                encoding="utf-8",
            )
            (src / "Cargo.lock").write_text("# lock\n", encoding="utf-8")
            cargo = fake_bin / "cargo"
            cargo.write_text(
                """#!/usr/bin/env sh
set -eu
printf '%s\n' "$*" > "$PPT_FAKE_CARGO_LOG"
root=''
while [ "$#" -gt 0 ]; do
  case "$1" in
    --root) root="$2"; shift 2 ;;
    *) shift ;;
  esac
done
mkdir -p "$root/bin"
printf '#!/usr/bin/env sh\necho rg\n' > "$root/bin/rg"
chmod 755 "$root/bin/rg"
""",
                encoding="utf-8",
            )
            cargo.chmod(0o755)

            env = {
                "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
                "PPT_FAKE_CARGO_LOG": str(log),
            }
            with patch.dict(os.environ, env, clear=False):
                ppt_main.build_from_source(src, out)

            self.assertTrue((out / "bin" / "rg").exists())
            args = log.read_text(encoding="utf-8")
            self.assertIn("install --path", args)
            self.assertIn(str(src), args)
            self.assertIn("--root", args)
            self.assertIn(str(out), args)
            self.assertIn("--locked", args)


if __name__ == "__main__":
    unittest.main()
