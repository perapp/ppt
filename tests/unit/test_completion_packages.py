from __future__ import annotations

import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from ppt import __main__ as ppt_main


class TestCompletePackages(unittest.TestCase):
    def run_ppt(self, *args: str, env: dict[str, str] | None = None) -> tuple[int, str, str]:
        stdout = StringIO()
        stderr = StringIO()
        with patch.dict(os.environ, env or {}, clear=False):
            with patch.object(sys, "argv", ["ppt", *args]):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = ppt_main.main()
        return code, stdout.getvalue(), stderr.getvalue()

    def test_complete_packages_outputs_owner_repo_and_unique_short_names(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            config_dir = Path(td)
            (config_dir / "packages.toml").write_text(
                """# Managed by ppt

[[package]]
repo = "https://github.com/neovim/neovim"

[[package]]
repo = "https://github.com/sharkdp/bat"

[[package]]
repo = "https://github.com/perapp/bat"
""",
                encoding="utf-8",
            )

            code, stdout, stderr = self.run_ppt(
                "_complete",
                "packages",
                env={"PPT_CONFIG_DIR": str(config_dir)},
            )
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            lines = [line for line in stdout.splitlines() if line.strip()]
            self.assertIn("neovim/neovim", lines)
            self.assertIn("neovim", lines)
            # bat is ambiguous; should not offer bare "bat".
            self.assertIn("sharkdp/bat", lines)
            self.assertIn("perapp/bat", lines)
            self.assertNotIn("bat", lines)

    def test_complete_packages_query_filters_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            config_dir = Path(td)
            (config_dir / "packages.toml").write_text(
                """# Managed by ppt

[[package]]
repo = "https://github.com/neovim/neovim"

[[package]]
repo = "https://github.com/sharkdp/fd"
""",
                encoding="utf-8",
            )

            code, stdout, stderr = self.run_ppt(
                "_complete",
                "packages",
                "--query",
                "neo",
                env={"PPT_CONFIG_DIR": str(config_dir)},
            )
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            lines = [line for line in stdout.splitlines() if line.strip()]
            self.assertIn("neovim", lines)
            self.assertIn("neovim/neovim", lines)
            self.assertNotIn("fd", lines)
            self.assertNotIn("sharkdp/fd", lines)
