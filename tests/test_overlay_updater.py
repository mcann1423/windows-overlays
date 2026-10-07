"""Offline tests: real temporary Git fixtures; never import overlay applications."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
import sys
import types

import overlay_updater as updater


def git(path, *args):
    env = os.environ.copy()
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_AUTHOR_NAME="Test", GIT_AUTHOR_EMAIL="test@example.invalid",
               GIT_COMMITTER_NAME="Test", GIT_COMMITTER_EMAIL="test@example.invalid")
    return subprocess.check_output(["git", "-C", str(path), *args], env=env,
                                   stderr=subprocess.DEVNULL).decode().strip()


class CheckoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.remote = self.base / "remote"
        self.remote.mkdir()
        git(self.remote, "init", "-b", "main")
        (self.remote / "code.py").write_text("original")
        (self.remote / ".gitignore").write_text("calendar_config*\n*.ttf\nfonts/\nclock_overlay.py\nlocal*\n")
        git(self.remote, "add", ".")
        git(self.remote, "commit", "-m", "initial")
        self.local = self.base / "local"
        git(self.base, "clone", str(self.remote), str(self.local))
        git(self.local, "remote", "set-url", "origin", updater.ORIGIN)
        self.engine = updater.GitUpdater(self.local)
        original_run = self.engine.run

        def offline_run(*args, **kwargs):
            # Only network destinations are replaced; allow-list validation stays real.
            if args[0] in {"ls-remote", "fetch"}:
                args = tuple(str(self.remote) if arg == updater.ORIGIN else arg for arg in args)
            return original_run(*args, **kwargs)
        self.engine.run = offline_run
        self.before = git(self.local, "rev-parse", "HEAD")

    def commit_remote(self, path="code.py", text="updated"):
        target = self.remote / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        git(self.remote, "add", "-f", path)
        git(self.remote, "commit", "-m", "update")

    def blocked(self, message):
        with self.assertRaisesRegex(updater.UpdateError, message):
            self.engine.update()
        self.assertEqual(git(self.local, "rev-parse", "HEAD"), self.before)

    def test_fast_forward_preserves_local_files(self):
        files = {"calendar_config.json": "private fixture", "Font.ttf": "font fixture",
                 "clock_overlay.py": "legacy fixture", "fonts/nested.bin": "font data"}
        for name, value in files.items():
            path = self.local / name
            path.parent.mkdir(exist_ok=True)
            path.write_text(value)
        self.commit_remote()
        self.assertIn("Restart ALL", self.engine.update())
        self.assertEqual(git(self.local, "rev-parse", "HEAD"), git(self.remote, "rev-parse", "HEAD"))
        for name, value in files.items():
            self.assertEqual((self.local / name).read_text(), value)

    def test_no_update(self):
        self.assertIn("Already up to date", self.engine.update())

    def test_dirty(self):
        (self.local / "code.py").write_text("local edit")
        self.blocked("local changes")

    def test_staged(self):
        (self.local / "code.py").write_text("local edit")
        git(self.local, "add", "code.py")
        self.blocked("local changes")

    def test_detached(self):
        git(self.local, "checkout", "--detach")
        self.blocked("Detached")

    def test_wrong_branch(self):
        git(self.local, "checkout", "-b", "other")
        self.blocked("wrong branch")

    def test_diverged(self):
        (self.local / "local.py").write_text("local commit")
        git(self.local, "add", "-f", "local.py")
        git(self.local, "commit", "-m", "local")
        self.before = git(self.local, "rev-parse", "HEAD")
        self.commit_remote()
        self.blocked("diverged")

    def test_ahead(self):
        (self.local / "code.py").write_text("local commit")
        git(self.local, "add", ".")
        git(self.local, "commit", "-m", "local")
        self.before = git(self.local, "rev-parse", "HEAD")
        self.blocked("ahead")

    def test_protected_collision(self):
        (self.local / "calendar_config.json").write_text("private fixture")
        self.commit_remote("calendar_config.json", "upstream must not replace")
        self.blocked("protected")
        self.assertEqual((self.local / "calendar_config.json").read_text(), "private fixture")

    def test_upstream_font_rejected_even_without_local_file(self):
        self.commit_remote("FONT.TTF")
        self.blocked("protected")

    def test_ignored_collision(self):
        (self.local / "local-data").write_text("keep")
        self.commit_remote("local-data")
        self.blocked("collide")
        self.assertEqual((self.local / "local-data").read_text(), "keep")

    def test_case_collision(self):
        (self.local / "LOCAL-DATA").write_text("keep")
        self.commit_remote("local-data")
        self.blocked("collide")

    def test_directory_collision(self):
        (self.local / "local-dir").mkdir()
        (self.local / "local-dir" / "data").write_text("keep")
        self.commit_remote("local-dir")
        self.blocked("collide")

    def test_missing_origin(self):
        git(self.local, "remote", "remove", "origin")
        self.blocked("Wrong origin")

    def test_symlink_upstream(self):
        if os.name == "nt":
            self.skipTest("Symlink creation requires Windows privileges")
        (self.remote / "link").symlink_to("code.py")
        git(self.remote, "add", "link")
        git(self.remote, "commit", "-m", "symlink")
        self.blocked("symlinks")

    def test_merge_failure_preserves_local_file(self):
        self.commit_remote()
        (self.local / "calendar_config.json").write_text("private fixture")
        original = self.engine.run
        def fail(*args, **kwargs):
            if args[0] == "merge":
                raise updater.UpdateError("Git refused the operation")
            return original(*args, **kwargs)
        self.engine.run = fail
        self.blocked("refused")
        self.assertEqual((self.local / "calendar_config.json").read_text(), "private fixture")
        self.assertFalse((self.local / ".git" / "overlay-update.lock").exists())

    def test_wrong_origin(self):
        git(self.local, "remote", "set-url", "origin", "https://example.invalid/repo.git")
        self.blocked("Wrong origin")

    def test_url_rewrite(self):
        git(self.local, "config", "url.https://example.invalid/.insteadOf", "https://github.com/")
        self.blocked("URL rewrite")

    def test_default_branch_changed(self):
        git(self.remote, "branch", "-m", "different")
        self.blocked("default branch changed")

    def test_concurrent_update(self):
        (self.local / ".git" / "overlay-update.lock").touch()
        self.blocked("Another overlay")

    def test_hidden_changes(self):
        git(self.local, "update-index", "--assume-unchanged", "code.py")
        (self.local / "code.py").write_text("hidden edit")
        self.blocked("assume-unchanged")

    def test_network_failure_releases_lock(self):
        original = self.engine.run
        def fail(*args, **kwargs):
            if args[0] == "fetch":
                raise updater.UpdateError("offline")
            return original(*args, **kwargs)
        self.engine.run = fail
        self.blocked("offline")
        self.assertFalse((self.local / ".git" / "overlay-update.lock").exists())


class UnitTests(unittest.TestCase):
    def test_protected_names(self):
        for name in ["CALENDAR_CONFIG.JSON", "calendar_config.json.bak", "font/x",
                     "fonts/x", "clock_overlay_v2.py", "Nunito.TTF", "font.ttf./child"]:
            self.assertTrue(updater.protected(name), name)
        self.assertFalse(updater.protected("calendar_config.example.json"))

    def test_missing_git(self):
        with patch.object(updater.shutil, "which", return_value=None):
            with self.assertRaisesRegex(updater.UpdateError, "Git not found"):
                updater.GitUpdater(".")

    def test_not_clone(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(updater.UpdateError, "not a Git clone"):
                updater.GitUpdater(folder).update()

    def test_platform_guard(self):
        with patch.object(updater.sys, "platform", "linux"):
            with self.assertRaisesRegex(updater.UpdateError, "Windows only"):
                updater.update_checkout(".")

    def test_subprocess_timeout_and_sanitized_errors(self):
        engine = updater.GitUpdater(".")
        with patch.object(updater.subprocess, "run", side_effect=subprocess.TimeoutExpired("git", 20)):
            with self.assertRaisesRegex(updater.UpdateError, "timed out"):
                engine.run("fetch")
        result = subprocess.CompletedProcess([], 128, b"", b"sensitive token")
        with patch.object(updater.subprocess, "run", return_value=result) as run:
            with self.assertRaisesRegex(updater.UpdateError, "network and GitHub access") as caught:
                engine.run("fetch")
            self.assertNotIn("sensitive", str(caught.exception))
            kwargs = run.call_args.kwargs
            self.assertNotIn("shell", kwargs)
            self.assertEqual(kwargs["timeout"], 20)
            self.assertEqual(kwargs["env"]["GCM_INTERACTIVE"], "never")

    def test_gui_explicit_worker_and_main_thread_delivery(self):
        root, menu, dialogs = Mock(), Mock(), Mock()
        tk = types.ModuleType("tkinter")
        tk.Menu = Mock(return_value=menu)
        tk.messagebox = dialogs
        with patch.dict(sys.modules, {"tkinter": tk, "tkinter.messagebox": dialogs}), \
             patch.object(updater.threading, "Thread") as thread, \
             patch.object(updater, "update_checkout", return_value="done") as update:
            updater.attach_update_menu(root, __file__)
            update.assert_not_called()
            thread.assert_not_called()
            root.bind.assert_called_once()
            self.assertEqual(root.bind.call_args.args[0], "<Button-3>")
            self.assertEqual(root.bind.call_args.kwargs, {"add": "+"})
            start = menu.add_command.call_args.kwargs["command"]
            dialogs.askyesno.return_value = False
            start()
            thread.assert_not_called()
            dialogs.askyesno.return_value = True
            start()
            thread.return_value.start.assert_called_once()
            update.assert_not_called()
            start()  # busy: no duplicate worker
            thread.assert_called_once()
            worker = thread.call_args.kwargs["target"]
            poll = root.after.call_args.args[1]
            poll()  # queue empty, schedules next poll
            worker()
            dialogs.showinfo.assert_not_called()
            poll()
            dialogs.showinfo.assert_called_once()


if __name__ == "__main__":
    unittest.main()
