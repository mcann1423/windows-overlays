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
`overlay_updater.py` module beside all four scripts. Optional in-app updates
require Git for Windows on PATH and existing private-repository authentication. Windows transparent-window attributes and the clock's Windows GDI
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


## Optional in-app updates (Windows only)

We use the maintained [Git for Windows](https://gitforwindows.org/) and its
[Git Credential Manager](https://github.com/git-ecosystem/git-credential-manager),
not a custom downloader or token store. Git's built-in fetch and
[fast-forward-only merge](https://git-scm.com/docs/git-merge) retain history and
refuse divergent updates. No Python packages, GitHub CLI, or updater-specific
credentials are needed on Windows.

### First-time setup

1. Install current Git for Windows with Git Credential Manager enabled and Git
   available to command-line applications; reopen terminals/overlays afterward.
2. In a Windows terminal, clone into a **new, empty folder**:

   ```bat
   git clone https://github.com/mcann1423/windows-overlays.git C:\path\to\windows-overlays
   cd /d C:\path\to\windows-overlays
   git fetch origin
   ```

   Complete Git Credential Manager's browser sign-in with a GitHub account that
   has access to this private repository (including any organization approval).
   Credentials stay in the user's Windows credential setup. Never put a token
   in a URL, script, config, shortcut or repository. Do not copy Linux credentials.
   An already configured GitHub SSH key/agent with a verified host key also works
   with the exact `git@github.com:mcann1423/windows-overlays.git` origin.
3. Copy your existing private `calendar_config.json` and separately licensed
   fonts into the new folder yourself, without overwriting originals. Keep your
   old folder as a backup. Point shortcuts at the new scripts and set **Start in**
   to the new folder. Downloaded ZIPs and loose scripts cannot self-update.
   Do not initialize/reset an existing mixed folder just to enable updates.
4. If already using a clean clone from before the update menu was added, run
   `git pull --ff-only origin main` once in its terminal, then restart overlays.
   Stop if Git reports conflicts/local changes; preserve and resolve them manually.

### Using it

Right-click the **visible text** of any overlay, choose **Check for updates…**,
then confirm. Transparent areas may pass mouse clicks to the desktop. The menu
updates the shared checkout for all four overlays; left-drag and hover-close
remain unchanged. Nothing checks at startup or on a timer. Git runs in a worker
thread while Tk polls for its result; subprocesses have bounded timeouts and
cannot prompt for passwords. If access fails, run `git fetch origin` in a terminal
and fix authentication/network access before retrying.

Only the trusted GitHub repository's `main` branch is accepted; the remote's
default branch must still be `main`. The updater refuses a dirty tracked tree,
detached/wrong branch, local commits ahead/diverged, URL rewrites, Git operations
in progress, hidden tracked-file flags, upstream protected paths, symlinks,
submodules, or collisions with any ignored/untracked local files. Config, fonts
and legacy clocks never become tracked via this updater. Local edits to styling
in tracked scripts also block updates: back them up and reconcile manually.
It never resets, cleans, stashes, force-pushes or stores credentials.

**Restart all running overlays manually after success.** Only on-disk tracked
files change; running applications retain their loaded code. Nothing kills or
restarts another overlay. Avoid other Git commands or file edits while an update
is running. The four updater instances serialize using a lock; if a process
crashes, inspect Git status and confirm no update/Git process remains before
removing `.git/overlay-update.lock`. Closing the initiating window does not cancel
a worker already running; leave it open to see the result. On timeout/failure,
inspect `git status` before retrying; never delete Git's own locks while it runs.

### Tests

From the repository root: `py -m unittest discover -s tests -v`. Tests use temporary
local Git repositories and mocked GUI/network destinations. They do not launch
overlays or access calendar feeds. Linux checks cover core Git safety and static
compilation; native Windows transparency, right-click placement, credential-manager
behavior and multi-overlay interaction still need a Windows GUI smoke test.
