# Windows desktop overlays

Four independently launched Python/Tkinter overlays:

- `clock_overlay_v3.py`: outlined clock near the top of the screen.
- `ip_overlay.py`: local IPv4 address in the lower-right corner.
- `cchl_cal_overlay.py`: today/tomorrow calendar on the left.
- `ceel_cal_overlay.py`: today/tomorrow calendar on the right.

Drag an overlay to move it; hover to reveal its close button.

## Windows requirements and launch

Use Python 3 on Windows with Tcl/Tk and Tkinter installed (normally included
with the standard Windows Python installer). All imports are from the Python
standard library; no third-party Python packages are required. Keep the shared modules,
`overlay_updater.py`, `overlay_windows.py` and `overlay_appearance.py`, beside all four scripts. Optional in-app updates use public HTTPS downloads: no Git, gh, pip packages, or authentication is required. Windows transparent-window attributes and the clock's Windows GDI
font registration mean these scripts are not intended to run unchanged on Linux.
Calendar overlays need network access to their configured feeds. The IP overlay
uses a UDP socket route lookup against 8.8.8.8:80 to select the local interface;
it does not send application data.

In a Windows terminal, change to the folder containing the scripts and your
separately supplied clock fonts, then run any desired overlay:

```bat
cd /d C:\path\to\windows-overlays
py clock_overlay_v3.py
py ip_overlay.py
py cchl_cal_overlay.py
py ceel_cal_overlay.py
```

Each command runs an independent application; use separate terminals or
shortcuts to run several together. The clock resolves optional fonts beside its script, independently of the
shortcut working directory. Existing Startup launchers need no changes.

## Fonts: supplied separately, never included in GitHub

No font files are distributed in this repository. Obtain desired fonts
separately under their applicable licenses and keep them local. The clock's
active default expects `Nunito-Black.ttf` beside the script and uses
the family name `Nunito Black`. It registers that file privately with Windows
GDI when present; when the file is missing, it requests `Arial Rounded MT Bold`.

The clock Theme submenu references optional local files:

- `Creepster-Regular.ttf` — `Creepster` (Halloween).
- `BerkshireSwash-Regular.ttf` — `Berkshire Swash` (fall).
- `MountainsofChristmas-Bold.ttf` — `Mountains of Christmas` (winter).

The IP overlay requests `Arial Narrow`, calendars request `Arial`, and close
buttons request `Segoe UI`. Make those system fonts available separately for
the intended appearance; Tk may substitute fonts if a family is unavailable.
Font files and font directories are ignored by Git. Do not force-add fonts or
package them in archives for publication.

## Appearance controls

Right-click visible text to select **Font size** on any overlay. Choose a preset (including **14 pt**),
**Custom…** (8–144 pt), or **Reset default** (clock/IP: 72 pt; calendars: 20 pt).
All four overlays also offer **Outline weight → None (0 px), 1 px, 2 px,
3 px, 4 px, 5 px**, plus **Reset default** (clock/IP: 3 px; calendars: 5 px).
Old settings without an outline option retain those original weights. Padding
reserves room for the maximum stroke, so changing weight does not resize or move
the overlay, rewrap calendar text, or reset its scroll position. The 5-pixel cap
keeps drawing work bounded; no-outline draws just the foreground text.
The clock also offers **Theme → Default, Halloween, Fall, Winter**, using the
original colors and optional fonts listed above. Missing fonts show a warning
and use a system fallback; no fonts are downloaded.

Changes apply immediately and persist separately for each overlay in
`%LOCALAPPDATA%\DesktopOverlays\<script-name>.json`. These per-user settings
need no administrator approval and never modify `calendar_config.json` or the
Program Files installation. Malformed settings fall back to defaults. Multiple
instances of the same overlay use last-save-wins; different overlays have separate
files. Windows are resized/repositioned within the current Windows monitor; clock/IP text
may render smaller to fit a small screen. The clock retains its top-third center,
or its dragged center, across font/theme changes without drift. Calendars stay
inside their original left/right third, with 20-pixel side margins and an
82%-height viewport relative to the monitor work area. Text wraps/clips inside
that column and scrolls with the mouse wheel. Dragging stays within the assigned
third. Appearance changes need no restart.

