"""Manual public HTTPS updates; no Git, credentials, packages or script execution."""
import ast
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import shutil
import stat
import sys
import tempfile
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import build_opener, HTTPRedirectHandler, Request

REPOSITORY = "mcann1423/windows-overlays"
API = "https://api.github.com/repos/" + REPOSITORY
RAW = "https://raw.githubusercontent.com/" + REPOSITORY
FILES = ("overlay_updater.py", "clock_overlay_v3.py", "ip_overlay.py",
         "cchl_cal_overlay.py", "ceel_cal_overlay.py", "README.md",
         "calendar_config.example.json")
STATE = ".overlay-update.json"
LOCK = ".overlay-update.lock"
BACKUPS = ".overlay-update-backups"
MAX_FILE = 1024 * 1024
TIMEOUT = 15
SHA = re.compile(r"[0-9a-f]{40}$")


class UpdateError(Exception):
    """A sanitized, user-actionable update failure."""


def valid_url(url):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in
            {"api.github.com", "raw.githubusercontent.com"} or
            parsed.username or parsed.password or parsed.port not in (None, 443)
            or parsed.fragment):
        raise UpdateError("Blocked an unexpected download host or non-HTTPS URL.")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Canonical public endpoints need no redirects. Fail closed.
        raise UpdateError("GitHub redirected a download. Retry later or update manually.")


def download(url, limit=MAX_FILE):
    valid_url(url)
    request = Request(url, headers={"User-Agent": "windows-overlays-updater",
                                   "Accept": "application/vnd.github+json",
                                   "Accept-Encoding": "identity"})
    try:
        started = time.monotonic()
        with build_opener(NoRedirect()).open(request, timeout=TIMEOUT) as response:
            valid_url(response.geturl())
            if response.geturl() != url or response.status != 200:
                raise UpdateError("Unexpected GitHub download response.")
            length = response.headers.get("Content-Length")
            if length and (not length.isdigit() or int(length) > limit):
                raise UpdateError("GitHub response exceeded the download size limit.")
            chunks, size = [], 0
            while True:
                chunk = response.read1(min(65536, limit + 1 - size))
                size += len(chunk)
                if size > limit or time.monotonic() - started > 45:
                    raise UpdateError("GitHub download exceeded its size or time limit.")
                if not chunk:
                    break
                chunks.append(chunk)
            return b"".join(chunks)
    except HTTPError as error:
        if error.code in (403, 429):
            raise UpdateError("GitHub rate limit or access restriction. Wait and retry later; no sign-in is required.") from None
        if error.code == 404:
            raise UpdateError("Published update not found (404). Retry later or check the public repository.") from None
        raise UpdateError("GitHub download failed (HTTP %s). Retry later." % error.code) from None
    except (URLError, OSError, TimeoutError):
        raise UpdateError("Cannot download from GitHub. Check internet access, TLS certificates and firewall; retry later.") from None


def decode_json(data):
    try:
        return json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeError):
        raise UpdateError("Invalid update metadata; nothing was installed.") from None


def digest(data):
    return hashlib.sha256(data).hexdigest()


def blob_digest(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + bytes([0]) + data).hexdigest()


def validate_content(name, data):
    try:
        text = data.decode("utf-8-sig")
        if not text.strip() or chr(0) in text:
            raise ValueError()
        if name.endswith(".py"):
            tree = ast.parse(text, filename=name)  # Parse only; never import/execute.
            if not tree.body:
                raise ValueError()
        elif name.endswith(".json"):
            example = json.loads(text)
            if (set(example) != {"cchl_ical_url", "ceel_ical_url"} or
                    any(not isinstance(v, str) or v != "YOUR_GOOGLE_CALENDAR_SECRET_ICAL_URL"
                        for v in example.values())):
                raise ValueError()
        elif not text.startswith("# Windows desktop overlays"):
            raise ValueError()
    except (ValueError, UnicodeError, SyntaxError, TypeError, AttributeError):
        raise UpdateError("Invalid published content: " + name) from None


