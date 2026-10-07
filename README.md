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
standard library; no third-party Python packages are required. Keep the shared
`overlay_updater.py` module beside all four scripts. Optional in-app updates use public HTTPS downloads: no Git, gh, pip packages, or authentication is required. Windows transparent-window attributes and the clock's Windows GDI
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
shortcuts to run several together. For shortcuts, set **Start in** to this
folder: the clock resolves its font file from the **current working directory**,
not from the script's location.

## Fonts: supplied separately, never included in GitHub

No font files are distributed in this repository. Obtain desired fonts
separately under their applicable licenses and keep them local. The clock's
active default expects `Nunito-Black.ttf` in its working directory and uses
the family name `Nunito Black`. It registers that file privately with Windows
GDI when present; when the file is missing, it requests `Arial Rounded MT Bold`.

The existing commented seasonal configurations reference optional local files
(not active by default):

- `Creepster-Regular.ttf` — `Creepster` (Halloween).
- `BerkshireSwash-Regular.ttf` — `Berkshire Swash` (fall).
- `MountainsofChristmas-Bold.ttf` — `Mountains of Christmas` (winter).

The IP overlay requests `Arial Narrow`, calendars request `Arial`, and close
buttons request `Segoe UI`. Make those system fonts available separately for
the intended appearance; Tk may substitute fonts if a family is unavailable.
Font files and font directories are ignored by Git. Do not force-add fonts or
package them in archives for publication.

## Local calendar configuration

1. If no local config exists, copy `calendar_config.example.json` to
   `calendar_config.json` beside the calendar scripts. Never overwrite an
   existing private config with the example.
2. Replace placeholders with private iCal feed URLs: `cchl_ical_url` for
   `cchl_cal_overlay.py`, and `ceel_ical_url` for `ceel_cal_overlay.py`.
   Keep both values as JSON strings.
3. Restart the calendar scripts after changing config. They locate config
   relative to the script, independently of the working directory, and refresh
   calendars every five minutes.

Missing or invalid configuration appears as `CONFIG ERROR` without displaying
private values. Keep private config local and transfer it privately when
setting up another computer. Restrict Windows file Security permissions to
your account; on Linux/macOS use `chmod 600 calendar_config.json`.

## Publication boundaries

Only the four scripts above, the shared updater, its tests, this README,
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

The updater resolves public GitHub main once, then fetches a tree and seven
allowlisted files pinned to that immutable commit SHA: itself, the four overlays,
README (current setup/recovery guidance), and the placeholder-only config example
(setup reference). It never downloads tests, .gitignore, fonts, real config,
legacy clocks, unknown files or .git. There is no ZIP extraction, authentication,
subprocess, calendar access, or import/execution of fetched scripts.

Existing-solutions preflight: Git requires an unwanted end-user installation;
third-party updater libraries add dependencies without benefit for seven flat
files. Maintained standard-library urllib plus GitHub API/raw endpoints suffice.
Downloads require trusted HTTPS hosts, reject redirects, use 15-second socket
timeouts and a 45-second read budget per response (a blocking read may extend
that by one socket timeout), and cap each response at 1 MiB. Files are checked
against GitHub blob hashes, sizes, UTF-8 and expected syntax/content. These are
consistency checks trusting HTTPS and the publisher, not independent signed
release authenticity. Offline/404/rate-limit errors leave application files
unchanged; wait and retry for rate limits, without signing in.

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
download the ZIP and manually copy the seven managed files after backing up
local edits; leave real config/fonts/legacy/unknown files untouched. Restart all
overlays. Subsequent menu updates need no Git and leave Git HEAD/index alone:
a clone may show tracked changes afterward. Do not blindly pull/reset it.
If copying only the seven files into an old clone, manually merge the four
updater ignore patterns from the new .gitignore before publishing anything;
the downloader intentionally never edits .gitignore.

### Tests and limitations

Run **py -m unittest discover -s tests -v**. Tests use temporary ordinary folders,
mocked HTTP and mocked Tk, not installed Git or real calendars. Linux tests and
static compilation do not replace a native Windows GUI smoke test of menu
placement, transparency, antivirus/file-sharing behavior and multiple overlays.
Python syntax validation uses installed Python; future code requiring a newer
Python will fail safely until Python is upgraded.
