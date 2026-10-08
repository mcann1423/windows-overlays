"""Fail-closed Windows installation guards (stdlib only).

Not a bootstrap trust anchor: import this only from already trusted code. Run the
preflight in the unelevated process, retain its context until the elevated child
has completed, and construct/revalidate another context in that child BEFORE any
network or update work. Launch the exact guarded python.exe with -I -S; do not use
PATH, associations, a venv, user site, or arbitrary runtime arguments.

release_script() releases all installation-file guards, not runtime or directory
guards. Call only in the elevated writer immediately before replacing files. The
unelevated parent must likewise release its installation-file guards before the
child writes (use an authenticated handshake, or validate then release before
launch and rely on protected ACLs). Directory guards and ACL checks remain active.
Trusted administrators/SYSTEM are outside the threat model; they can change ACLs.
"""
import ctypes
from ctypes import wintypes as w
import ntpath
import os
import sys


class SecurityError(Exception):
    """The installation cannot safely be used for elevated updates."""


TRUSTED = frozenset({
    "S-1-5-18", "S-1-5-32-544",
    "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464",
})
# File/directory write, append, EA, delete-child, attributes; DELETE,
# WRITE_DAC, WRITE_OWNER; GENERIC_WRITE/ALL. Unknown rights also fail closed.
READ_ONLY = 0x001200A9
FILE_ALL_ACCESS = 0x001F01FF
INHERIT_ONLY = 0x08
REPARSE = 0x400
DIRECTORY = 0x10
MANAGED = frozenset({'overlay_updater.py', 'overlay_windows.py', 'overlay_appearance.py',
                     'clock_overlay_v3.py', 'ip_overlay.py', 'cchl_cal_overlay.py',
                     'ceel_cal_overlay.py', 'readme.md', 'calendar_config.example.json',
                     '.overlay-update.json', '.overlay-update.lock', '.overlay-update-backups'})


def _trustee_label(sid):
    # Never resolve account names or disclose machine/domain/account identifiers.
    # Well-known SIDs are public constants; all other SIDs stay categorized.
    known = {
        "S-1-1-0": "Everyone", "S-1-5-11": "Authenticated Users",
        "S-1-5-32-545": "BUILTIN Users", "S-1-3-0": "CREATOR OWNER",
        "S-1-3-1": "CREATOR GROUP", "S-1-3-4": "OWNER RIGHTS",
        "S-1-5-18": "SYSTEM", "S-1-5-32-544": "Administrators",
    }
    if sid in known:
        return known[sid] + " [" + sid + "]"
    if sid in TRUSTED:
        return "TrustedInstaller"
    if isinstance(sid, str) and sid.startswith("S-1-5-21-"):
        return "account/domain SID (redacted)"
    return "other SID (redacted)"


def _file_rights(mask):
    # Win32 file/directory generic mapping; retain unknown bits to fail closed.
    specific = mask & ~0xF0000000
    for generic, rights in ((0x80000000, 0x00120089),
                            (0x40000000, 0x00120116),
                            (0x20000000, 0x001200A0),
                            (0x10000000, FILE_ALL_ACCESS)):
        if mask & generic:
            specific |= rights
    return specific


