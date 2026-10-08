"""Manual public HTTPS updates; no Git, credentials or packages."""
# Minimal isolated child bootstrap before extension/network imports. CPython's
# built-in os/sys are safe here; no application directory is added to sys.path.
import sys
import os
if __name__ == '__main__' and sys.platform == 'win32':
    if not sys.flags.isolated or not sys.flags.no_site:
        raise SystemExit(20)
    for _name in tuple(os.environ):
        if (_name.upper().startswith(('OPENSSL_', 'SSL_', 'PYTHON')) or
                _name.upper() in {'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY', '__PYVENV_LAUNCHER__'}):
            os.environ.pop(_name, None)
    import ctypes
    _kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    _kernel.SetDefaultDllDirectories.argtypes = [ctypes.c_uint32]
    _kernel.SetDefaultDllDirectories.restype = ctypes.c_int
    if not _kernel.SetDefaultDllDirectories(0xA00):  # APPLICATION_DIR | SYSTEM32
        raise SystemExit(20)

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
from urllib.request import build_opener, HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request

REPOSITORY = "mcann1423/windows-overlays"
API = "https://api.github.com/repos/" + REPOSITORY
RAW = "https://raw.githubusercontent.com/" + REPOSITORY
FILES = ("overlay_updater.py", "overlay_windows.py", "overlay_appearance.py", "clock_overlay_v3.py", "ip_overlay.py",
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


def https_context():
    import ssl
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    if sys.platform == 'win32':
        # Explicit Windows certificate stores: never SSL_CERT_FILE/DIR or an
        # OpenSSL default CA path from the inherited user environment.
        for cert in windows_helper().machine_root_certificates():
            context.load_verify_locations(cadata=ssl.DER_cert_to_PEM_cert(cert))
    else:
        context.load_default_certs()
    return context


def download(url, limit=MAX_FILE):
    valid_url(url)
    request = Request(url, headers={"User-Agent": "windows-overlays-updater",
                                   "Accept": "application/vnd.github+json",
                                   "Accept-Encoding": "identity"})
    try:
        started = time.monotonic()
        with build_opener(NoRedirect(), ProxyHandler({}), HTTPSHandler(context=https_context())).open(request, timeout=TIMEOUT) as response:
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
    def __init__(self, directory, guard=None):
        self.directory = Path(directory).resolve(strict=True)
        self.recovery_needed = False
        self.guard = guard

    def path(self, name):
        # Names originate only in fixed constants, never remote paths.
        if name not in (*FILES, STATE, LOCK, BACKUPS):
            raise UpdateError("Unsafe update path.")
        path = self.directory / name
        self.checked(path)
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

    def checked(self, path):
        if self.guard is not None:
            try:
                self.guard.check_path(path)
            except Exception:
                raise UpdateError("Protected path trust changed or cannot be verified; stop and review installation permissions.") from None
        return path

    def temporary_directory(self, prefix, parent):
        if self.guard is None:
            return Path(tempfile.mkdtemp(prefix=prefix, dir=parent))
        # Maintained Windows Python mkdir(mode=0o700), as used by tempfile, installs a
        # user-specific DACL. Protected updates require inherited admin ACLs.
        import secrets
        for _ in range(10):
            path = self.checked(parent / (prefix + secrets.token_hex(12)))
            try:
                path.mkdir(mode=0o777)
            except FileExistsError:
                continue
            self.checked(path)
            return path
        raise UpdateError("Cannot allocate a unique protected staging directory.")

    @contextmanager
    def staging(self):
        stage = self.temporary_directory('.overlay-update-stage-', self.directory)
        try:
            yield stage
        finally:
            if self.guard is not None:
                self.guard.release_temporary(stage)
            shutil.rmtree(stage)

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
        self.checked(path)
        try:
            yield
        finally:
            if not self.recovery_needed:
                self.checked(path).unlink()

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
        with self.staging() as stage:
            for name in changed:
                with self.checked(stage / name).open("wb") as file:
                    file.write(incoming[name])
                    file.flush()
                    os.fsync(file.fileno())
                if self.checked(stage / name).read_bytes() != incoming[name]:
                    raise UpdateError("Staged file verification failed; nothing replaced.")
            if self.snapshot() != before:
                raise UpdateError("Local files changed during download; nothing replaced. Retry when editing is finished.")
            backups = self.path(BACKUPS)
            backups.mkdir(exist_ok=True)
            self.checked(backups)
            backup = self.temporary_directory(sha[:12] + "-", backups)
            self.checked(backup)
            for name in changed:
                if before[name] is not None:
                    with self.checked(backup / name).open("wb") as file:
                        file.write(before[name])
                        file.flush()
                        os.fsync(file.fileno())
                    if self.checked(backup / name).read_bytes() != before[name]:
                        raise UpdateError("Backup verification failed; nothing replaced.")
            journal = json.dumps({"replaced": changed,
                                  "previously_absent": [n for n in changed if before[n] is None]}, indent=2)
            with self.checked(backup / "recovery.json").open("w", encoding="utf-8") as file:
                file.write(journal)
                file.flush()
                os.fsync(file.fileno())
            if self.snapshot() != before:
                raise UpdateError("Local files changed before installation; nothing replaced.")
            replaced = []
            try:
                # Metadata is last; it never describes a partially applied update.
                for name in changed:
                    os.replace(self.checked(stage / name), self.path(name))
                    replaced.append(name)
            except (OSError, UpdateError):
                failed = []
                for name in reversed(replaced):
                    try:
                        if before[name] is None:
                            self.path(name).unlink()
                        else:
                            restore = stage / name
                            shutil.copyfile(self.checked(backup / name), self.checked(restore))
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


# Exit codes are the only cross-integrity result channel: no writable request,
# command, target or result files. Detailed failures are displayed by the child.
CHILD_FLAG = '--protected-update'
CHILD_RESULTS = {
    0: 'Updated successfully. Restart ALL overlays manually. Config/fonts untouched; backups are in .overlay-update-backups.',
    10: 'Already up to date. No files changed.',
}


def windows_api():
    import ctypes
    from ctypes import wintypes as w

    class ShellExecuteInfo(ctypes.Structure):
        _fields_ = [('cbSize', w.DWORD), ('fMask', w.ULONG), ('hwnd', w.HWND),
                    ('lpVerb', w.LPCWSTR), ('lpFile', w.LPCWSTR),
                    ('lpParameters', w.LPCWSTR), ('lpDirectory', w.LPCWSTR),
                    ('nShow', ctypes.c_int), ('hInstApp', w.HINSTANCE),
                    ('lpIDList', ctypes.c_void_p), ('lpClass', w.LPCWSTR),
                    ('hkeyClass', w.HKEY), ('dwHotKey', w.DWORD),
                    ('hIcon', w.HANDLE), ('hProcess', w.HANDLE)]

    shell = ctypes.WinDLL('shell32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    shell.ShellExecuteExW.argtypes = [ctypes.POINTER(ShellExecuteInfo)]
    shell.ShellExecuteExW.restype = w.BOOL
    shell.IsUserAnAdmin.argtypes = []
    shell.IsUserAnAdmin.restype = w.BOOL
    kernel.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    kernel.WaitForSingleObject.restype = w.DWORD
    kernel.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
    kernel.GetExitCodeProcess.restype = w.BOOL
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.CloseHandle.restype = w.BOOL
    return ctypes, w, ShellExecuteInfo, shell, kernel


def is_admin():
    return bool(windows_api()[3].IsUserAnAdmin())


def child_parameters(script):
    # -I removes CWD/script directory, user site, and PYTHON* environment influence.
    # -S additionally disables system .pth/sitecustomize execution; -B avoids pyc.
    import subprocess
    return subprocess.list2cmdline(['-I', '-S', '-B', str(script), CHILD_FLAG])


def run_elevated(script, interpreter):
    c, w, info_type, shell, kernel = windows_api()
    info = info_type()
    info.cbSize = c.sizeof(info)
    info.fMask = 0x40 | 0x100 | 0x400  # NOCLOSEPROCESS | NOASYNC | FLAG_NO_UI
    info.lpVerb = 'runas'
    info.lpFile = str(interpreter)
    info.lpParameters = child_parameters(script)
    info.lpDirectory = str(interpreter.parent)
    info.nShow = 0
    # Honored even with -I by CPython before our child bootstrap. ShellExecuteEx
    # has no private environment block; refuse rather than mutate the GUI env.
    if any(name in os.environ for name in ('PYTHONEXECUTABLE', '__PYVENV_LAUNCHER__')):
        raise UpdateError('Python launcher environment overrides are unsupported for elevation. Restart with the standard all-users interpreter.')
    if not shell.ShellExecuteExW(c.byref(info)):
        if c.get_last_error() == 1223:
            raise UpdateError('Administrator approval was cancelled. Nothing was installed.')
        raise UpdateError('Windows could not start the updater with administrator approval. No retry was attempted.')
    if not info.hProcess:
        raise UpdateError('Windows did not return an updater process handle. Check for a running updater before retrying.')
    try:
        # Only on the existing non-daemon worker, never Tk's thread.
        if kernel.WaitForSingleObject(info.hProcess, 0xFFFFFFFF) != 0:
            raise UpdateError('Cannot observe the updater. Check for a running updater and retained lock before retrying.')
        code = w.DWORD()
        if not kernel.GetExitCodeProcess(info.hProcess, c.byref(code)):
            raise UpdateError('Cannot read updater result. Inspect backups and lock before retrying.')
        if code.value not in CHILD_RESULTS:
            raise UpdateError('Administrator updater did not complete. See its error dialog; inspect backups and any retained lock before retrying. Do not restart overlays after incomplete rollback.')
        return CHILD_RESULTS[code.value]
    finally:
        kernel.CloseHandle(info.hProcess)


_windows_helper_module = None


def windows_helper():
    global _windows_helper_module
    if _windows_helper_module is not None:
        return _windows_helper_module
    # Explicit file loading works under -I -S without adding application sys.path.
    import importlib.util
    path = Path(__file__).parent / 'overlay_windows.py'
    spec = importlib.util.spec_from_file_location('_overlay_windows', path)
    module = importlib.util.module_from_spec(spec)
    # Load source only: never a timestamp-valid application __pycache__ file.
    # The privileged parent has validated and guarded this source path.
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    _windows_helper_module = module
    return module


def protected_install(script, interpreter):
    return windows_helper().ProtectedInstall(script, interpreter)


def elevation_required(directory):
    # Probe BEFORE lock/download/stage/replacement. Never escalate a failed
    # transaction (especially a partial write or failed rollback).
    try:
        with tempfile.TemporaryFile(prefix='.overlay-write-probe-', dir=directory):
            pass
        return False
    except PermissionError:
        return True
    except OSError:
        raise UpdateError('Cannot test folder access. Check disk space and folder availability; no elevation attempted.') from None


def elevated_main():
    if (sys.platform != 'win32' or sys.argv[1:] != [CHILD_FLAG] or
            not sys.flags.isolated or not sys.flags.no_site or not is_admin()):
        return 20
    try:
        script = Path(os.path.abspath(__file__))
        with protected_install(script, Path(sys.executable)) as guard:
            guard.release_script()
            message = FolderUpdater(script.parent, guard=guard).update()
        return 10 if message.startswith('Already up to date') else 0
    except Exception as error:
        # No Tk/site imports in the privileged process. No calendar/config read.
        import ctypes
        from ctypes import wintypes as w
        user = ctypes.WinDLL('user32', use_last_error=True)
        user.MessageBoxW.argtypes = [w.HWND, w.LPCWSTR, w.LPCWSTR, w.UINT]
        user.MessageBoxW.restype = ctypes.c_int
        message = str(error) if isinstance(error, UpdateError) else 'Protected updater refused this installation or failed. Review permissions, backups and the retained lock. Do not restart overlays after incomplete rollback.'
        user.MessageBoxW(None, message, 'Overlay updater', 0x10)
        return 20


def update_checkout(directory):
    if sys.platform != "win32":
        raise UpdateError("Overlay updates are supported on Windows only.")
    script = Path(os.path.abspath(__file__))
    directory = Path(os.path.abspath(directory))
    if directory != script.parent:
        raise UpdateError("Updater must be beside the running overlays.")
    if is_admin():
        raise UpdateError("Close administrator overlays and launch normally. Only the dedicated updater child may run elevated.")
    if not elevation_required(directory):
        return FolderUpdater(directory).update()
    try:
        with protected_install(script, Path(sys.executable)) as guard:
            guard.release_script()
            return run_elevated(script, Path(sys.executable))
    except UpdateError:
        raise
    except Exception:
        raise UpdateError("Elevation refused: installation or Python trust checks failed. Use a protected all-users Python installation and administrator-managed application folder; see README. No automatic retry.") from None


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
                "Overlay updates", "Download and replace the nine published application/documentation files? "
                "All overlays share these files. First use has no baseline: existing code, including edits, may be replaced and backed up. Later edits block updates. Config/fonts/other files are untouched. Restart all overlays manually afterward. If this folder is protected, Windows will ask for administrator approval for the updater only; overlays stay non-administrator.", parent=root):
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


if __name__ == "__main__":
    raise SystemExit(elevated_main())
