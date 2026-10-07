"""Explicit, Windows-only updates using the user's existing Git installation.

No credentials, downloads, startup checks, process restarts or calendar access.
"""
import os
from pathlib import Path, PurePosixPath
import queue
import shutil
import subprocess
import sys
import threading

ORIGIN = "https://github.com/mcann1423/windows-overlays.git"
BRANCH = "main"  # Verified GitHub default branch; changes require a reviewed release.
ALLOWED_ORIGINS = {ORIGIN, ORIGIN[:-4],
                   "git@github.com:mcann1423/windows-overlays.git",
                   "ssh://git@github.com/mcann1423/windows-overlays.git"}
FONT_SUFFIXES = {".ttf", ".otf", ".ttc", ".otc", ".woff", ".woff2", ".fon",
                 ".fnt", ".pfb", ".pfm", ".pfa", ".bdf", ".pcf", ".sfd", ".dfont"}


class UpdateError(Exception):
    """A sanitized, user-actionable update failure."""


def protected(path):
    parts = PurePosixPath(path.replace("\\", "/").casefold()).parts
    # Windows ignores trailing spaces/dots in ordinary paths.
    parts = tuple(part.rstrip(" .") for part in parts)
    return any(part in {"font", "fonts", "clock_overlay.py", "clock_overlay_v2.py"}
               or (part.startswith("calendar_config") and
                   part != "calendar_config.example.json")
               or PurePosixPath(part).suffix in FONT_SUFFIXES for part in parts)