def _acl_policy(owner, aces, directory, inheritance=False, ancestor=False):
    if owner not in TRUSTED:
        raise SecurityError("Installation object has an untrusted owner (%s)." % _trustee_label(owner))
    if aces is None:
        raise SecurityError("Installation object has a missing or NULL DACL.")
    inherited_admin = False
    for index, (kind, flags, mask, sid) in enumerate(aces):
        # Only conventional ALLOW and DENY ACEs are understood. No callback,
        # object, conditional, compound, or unknown ACE is interpreted optimistically.
        if kind not in (0, 1) or flags & ~0x1F:
            raise SecurityError("Unsupported installation ACL entry.")
        # Ancestors may permit creation of unrelated new children. Retained
        # handles prevent replacement of our existing child directories; DELETE_CHILD,
        # WRITE_DAC/OWNER and all other mutation rights remain forbidden.
        allowed = READ_ONLY | (0x4 if ancestor else 0)
        effective = not flags & INHERIT_ONLY
        rights = _file_rights(mask)
        # INHERIT_ONLY never controls access to this object, regardless of SID.
        # Every existing runtime/managed descendant is independently inspected.
        if kind == 0 and sid not in TRUSTED and rights & ~allowed and effective:
            raise SecurityError(
                "Installation ACL grants untrusted write rights "
                "(ACE %d, mask 0x%08X, flags 0x%02X; trustee %s; %s; %s)." %
                (index, mask, flags, _trustee_label(sid),
                 "applies to object" if effective else "inherit-only",
                 "ancestor directory" if ancestor else "directory" if directory else "file"))
        # Writable update directories must also be safe BEFORE child creation:
        # an inherit-only grant to an untrusted principal could expose a new stage
        # or file before its post-create check. CREATOR OWNER is a placeholder,
        # not OWNER RIGHTS: elevated creates must still pass trusted-owner and
        # effective-DACL checks afterward. Never treat other SIDs as placeholders.
        if (directory and inheritance and kind == 0 and flags & 3
                and sid not in TRUSTED and sid != "S-1-3-0"
                and rights & ~READ_ONLY):
            raise SecurityError(
                "Update directory ACL would grant untrusted child write rights "
                "(ACE %d, mask 0x%08X, flags 0x%02X; trustee %s)." %
                (index, mask, flags, _trustee_label(sid)))
        # Require an ordinary inheritable full-control grant to a trusted
        # principal. CREATOR OWNER is intentionally not accepted.
        if (kind == 0 and sid in TRUSTED and flags & 3 == 3
                and not flags & 4 and rights & FILE_ALL_ACCESS == FILE_ALL_ACCESS):
            inherited_admin = True
    if directory and inheritance and not inherited_admin:
        raise SecurityError("Update directory lacks safe inheritable full control.")


def _path(value):
    p = os.fspath(value)
    # No UNC/device namespace, ADS, relative path, DOS aliases, dot segments,
    # trailing spaces/dots or separators ambiguities. Do not resolve symlinks.
    if (not isinstance(p, str) or len(p) < 3 or not p[0].isascii()
            or not p[0].isalpha() or p[1:3] != ":\\"
            or "/" in p or "\x00" in p):
        raise SecurityError("A canonical local drive path is required.")
    parts = p[3:].split("\\") if p[3:] else []
    for part in parts:
        stem = part.split(".", 1)[0].upper()
        if (not part or part in (".", "..") or part[-1:] in (" ", ".")
                or any(c in part for c in ':*?<>|"') or "~" in part
                or stem in {"CON", "PRN", "AUX", "NUL"}
                or stem in {"COM" + str(i) for i in range(10)}
                or stem in {"LPT" + str(i) for i in range(10)}):
            raise SecurityError("Unsafe or ambiguous Windows path.")
    return ntpath.normcase(p)


def _under(path, root):
    return path == root or path.startswith(root.rstrip("\\") + "\\")


class _Info(ctypes.Structure):
    _fields_ = [("attrs", w.DWORD), ("created", w.FILETIME),
                ("accessed", w.FILETIME), ("written", w.FILETIME),
                ("volume", w.DWORD), ("sizehi", w.DWORD),
                ("sizelo", w.DWORD), ("links", w.DWORD),
                ("indexhi", w.DWORD), ("indexlo", w.DWORD)]


