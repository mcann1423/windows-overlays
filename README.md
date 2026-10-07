# Windows desktop overlays

Four standalone Python/Tkinter overlays:

- `clock_overlay_v3.py`: outlined clock near the top of the screen.
- `ip_overlay.py`: local IPv4 address in the lower-right corner.
- `cchl_cal_overlay.py`: today/tomorrow calendar on the left.
- `ceel_cal_overlay.py`: today/tomorrow calendar on the right.

Drag an overlay to move it; hover to reveal its close button.

## Windows requirements and launch

Use Python 3 on Windows with Tcl/Tk and Tkinter installed (normally included
with the standard Windows Python installer). All imports are from the Python
standard library; no third-party Python packages or local helper modules are
required. Windows transparent-window attributes and the clock's Windows GDI
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

Only the four scripts above, this README, `.gitignore`, and the placeholder-only
example config are published. `calendar_config.json`, common config backups,
legacy `clock_overlay.py` and `clock_overlay_v2.py`, and all fonts remain local
and ignored. Never force-add them or put real feed URLs in the example or
source. Review exact staged files before every push. No updater is included.