class GitUpdater:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.git = shutil.which("git")
        if not self.git:
            raise UpdateError("Git not found. Install Git for Windows, then reopen the overlay.")

    def run(self, *args, timeout=20, allowed=(0,)):
        env = os.environ.copy()
        # Do not let an unrelated launcher redirect operations into another repository.
        for key in list(env):
            if key.startswith("GIT_"):
                del env[key]
        env.update(GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never",
                   GIT_SSH_COMMAND="ssh -oBatchMode=yes -oConnectTimeout=15")
        try:
            result = subprocess.run(
                [self.git, "-c", "core.hooksPath=" + os.devnull, "-c", "submodule.recurse=false",
                 "-c", "core.fsmonitor=false", "-c", "http.followRedirects=false", *args],
                cwd=self.directory, env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            raise UpdateError("Git timed out. Check connectivity/authentication; inspect git status before retrying.") from None
        except OSError:
            raise UpdateError("Could not run Git. Check the installation and folder permissions.") from None
        if result.returncode not in allowed:
            # Never display raw Git output: remotes/helpers may include credentials.
            if args[0] in {"fetch", "ls-remote"}:
                raise UpdateError("Cannot reach the private repository. Check your network and GitHub access. "
                                  "Authenticate with Git Credential Manager in a terminal, then retry.")
            raise UpdateError("Git refused the operation. Inspect git status in a terminal; "
                              "resolve locks, permissions or local changes before retrying.")
        output = result.stdout.decode("utf-8", errors="surrogateescape")
        return (output if "-z" in args else output.strip()), result.returncode

    def text(self, *args, **kwargs):
        return self.run(*args, **kwargs)[0]

    def local_state(self):
        branch = self.text("symbolic-ref", "--quiet", "--short", "HEAD", allowed=(0, 1))
        if branch != BRANCH:
            raise UpdateError("Detached HEAD or wrong branch. Switch to the repository's main branch in a terminal.")
        if self.text("status", "--porcelain=v1", "--untracked-files=no", "--ignore-submodules=none"):
            raise UpdateError("Tracked files have local changes. Commit or back them up and resolve them manually first.")
        for name in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply"):
            marker = Path(self.text("rev-parse", "--git-path", name))
            if not marker.is_absolute():
                marker = self.directory / marker
            if marker.exists():
                raise UpdateError("A Git merge/rebase is in progress. Finish it manually first.")
        # Skip-worktree / assume-unchanged can hide modified tracked files.
        entries = self.text("ls-files", "-v", "-z").split("\0")
        if any(entry and (entry[0].islower() or entry[0] == "S") for entry in entries):
            raise UpdateError("Tracked files have skip-worktree/assume-unchanged flags. Resolve these in Git first.")
        return self.text("rev-parse", "HEAD")

    def update(self):
        if not (self.directory / ".git").exists():
            raise UpdateError("This is not a Git clone. Follow the README to clone into a new folder; keep your local files.")
        if Path(self.text("rev-parse", "--show-toplevel")).resolve() != self.directory:
            raise UpdateError("The overlay folder must be the root of its own Git clone.")
        # Reject URL rewriting as well as additional fetch URLs before contacting anything.
        raw = self.text("config", "--get-all", "remote.origin.url", allowed=(0, 1)).splitlines()
        effective = self.text("remote", "get-url", "--all", "origin", allowed=(0, 2, 128)).splitlines()
        if len(raw) != 1 or raw != effective or raw[0] not in ALLOWED_ORIGINS:
            raise UpdateError("Wrong origin or URL rewrite. Expected the trusted mcann1423/windows-overlays GitHub repository.")
        before = self.local_state()
        # Serialize updater instances across the four independent overlay processes.
        lock = Path(self.text("rev-parse", "--git-path", "overlay-update.lock"))
        if not lock.is_absolute():
            lock = self.directory / lock
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise UpdateError("Another overlay update is running. If one crashed, verify Git is idle before removing .git/overlay-update.lock.") from None
        try:
            os.close(fd)
            head = self.text("ls-remote", "--symref", raw[0], "HEAD", timeout=60)
            if f"ref: refs/heads/{BRANCH}\tHEAD" not in head.splitlines():
                raise UpdateError("The remote default branch changed. Update manually after reviewing the repository.")
            self.text("fetch", "--no-tags", "--no-recurse-submodules", "--refmap=", raw[0],
                      f"refs/heads/{BRANCH}", timeout=90)
            target = self.text("rev-parse", "--verify", "FETCH_HEAD^{commit}")
            # Check entire candidate tree, not only changed files. Never let ignored
            # config/fonts/legacy paths become tracked (Git may overwrite ignored files).
            tree = self.text("ls-tree", "-r", "-z", target)
            paths = []
            for entry in tree.split("\0"):
                if not entry:
                    continue
                meta, path = entry.split("\t", 1)
                if protected(path) or meta.split()[0] not in {"100644", "100755"}:
                    raise UpdateError("Update blocked: upstream contains protected local paths, symlinks or submodules. Nothing was applied.")
                components = path.split("/")
                if any(part != part.rstrip(" .") or ":" in part or "\\" in part for part in components):
                    raise UpdateError("Update blocked: upstream has ambiguous Windows paths.")
                folded = path.casefold()
                if folded in paths:
                    raise UpdateError("Update blocked: upstream has case-colliding Windows paths.")
                paths.append(folded)
            # Protect ALL ignored/untracked local files, including Windows case collisions
            # and file/directory replacement, before merge touches the working tree.
            local = self.text("ls-files", "--others", "-z").split("\0")
            for name in filter(None, local):
                name = name.casefold().rstrip("/")
                if any(name == p or name.startswith(p + "/") or p.startswith(name + "/") for p in paths):
                    raise UpdateError("Update blocked: upstream would collide with an untracked or ignored local file. Move/back it up manually first.")
            if self.local_state() != before:
                raise UpdateError("Repository changed during the check. Retry after other Git operations finish.")
            if target == before:
                return "Already up to date. No files changed."
            if self.run("merge-base", "--is-ancestor", before, target, allowed=(0, 1))[1]:
                raise UpdateError("Local branch is ahead of or diverged from GitHub. Reconcile it manually; no reset or merge was performed.")
            self.text("merge", "--ff-only", "--no-edit", "--no-autostash", target, timeout=60)
            return ("Updated successfully. Restart ALL running overlays manually to apply the new code. "
                    "No overlays were stopped; local config and fonts were preserved.")
        finally:
            lock.unlink()


def update_checkout(directory):
    if sys.platform != "win32":
        raise UpdateError("Overlay updates are supported on Windows only.")
    return GitUpdater(directory).update()


def attach_update_menu(root, script_file):
    """Add only a right-click binding. All Tk work stays on the GUI thread."""
    import tkinter as tk
    from tkinter import messagebox

    menu = tk.Menu(root, tearoff=False)
    results = queue.Queue()
    busy = False

    def worker():
        try:
            results.put((True, update_checkout(Path(script_file).resolve().parent)))
        except UpdateError as error:
            results.put((False, str(error)))
        except Exception:
            results.put((False, "Update failed unexpectedly. Inspect git status in a terminal before retrying."))

    def poll():
        nonlocal busy
        try:
            success, message = results.get_nowait()
        except queue.Empty:
            root.after(100, poll)
            return
        busy = False
        menu.entryconfigure(0, state="normal", label="Check for updates…")
        (messagebox.showinfo if success else messagebox.showerror)("Overlay updates", message, parent=root)

    def start():
        nonlocal busy
        if busy or not messagebox.askyesno(
                "Overlay updates", "Check GitHub and apply a clean fast-forward update to this folder? "
                "All four overlays share these files. Restart them manually afterward.", parent=root):
            return
        busy = True
        menu.entryconfigure(0, state="disabled", label="Checking for updates…")
        # Non-daemon: closing this window must not abandon an in-progress Git write.
        threading.Thread(target=worker, daemon=False).start()
        root.after(100, poll)

    def popup(event):
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    menu.add_command(label="Check for updates…", command=start)
    root.bind("<Button-3>", popup, add="+")
    return menu