## Local calendar configuration

1. If no local config exists, copy `calendar_config.example.json` to
   `calendar_config.json` beside the calendar scripts. Never overwrite an
   existing private config with the example.
2. Replace placeholders with private iCal feed URLs: `cchl_ical_url` for
   `cchl_cal_overlay.py`, and `ceel_ical_url` for `ceel_cal_overlay.py`.
   Keep both values as JSON strings.
3. Restart the calendar scripts after changing config. They locate config
   relative to the script, independently of the working directory, and refresh
   calendars every five minutes. Both calendars hide timed appointments at
   **start time + 30 minutes** (not end time). A separate local check every
   15 seconds expires cached appointments without fetching again, even when
   a network refresh fails. All-day events remain for their relevant day;
   future/tomorrow events stay visible. UTC and numeric-offset starts are compared
   as timezone-aware instants; floating/local times retain system-local semantics.
   As before, named non-UTC TZID values use system-local time (no bundled timezone
   database or recurrence expansion). Local expiry also rolls the day headers at
   midnight. Only changed text is redrawn; scroll and dragged placement are retained.
   On a failed refresh, a warning appears above any remaining cached events.

Missing or invalid configuration appears as `CONFIG ERROR` without displaying
private values. Keep private config local and transfer it privately when
setting up another computer. Restrict Windows file Security permissions to
your account; on Linux/macOS use `chmod 600 calendar_config.json`.

## Publication boundaries

Only the four scripts above, the shared updater and Windows trust helper, their tests, this README,
`.gitignore`, and the placeholder-only example config are published. `calendar_config.json`, common config backups,
legacy `clock_overlay.py` and `clock_overlay_v2.py`, and all fonts remain local
and ignored. Never force-add them or put real feed URLs in the example or
source. Review exact staged files before every push. The updater never publishes or uploads local files.


## Download and setup (no Git required)

1. Open https://github.com/mcann1423/windows-overlays, choose **Code → Download
   ZIP**, and extract to a writable folder. Do not run from inside the ZIP.
   Keep the shared updater beside all four overlay scripts.
2. Install standard Windows Python with Tkinter. Obtain fonts separately and
   follow the working-directory/font instructions above.
3. Copy the example config only if no real config exists, then enter your own
   calendar URLs locally. Launch overlays using the commands above.

## Optional in-app updates (Windows only)

Right-click **visible text**, choose **Check for updates…**, and confirm the
replacement warning. Transparent areas may pass clicks through. Nothing checks
at startup or on a timer. Downloads and file operations run in a worker; Tk
handles dialogs on its main thread. Leave the initiating window open to see the
result. Closing it does not cancel the non-daemon worker.

The updater resolves public GitHub main once, then fetches a tree and nine
allowlisted files pinned to that immutable commit SHA: itself, its Windows trust and appearance helpers, the four overlays,
README (current setup/recovery guidance), and the placeholder-only config example
(setup reference). It never downloads tests, .gitignore, fonts, real config,
legacy clocks, unknown files or .git. There is no ZIP extraction, authentication,
calendar access, or import/execution of fetched scripts. A protected installation
may launch only the dedicated local updater child described below.

Existing-solutions preflight: Git requires an unwanted end-user installation;
third-party updater libraries add dependencies without benefit for nine flat
files. Maintained standard-library urllib plus GitHub API/raw endpoints suffice.
Downloads require trusted HTTPS hosts, reject redirects, use 15-second socket
timeouts and a 45-second read budget per response (a blocking read may extend
that by one socket timeout), and cap each response at 1 MiB. Files are checked
against GitHub blob hashes, sizes, UTF-8 and expected syntax/content. These are
consistency checks trusting HTTPS and the publisher, not independent signed
release authenticity. Offline/404/rate-limit errors leave application files
unchanged; wait and retry for rate limits, without signing in.

### Program Files and administrator approval