class _Native:
    def __init__(self):
        if os.name != "nt":
            raise SecurityError("Protected installation checks require Windows.")
        self.k = ctypes.WinDLL("kernel32", use_last_error=True)
        self.a = ctypes.WinDLL("advapi32", use_last_error=True)
        signatures = [
            (self.k, "CreateFileW", [w.LPCWSTR, w.DWORD, w.DWORD, w.LPVOID, w.DWORD, w.DWORD, w.HANDLE], w.HANDLE),
            (self.k, "CloseHandle", [w.HANDLE], w.BOOL),
            (self.k, "GetFileInformationByHandle", [w.HANDLE, ctypes.POINTER(_Info)], w.BOOL),
            (self.k, "LocalFree", [w.HLOCAL], w.HLOCAL),
            (self.k, "GetDriveTypeW", [w.LPCWSTR], w.UINT),
            (self.k, "GetVolumeInformationW", [w.LPCWSTR, w.LPWSTR, w.DWORD, ctypes.POINTER(w.DWORD), ctypes.POINTER(w.DWORD), ctypes.POINTER(w.DWORD), w.LPWSTR, w.DWORD], w.BOOL),
            (self.a, "GetSecurityInfo", [w.HANDLE, ctypes.c_int, w.DWORD, ctypes.POINTER(w.LPVOID), ctypes.POINTER(w.LPVOID), ctypes.POINTER(w.LPVOID), ctypes.POINTER(w.LPVOID), ctypes.POINTER(w.LPVOID)], w.DWORD),
            (self.a, "ConvertSidToStringSidW", [w.LPVOID, ctypes.POINTER(w.LPWSTR)], w.BOOL),
            (self.a, "IsValidSid", [w.LPVOID], w.BOOL),
            (self.a, "GetLengthSid", [w.LPVOID], w.DWORD),
            (self.a, "IsValidAcl", [w.LPVOID], w.BOOL),
            (self.a, "GetAce", [w.LPVOID, w.DWORD, ctypes.POINTER(w.LPVOID)], w.BOOL),
        ]
        for dll, name, args, result in signatures:
            fn = getattr(dll, name)
            fn.argtypes, fn.restype = args, result

    def loaded_runtime(self):
        self.k.GetModuleFileNameW.argtypes = [w.HMODULE, w.LPWSTR, w.DWORD]
        self.k.GetModuleFileNameW.restype = w.DWORD
        buffer = ctypes.create_unicode_buffer(32768)
        size = self.k.GetModuleFileNameW(ctypes.c_void_p(sys.dllhandle), buffer, len(buffer))
        if not size or size >= len(buffer):
            raise SecurityError("Cannot locate loaded CPython runtime DLL.")
        return _path(buffer.value)

    def volume(self, root):
        flags = w.DWORD()
        fs = ctypes.create_unicode_buffer(32)
        if (self.k.GetDriveTypeW(root) != 3 or not self.k.GetVolumeInformationW(
                root, None, 0, None, None, ctypes.byref(flags), fs, len(fs))
                or fs.value.upper() != "NTFS" or not flags.value & 8):
            raise SecurityError("Only local fixed NTFS volumes with persistent ACLs are supported.")

    def open(self, path, directory):
        # Directories permit content writes but not rename/delete. Files permit
        # only readers: existing write handles cause this open to fail as well.
        handle = self.k.CreateFileW(path, 0x00020080 if directory else 0x80000000,
                                   3 if directory else 1,
                                   None, 3, 0x02200000, None)
        if handle == ctypes.c_void_p(-1).value:
            error = ctypes.get_last_error()
            if error in (2, 3):
                raise FileNotFoundError(path)
            raise SecurityError("Cannot acquire protected installation handle (Windows error %d)." % error)
        return handle

    def close(self, handle):
        self.k.CloseHandle(handle)

    def sid(self, pointer):
        if not pointer or not self.a.IsValidSid(pointer):
            raise SecurityError("Invalid installation SID.")
        value = w.LPWSTR()
        if not self.a.ConvertSidToStringSidW(pointer, ctypes.byref(value)):
            raise SecurityError("Cannot inspect installation SID.")
        try:
            return value.value
        finally:
            self.k.LocalFree(ctypes.cast(value, w.LPVOID))

    def inspect(self, handle):
        info = _Info()
        if not self.k.GetFileInformationByHandle(handle, ctypes.byref(info)):
            raise SecurityError("Cannot inspect installation identity.")
        if info.attrs & REPARSE or (not info.attrs & DIRECTORY and info.links != 1):
            raise SecurityError("Reparse points and hard-linked files are not permitted.")
        owner, dacl, sd = w.LPVOID(), w.LPVOID(), w.LPVOID()
        status = self.a.GetSecurityInfo(handle, 1, 5, ctypes.byref(owner), None,
                                       ctypes.byref(dacl), None, ctypes.byref(sd))
        if status:
            raise SecurityError("Cannot inspect installation security descriptor (Windows error %d)." % status)
        try:
            aces = None
            if dacl.value:
                if not self.a.IsValidAcl(dacl):
                    raise SecurityError("Malformed installation DACL.")
                header = ctypes.string_at(dacl, 8)
                count = int.from_bytes(header[4:6], "little")
                aces = []
                for index in range(count):
                    ace = w.LPVOID()
                    if not self.a.GetAce(dacl, index, ctypes.byref(ace)):
                        raise SecurityError("Cannot inspect ACL entry.")
                    head = ctypes.string_at(ace, 4)
                    size = int.from_bytes(head[2:4], "little")
                    if head[0] not in (0, 1) or size < 16:
                        raise SecurityError("Unsupported installation ACL entry.")
                    sid = ace.value + 8
                    if (not self.a.IsValidSid(sid)
                            or self.a.GetLengthSid(sid) != size - 8):
                        raise SecurityError("Malformed installation ACL SID.")
                    mask = int.from_bytes(ctypes.string_at(ace.value + 4, 4), "little")
                    aces.append((head[0], head[1], mask, self.sid(sid)))
            identity = (info.volume, info.indexhi, info.indexlo)
            return identity, bool(info.attrs & DIRECTORY), self.sid(owner), aces
        finally:
            if sd.value:
                self.k.LocalFree(sd)

    def children(self, path):
        with os.scandir(path) as entries:
            return [(e.name, e.is_dir(follow_symlinks=False)) for e in entries]