class FolderUpdater:
    def __init__(self, directory):
        self.directory = Path(directory).resolve(strict=True)
        self.recovery_needed = False

    def path(self, name):
        # Names originate only in fixed constants, never remote paths.
        if name not in (*FILES, STATE, LOCK, BACKUPS):
            raise UpdateError("Unsafe update path.")
        path = self.directory / name
        for entry in self.directory.iterdir():
            if entry.name.rstrip(" .").casefold() == name.casefold() and entry.name != name:
                raise UpdateError("Ambiguous local filename: " + name)
        try:
            info = path.lstat()
        except FileNotFoundError:
            return path
        if (stat.S_ISLNK(info.st_mode) or
                getattr(info, "st_file_attributes", 0) & 0x400 or
                (name != BACKUPS and not stat.S_ISREG(info.st_mode)) or
                (name == BACKUPS and not stat.S_ISDIR(info.st_mode))):
            raise UpdateError("Unsafe local path (link or wrong file type): " + name)
        return path

    def snapshot(self):
        result = {}
        for name in (*FILES, STATE):
            path = self.path(name)
            if path.exists() and path.stat().st_size > MAX_FILE:
                raise UpdateError("Local file too large; preserve and reconcile manually: " + name)
            result[name] = path.read_bytes() if path.exists() else None
        return result

    @contextmanager
    def locked(self):
        path = self.path(LOCK)
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise UpdateError("Another overlay update is running or was interrupted. See README lock/recovery steps.") from None
        os.close(fd)
        try:
            yield
        finally:
            if not self.recovery_needed:
                path.unlink()

    def fetch(self):
        commit = decode_json(download(API + "/commits/main"))
        sha = commit.get("sha") if isinstance(commit, dict) else None
        if not isinstance(sha, str) or not SHA.fullmatch(sha):
            raise UpdateError("Invalid published commit SHA.")
        tree = decode_json(download(API + "/git/trees/" + sha))
        if not isinstance(tree, dict) or tree.get("truncated") is not False or not isinstance(tree.get("tree"), list):
            raise UpdateError("Invalid or truncated published file list.")
        entries = {}
        for entry in tree["tree"]:
            if not isinstance(entry, dict):
                raise UpdateError("Invalid published file list.")
            name = entry.get("path")
            if not isinstance(name, str):
                raise UpdateError("Invalid published path.")
            if name in FILES:
                if name in entries:
                    raise UpdateError("Duplicate published file.")
                entries[name] = entry
        if set(entries) != set(FILES):
            raise UpdateError("Published update is missing required files.")
        data = {}
        for name in FILES:
            entry = entries[name]
            if (entry.get("type") != "blob" or entry.get("mode") not in ("100644", "100755") or
                    type(entry.get("size")) is not int or not 0 < entry["size"] <= MAX_FILE or
                    not isinstance(entry.get("sha"), str) or not SHA.fullmatch(entry["sha"])):
                raise UpdateError("Invalid published file metadata: " + name)
            content = download(RAW + "/" + sha + "/" + name)
            if len(content) != entry["size"] or blob_digest(content) != entry["sha"]:
                raise UpdateError("Downloaded file failed GitHub blob verification: " + name)
            validate_content(name, content)
            data[name] = content
        return sha, data

    def update(self):
        try:
            with self.locked():
                return self._update()
        except OSError:
            raise UpdateError("Update could not access the folder. Check permissions, disk space and backups before retrying.") from None

    def _update(self):
        before = self.snapshot()
        if before[STATE] is not None:
            state = decode_json(before[STATE])
            if (not isinstance(state, dict) or state.get("version") != 1 or
                    not isinstance(state.get("files"), dict) or set(state["files"]) != set(FILES) or
                    not isinstance(state.get("commit"), str) or not SHA.fullmatch(state["commit"])):
                raise UpdateError("Invalid installed baseline. Preserve it and reconcile manually; see README.")
            for name in FILES:
                if before[name] is None or digest(before[name]) != state["files"][name]:
                    raise UpdateError("Local edits or missing installed file: " + name +
                                      ". Back up and reconcile manually; nothing replaced.")
        sha, incoming = self.fetch()
        state_bytes = (json.dumps({"version": 1, "commit": sha,
                                  "files": {n: digest(incoming[n]) for n in FILES}},
                                 indent=2) + chr(10)).encode("utf-8")
        incoming[STATE] = state_bytes
        changed = [n for n in incoming if incoming[n] != before[n]]
        if not changed:
            return "Already up to date. No files changed."
        # Staging shares the target filesystem, so os.replace is per-file atomic.
        with tempfile.TemporaryDirectory(prefix=".overlay-update-stage-", dir=self.directory) as temp:
            stage = Path(temp)
            for name in changed:
                with (stage / name).open("wb") as file:
                    file.write(incoming[name])
                    file.flush()
                    os.fsync(file.fileno())
                if (stage / name).read_bytes() != incoming[name]:
                    raise UpdateError("Staged file verification failed; nothing replaced.")
            if self.snapshot() != before:
                raise UpdateError("Local files changed during download; nothing replaced. Retry when editing is finished.")
            backups = self.path(BACKUPS)
            backups.mkdir(exist_ok=True)
            backup = Path(tempfile.mkdtemp(prefix=sha[:12] + "-", dir=backups))
            for name in changed:
                if before[name] is not None:
                    with (backup / name).open("wb") as file:
                        file.write(before[name])
                        file.flush()
                        os.fsync(file.fileno())
                    if (backup / name).read_bytes() != before[name]:
                        raise UpdateError("Backup verification failed; nothing replaced.")
            journal = json.dumps({"replaced": changed,
                                  "previously_absent": [n for n in changed if before[n] is None]}, indent=2)
            with (backup / "recovery.json").open("w", encoding="utf-8") as file:
                file.write(journal)
                file.flush()
                os.fsync(file.fileno())
            if self.snapshot() != before:
                raise UpdateError("Local files changed before installation; nothing replaced.")
            replaced = []
            try:
                # Metadata is last; it never describes a partially applied update.
                for name in changed:
                    os.replace(stage / name, self.path(name))
                    replaced.append(name)
            except (OSError, UpdateError):
                failed = []
                for name in reversed(replaced):
                    try:
                        if before[name] is None:
                            self.path(name).unlink()
                        else:
                            restore = stage / name
                            shutil.copyfile(backup / name, restore)
                            os.replace(restore, self.path(name))
                    except (OSError, UpdateError):
                        failed.append(name)
                if failed:
                    self.recovery_needed = True  # Keep lock to block future updates.
                    raise UpdateError("Rollback incomplete. Do not restart overlays; restore from " + str(backup)) from None
                raise UpdateError("Install failed; previous files restored. Backups: " + str(backup)) from None
        return ("Updated successfully. Restart ALL running overlays manually. Config/fonts untouched. "
                "Previous files backed up in " + str(backup) +
                (". First-use baseline recorded." if before[STATE] is None else "."))


def update_checkout(directory):
    if sys.platform != "win32":
        raise UpdateError("Overlay updates are supported on Windows only.")
    return FolderUpdater(directory).update()


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
            results.put((False, "Update failed unexpectedly. Check folder permissions and retained backups before retrying."))

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
                "Overlay updates", "Download and replace the seven published application/documentation files? "
                "All overlays share these files. First use has no baseline: existing code, including edits, may be replaced and backed up. Later edits block updates. Config/fonts/other files are untouched. Restart all overlays manually afterward.", parent=root):
            return
        busy = True
        menu.entryconfigure(0, state="disabled", label="Checking for updates…")
        # Non-daemon: closing this window must not abandon an in-progress file transaction.
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