For an existing installation at **C:\Program Files\Clock Overlays**, keep the
actual Python scripts and both updater modules there. The Startup folder should
contain only your existing launcher/shortcut: **do not change it or run overlays
as administrator**. Use a standard, all-users CPython installation, not a per-user
Python, virtual environment, Store alias, or portable/custom runtime. Protected
updates support standard release CPython **3.11–3.14** on local fixed NTFS.

After your menu confirmation, a worker tests folder write access **before** any
update transaction. A writable installation updates normally. Only access
denial triggers Windows' UAC prompt, via ShellExecuteExW `runas`, for the updater
child alone. Approve your trusted Python executable to proceed, or cancel; no
automatic retry occurs. The overlay GUI stays responsive and unprivileged.
Already-administrator overlays are refused; close and relaunch normally.
A failed transaction or rollback never triggers elevation.

The child uses absolute paths and isolated Python startup (`-I -S -B`), accepts
no target folder or arbitrary command, and updates only its own folder. The
parent waits for the child process exit code; there are no shared request/result
files. The child displays detailed errors, and the original overlay reports
completion. Keep it open and restart **all** overlays manually only on success.

Protected updates fail closed when local security checks cannot establish a
trusted installation. The folder name `Program Files` alone is not proof of
security. Owner/DACL checks allow only SYSTEM, Administrators and TrustedInstaller
mutation of managed files, Python runtime files and protected folders. Ancestors
are checked too; retained handles prevent rename/reparse substitution, and
identities/ACLs are revalidated before writes. Links, junctions, unsupported ACLs,
custom startup markers, redirected Python paths and untrusted writable runtime
content are refused. This may reject customized installations; do not weaken
permissions to make it pass. It scans the Python tree, which can take time.
Trusted Windows, its loader/system DLLs and administrators are the platform trust
boundary; this is not protection against an already-privileged attacker.

The child strips OpenSSL/TLS/proxy environment overrides before network imports,
restricts subsequent DLL search, disables proxies, and uses only machine ROOT
certificates, not user CA files/stores. Networks requiring a proxy or only a
per-user enterprise CA must use manual deployment. No ACL is loosened, no service
is installed, and no Git/authentication or pip is needed on the target computer.

### One-time bootstrap for an older updater

The older updater cannot request UAC, and its seven-file manifest cannot install
the new helpers. Close all overlays. Download the public repository ZIP, inspect
it, and back up existing application files and updater metadata. Use **Explorer**
to copy the nine managed files into `C:\Program Files\Clock Overlays`, accepting
Explorer's administrator approval for the copy. These are both updater modules, the appearance helper,
the four current overlays, README, and `calendar_config.example.json`. Preserve
`calendar_config.json` (the exact private configuration filename), all fonts,
legacy clocks and other local files. Do not copy the example over private config.

After manually replacing managed files, preserve then move the old
`.overlay-update.json` baseline out of the installation; the next confirmed
update records a fresh baseline. Do not remove a live/stale lock without following
the recovery steps below. Restart overlays normally using the existing Startup
launcher. Future updates use the menu and UAC. Never bootstrap by running an
entire overlay as administrator.

### Local edits, backups and recovery

**First use has no installed baseline, even in a Git clone.** Confirmation
explicitly authorizes replacing existing allowlisted files, including edits.
Replaced bytes are backed up first in .overlay-update-backups/. Save valued
customizations separately before confirming. Identical files need no replacement.
A successful first check writes .overlay-update.json with installed hashes.
Subsequent edits or missing managed files block updates, even when the published
version is unchanged. Nothing silently merges/resets/discards baseline edits.
To keep customizations, reconcile manually. To deliberately accept published
versions after separately backing up edits, move metadata out of the folder and
confirm first-use replacement again. Invalid metadata requires manual review.

All downloads are verified before staging; staged files and backups are verified
before replacement. Each replacement is atomic on the same filesystem; the
whole set is **not** one atomic transaction. Ordinary install errors restore
previous files and retain backups. Power loss, termination or failed rollback
can leave mixed versions: do not launch/restart overlays until recovered. No
rollback guarantee can survive disk failure.