class ProtectedInstall:
    """Hold namespace/runtime guards; validate destinations immediately before writes.

    Requires python.exe in a protected full, non-venv Python installation. Scans
    and locks its ENTIRE directory tree, including DLLs, ZIPs and all Lib content.
    Managed overlay paths and existing backups are likewise checked. Existing ACLs are never repaired.
    This proves filesystem protection, not publisher authenticity. External OS
    DLLs and the OS loader remain part of the trusted Windows platform. The
    caller must use a protected cwd and sanitized DLL search environment.
    check_path accepts missing final paths only under trusted inheritable dirs;
    call again after creation. Do not set custom security descriptors on creates.
    """
    def __init__(self, script_path, interpreter, *, _api=None, local_details=False):
        self.local_details = local_details
        self.script = _path(script_path)
        self.interpreter = _path(interpreter)
        self.install = ntpath.dirname(self.script)
        self.runtime = ntpath.dirname(self.interpreter)
        if ntpath.basename(self.interpreter) not in ("python.exe", "pythonw.exe"):
            raise SecurityError("Use the protected all-users python.exe or pythonw.exe interpreter.")
        if _under(self.install, self.runtime) or _under(self.runtime, self.install):
            raise SecurityError("Python and overlay installation trees must be separate.")
        self.api = _api if _api is not None else _Native()
        self.guards = {}
        self.active = False
        self.released = False

    def _label(self, path):
        if self.local_details:
            return path
        if path == self.runtime:
            return "Python directory"
        if path == self.install:
            return "application directory"
        if path == self.script:
            return "updater source"
        if path == self.interpreter:
            return "Python executable"
        if _under(path, self.runtime):
            return "Python tree entry"
        if _under(path, self.install):
            return "managed application entry"
        # Depth counts components below the drive root, not distance from install.
        depth = len(path[3:].split(chr(92))) if path[3:] else 0
        return "installation ancestor (depth %d)" % depth

    def _guard(self, path, directory, writable=False, ancestor=False):
        try:
            self._guard_impl(path, directory, writable, ancestor)
        except SecurityError as error:
            raise SecurityError(self._label(path) + ": " + str(error)) from None
        except OSError as error:
            raise SecurityError(self._label(path) + ": filesystem inspection failed (Windows error %s)." %
                                getattr(error, 'winerror', None)) from None

    def _guard_impl(self, path, directory, writable=False, ancestor=False):
        if path in self.guards:
            self._validate(path, self.guards[path], directory, writable)
            return
        handle = self.api.open(path, directory)
        try:
            info = self.api.inspect(handle)
            self._policy(info, directory, writable, ancestor)
            self.guards[path] = (handle, info[0], directory, writable, ancestor)
        except BaseException:
            self.api.close(handle)
            raise

    @staticmethod
    def _policy(info, directory, writable, ancestor=False):
        if info[1] != directory:
            raise SecurityError("Installation path has the wrong object type.")
        _acl_policy(info[2], info[3], directory, writable, ancestor)

    def _validate(self, path, guard, directory=None, writable=None):
        try:
            self._validate_impl(path, guard, directory, writable)
        except SecurityError as error:
            raise SecurityError(self._label(path) + ": " + str(error)) from None

    def _validate_impl(self, path, guard, directory=None, writable=None):
        handle, identity, was_dir, was_writable, ancestor = guard
        info = self.api.inspect(handle)
        self._policy(info, was_dir if directory is None else directory,
                     was_writable if writable is None else writable, ancestor)
        if info[0] != identity:
            raise SecurityError("Installation object identity changed.")
        # Check namespace as well as the retained handle (e.g. drive remapping).
        probe = self.api.open(path, was_dir)
        try:
            if self.api.inspect(probe)[0] != identity:
                raise SecurityError("Installation pathname identity changed.")
        finally:
            self.api.close(probe)

    def _ancestors(self, path, writable=False):
        drive = path[:3]
        self.api.volume(drive)
        self._guard(drive, True, ancestor=True)
        current = drive
        for part in path[3:].split("\\"):
            if part:
                current = ntpath.join(current, part)
                self._guard(current, True, writable and _under(current, self.install),
                            ancestor=not (_under(current, self.install) or _under(current, self.runtime)))

    def _tree(self, root, writable):
        pending = [root]
        count = 0
        while pending:
            directory = pending.pop()
            for name, is_dir in self.api.children(directory):
                if writable and directory == self.install and name.casefold() not in MANAGED:
                    continue  # Private config/fonts/unmanaged data are not elevated inputs.
                path = _path(ntpath.join(directory, name))
                if ntpath.dirname(path) != directory:
                    raise SecurityError("Invalid installation directory entry.")
                count += 1
                if count > 100000:
                    raise SecurityError("Installation tree exceeds safety limit.")
                self._guard(path, is_dir, writable and is_dir)
                if is_dir:
                    pending.append(path)
                elif _under(path, self.runtime) and (name.casefold() in ("pyvenv.cfg", "pybuilddir.txt")
                        or name.casefold().endswith("._pth")):
                    raise SecurityError("Venv and custom Python path configurations are unsupported.")

    def _runtime_landmarks(self, version):
        for relative in ('DLLs', 'Lib\\os.py', 'Lib\\encodings\\__init__.py',
                         'python%d%d.dll' % version):
            if _path(ntpath.join(self.runtime, relative)) not in self.guards:
                raise SecurityError("Standard protected CPython runtime landmark missing: " + relative)

    def __enter__(self):
        if self.active:
            raise SecurityError("Protected installation context already active.")
        self.active = True
        try:
            self._ancestors(self.runtime)
            self._ancestors(self.install, True)
            # CPython also probes pyvenv.cfg one directory above python.exe.
            candidate = ntpath.join(ntpath.dirname(self.runtime), "pyvenv.cfg")
            try:
                probe = self.api.open(candidate, False)
            except FileNotFoundError:
                pass
            else:
                self.api.close(probe)
                raise SecurityError("Parent-directory Python venv configuration is unsupported.")
            self._guard(self.interpreter, False)
            self._guard(self.script, False)
            self._tree(self.runtime, False)
            # Standard CPython must find its trusted stdlib landmarks, not fall
            # back to registry/CWD discovery. No free-threaded/debug/custom builds.
            if self.api.__class__ is _Native:
                if (sys.implementation.name != 'cpython' or hasattr(sys, 'gettotalrefcount')
                        or not (3, 11) <= sys.version_info[:2] <= (3, 14)):
                    raise SecurityError("Only standard release CPython is supported.")
                self._runtime_landmarks(sys.version_info[:2])
                if self.api.loaded_runtime() != ntpath.join(self.runtime, 'python%d%d.dll' % sys.version_info[:2]):
                    raise SecurityError('Loaded Python runtime DLL is outside the guarded layout.')
                if _path(sys.base_prefix) != self.runtime or sys.prefix != sys.base_prefix:
                    raise SecurityError("Virtual or redirected Python runtimes are unsupported.")
                if sys.flags.isolated:
                    if any(not _under(_path(entry), self.runtime) for entry in sys.path):
                        raise SecurityError("Isolated Python imported paths outside protected runtime.")
                    if _path(sys.exec_prefix) != self.runtime or _path(sys.base_exec_prefix) != self.runtime:
                        raise SecurityError("Redirected Python execution prefix.")
            self._tree(self.install, True)
            self.revalidate()
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def revalidate(self):
        if not self.active:
            raise SecurityError("Protected installation context is not active.")
        for path, guard in list(self.guards.items()):
            self._validate(path, guard)

    def check_path(self, path):
        if not self.active:
            raise SecurityError("Protected installation context is not active.")
        path = _path(path)
        if not _under(path, self.install):
            raise SecurityError("Update path escapes the protected installation.")
        self.revalidate()
        parent = ntpath.dirname(path)
        if path != self.install:
            self._ancestors(parent, True)
        # Files are transiently checked, not retained here: caller must write/
        # replace them. Retained directories prohibit namespace replacement.
        try:
            handle = self.api.open(path, False)
        except FileNotFoundError:
            return
        try:
            info = self.api.inspect(handle)
            self._policy(info, info[1], info[1])
        finally:
            self.api.close(handle)
        if info[1]:
            self._guard(path, True, True)

    def release_temporary(self, path):
        """Release a completed private staging subtree before rmdir cleanup."""
        path = _path(path)
        if ntpath.dirname(path) != self.install or not ntpath.basename(path).startswith('.overlay-update-stage-'):
            raise SecurityError("Not an updater staging directory.")
        self.revalidate()
        for key, guard in reversed(list(self.guards.items())):
            if _under(key, path):
                self.api.close(guard[0])
                del self.guards[key]

    def release_script(self):
        """Allow own-file replacement; keep directory/runtime guards until exit."""
        self.revalidate()
        for path, guard in list(self.guards.items()):
            if _under(path, self.install) and not guard[2]:
                self.api.close(guard[0])
                del self.guards[path]
        self.released = True

    def __exit__(self, *exc):
        for guard in reversed(list(self.guards.values())):
            self.api.close(guard[0])
        self.guards.clear()
        self.active = False


