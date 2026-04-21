from __future__ import annotations

import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import tempfile
from unittest.mock import patch

from pathlib import Path

from ppt import __main__ as ppt_main


class TestShellEnv(unittest.TestCase):
    def run_ppt(self, *args: str) -> tuple[int, str, str]:
        stdout = StringIO()
        stderr = StringIO()
        with patch.object(sys, "argv", ["ppt", *args]):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = ppt_main.main()
        return code, stdout.getvalue(), stderr.getvalue()

    def test_shell_env_bash_prints_path_and_completion(self) -> None:
        code, stdout, stderr = self.run_ppt("shell-env", "--shell", "bash")
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertIn("ppt shell-env (bash)", stdout)
        self.assertIn("PPT_HOME", stdout)
        self.assertIn("complete -F _ppt", stdout)

    def test_shell_env_zsh_prints_path_and_completion(self) -> None:
        code, stdout, stderr = self.run_ppt("shell-env", "--shell", "zsh")
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertIn("ppt shell-env (zsh)", stdout)
        self.assertIn("compdef _ppt ppt", stdout)

    def test_shell_env_fish_prints_path_and_completion(self) -> None:
        code, stdout, stderr = self.run_ppt("shell-env", "--shell", "fish")
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertIn("ppt shell-env (fish)", stdout)
        self.assertIn("set -gx PATH", stdout)
        self.assertIn("complete -c ppt", stdout)

    def test_shell_env_defaults_from_shell_env_var(self) -> None:
        with patch.dict(os.environ, {"SHELL": "/bin/zsh"}, clear=False):
            code, stdout, stderr = self.run_ppt("shell-env")
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertIn("ppt shell-env (zsh)", stdout)


class TestUpdateShellConfig(unittest.TestCase):
    def run_ppt(self, *args: str) -> tuple[int, str, str]:
        stdout = StringIO()
        stderr = StringIO()
        with patch.object(sys, "argv", ["ppt", *args]):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = ppt_main.main()
        return code, stdout.getvalue(), stderr.getvalue()

    def test_update_shell_config_appends_idempotent_block(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            rc = home / ".bashrc"
            with patch.dict(os.environ, {"HOME": str(home), "SHELL": "/bin/bash"}, clear=False):
                code, stdout, stderr = self.run_ppt("update-shell-config", "--yes")
                self.assertEqual(code, 0)
                self.assertEqual(stderr, "")
                self.assertIn("added ppt shell init", stdout)
                text = rc.read_text(encoding="utf-8")
                self.assertIn("shell-env --shell bash", text)
                self.assertIn("eval", text)

                # Running again should not duplicate.
                code2, stdout2, stderr2 = self.run_ppt("update-shell-config", "--yes")
                self.assertEqual(code2, 0)
                self.assertEqual(stderr2, "")
                self.assertIn("already present", stdout2)
                text2 = rc.read_text(encoding="utf-8")
                self.assertEqual(text2.count("shell-env --shell bash"), 1)