A folder-wide .overlay-update.lock serializes overlays. After interruption,
close all overlays and confirm no updater remains. Inspect the newest backup's
recovery.json: restore its listed replaced files from that backup (including
old metadata), and remove only listed previously_absent files if now present.
If no backup exists, or its recovery.json was never completed, no application replacement began. Keep backups until
recovery is verified, then remove the stale lock and abandoned
.overlay-update-stage-* directories. Incomplete rollback retains the lock.
Never remove a live lock. Backups can contain private edits: never share them.
Updater metadata, locks, staging and backups are ignored by the new .gitignore.

**Restart ALL overlays manually after success.** Running processes retain their
loaded code, including the old updater. Avoid editing, launching overlays or
running Git during updates. Only cooperating updaters honor the lock; it does
not protect against another program editing files or a hostile local user.
Use a folder you control.

### Migration from the Git updater

Existing Git clients may run **git pull --ff-only origin main** once to obtain
this updater. Stop and preserve local changes if Git refuses. Alternatively,
download the ZIP and manually copy the nine managed files after backing up
local edits; leave real config/fonts/legacy/unknown files untouched. Restart all
overlays. Subsequent menu updates need no Git and leave Git HEAD/index alone:
a clone may show tracked changes afterward. Do not blindly pull/reset it.
If copying only the nine files into an old clone, manually merge the four
updater ignore patterns from the new .gitignore before publishing anything;
the downloader intentionally never edits .gitignore.

### Tests and limitations

Run **py -m unittest discover -s tests -v**. Tests use temporary ordinary folders,
mocked HTTP, Windows APIs and mocked Tk, not installed Git or real calendars.
**Native Windows/UAC execution has not been tested in this development environment.**
Before deployment, verify approval/cancellation, all-users python/pythonw,
alternate-admin credentials, real inherited ACLs, stage cleanup, rollback and
concurrent updaters on a Windows test installation. Linux tests and
static compilation do not replace a native Windows GUI smoke test of menu
placement, transparency, antivirus/file-sharing behavior and multiple overlays.
Python syntax validation uses installed Python; future code requiring a newer
Python will fail safely until Python is upgraded.

## Diagnosing a refused protected update

Do **not** reinstall Python or loosen ACLs based only on the old generic refusal.
A bug in 0251fae compared lowercased guarded paths with mixed-case DLLs/Lib
landmarks, falsely refusing a protected standard Python installation that reached
that check. This is corrected without relaxing the security policy. Other checks
can still fail; native Windows/UAC validation is required on your PC.

After manually deploying these files, open ordinary (not administrator) PowerShell.
Set $python to the full python.exe in the **same installation your Startup launcher
uses** (not a guessed path, Store alias or different Python), then run:

    & $python -I -S -B 'C:\Program Files\Clock Overlays\overlay_updater.py' --diagnose-trust

This only reads trust metadata: no UAC, download, calendar feed/config read, ACL
change or update. It prints Python version, executable and exact policy reason
with a sanitized object category. Share the version and Trust check line; redact
usernames in the executable path. If needed, append --local-details to display
the exact failing path **locally**. Do not publish this output unredacted. An
administrator can inspect that object with:

    Get-Acl -LiteralPath '<exact local path>' | Format-List Owner,AccessToString

Do not blindly change ownership/ACLs: untrusted owners, write grants, unsupported
ACLs, locked files, runtime layouts or Python versions need their own remedies.

**Manual deployment while updater is blocked:** close all four overlays; download
the repository ZIP from a reviewed commit and extract to a temporary folder. Use
Explorer's administrator copy prompt to replace only overlay_updater.py,
overlay_windows.py, overlay_appearance.py, clock_overlay_v3.py, ip_overlay.py,
cchl_cal_overlay.py, ceel_cal_overlay.py, README.md and calendar_config.example.json
in C:\Program Files\Clock Overlays. Keep calendar_config.json, all .ttf fonts,
per-user appearance settings and the separate Startup launcher untouched. Back up
replaced code. Existing updater baselines may report local edits after manual
replacement; do not delete locks/backups or force through failed transactions.
Run the diagnostic, then restart overlays normally, not as administrator. No
Windows reboot or Python reinstall is required merely to deploy this fix.