def machine_root_certificates():
    """Return only machine ROOT certificates, never per-user CA overrides."""
    class Certificate(ctypes.Structure):
        _fields_ = [('encoding', w.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte)),
                    ('size', w.DWORD), ('info', w.LPVOID), ('store', w.HANDLE)]
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    crypt.CertOpenStore.argtypes = [w.LPCSTR, w.DWORD, w.HANDLE, w.DWORD, w.LPVOID]
    crypt.CertOpenStore.restype = w.HANDLE
    crypt.CertEnumCertificatesInStore.argtypes = [w.HANDLE, ctypes.POINTER(Certificate)]
    crypt.CertEnumCertificatesInStore.restype = ctypes.POINTER(Certificate)
    crypt.CertFreeCertificateContext.argtypes = [ctypes.POINTER(Certificate)]
    crypt.CertFreeCertificateContext.restype = w.BOOL
    crypt.CertCloseStore.argtypes = [w.HANDLE, w.DWORD]
    crypt.CertCloseStore.restype = w.BOOL
    # CERT_STORE_PROV_SYSTEM_W, LOCAL_MACHINE | OPEN_EXISTING | READONLY.
    store = crypt.CertOpenStore(ctypes.cast(ctypes.c_void_p(10), w.LPCSTR), 0,
                               None, 0x20000 | 0x4000 | 0x8000,
                               ctypes.cast(ctypes.c_wchar_p('ROOT'), w.LPVOID))
    if not store:
        error = ctypes.get_last_error() & 0xFFFFFFFF
        raise SecurityError('Cannot open machine TLS trust store (Win32 0x%08X).' % error)
    certificate = None
    roots = []
    try:
        while True:
            # Crypt32 consumes the previous context even on native failure.
            # Keep only its returned context for the finally-block to free.
            certificate = crypt.CertEnumCertificatesInStore(store, certificate)
            if not certificate:
                # use_last_error=True saves the native DWORD in ctypes' private
                # signed int slot. Normalize BEFORE comparing HRESULT-style
                # codes; CRYPT_E_NOT_FOUND otherwise looks like -2146885628.
                # Read immediately, before any cleanup call can overwrite it.
                error = ctypes.get_last_error() & 0xFFFFFFFF
                if error != 0x80092004:  # CRYPT_E_NOT_FOUND (system ROOT store)
                    raise SecurityError('Cannot enumerate machine TLS trust store (Win32 0x%08X).' % error)
                break
            if certificate.contents.encoding & 1:
                roots.append(ctypes.string_at(certificate.contents.data, certificate.contents.size))
    finally:
        if certificate:
            crypt.CertFreeCertificateContext(certificate)
        crypt.CertCloseStore(store, 0)
    if not roots:
        raise SecurityError('Machine TLS trust store contains no X.509 root certificates.')
    return roots
