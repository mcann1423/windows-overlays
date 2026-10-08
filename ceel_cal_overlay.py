import datetime
import json
from pathlib import Path
from urllib.parse import urlsplit
import os
import re
import sys
import tkinter as tk
from overlay_updater import attach_update_menu
from overlay_appearance import Appearance, calendar_layout, calendar_zone, place_within_screen
import tkinter.font as tkfont
import urllib.request

# ==============================================================================
# CONFIGURATION OPTIONS
# ==============================================================================
HEADER_TITLE = "CEEL Appointments"

# Choose screen placement: "left", "center", or "right"
POSITION = "right"

# Private feed URLs live beside this script, never in source control.
def load_calendar_url():
  config_path = Path(__file__).resolve().with_name("calendar_config.json")
  try:
    with config_path.open(encoding="utf-8") as config_file:
      config = json.load(config_file)
  except FileNotFoundError:
    raise ValueError(
        "Missing calendar_config.json beside the script; copy "
        "calendar_config.example.json and fill in your private URLs."
    ) from None
  except (OSError, UnicodeError, ValueError):
    raise ValueError(
        "Cannot read calendar_config.json; check permissions and valid UTF-8 JSON."
    ) from None

  key = "ceel_ical_url"
  if not isinstance(config, dict) or key not in config:
    raise ValueError(f"calendar_config.json must contain the {key} key.") from None
  url = config[key]
  if not isinstance(url, str) or not url or any(c.isspace() for c in url):
    raise ValueError(f"calendar_config.json: {key} must be an HTTP(S) feed URL.") from None
  try:
    parsed = urlsplit(url)
    valid = (
        parsed.scheme in ("http", "https")
        and bool(parsed.hostname)
        and parsed.port != 0
        and "YOUR_GOOGLE_CALENDAR" not in url
    )
  except ValueError:
    valid = False
  if not valid:
    raise ValueError(f"calendar_config.json: {key} must be an HTTP(S) feed URL.") from None
  return url


try:
  ICAL_URL = load_calendar_url()
  CONFIG_ERROR = None
except ValueError as error:
  ICAL_URL = ""
  CONFIG_ERROR = str(error)

FONT_FAMILY = "Arial"
EVENT_FONT_SIZE = 20

OUTLINE_WEIGHT = 5  # Outline stroke thickness
OUTLINE_COLOR = "#0F172A"  # Dark slate stroke border
TEXT_COLOR = "#E2E8F0"  # Main soft slate text color

EXPIRY_INTERVAL_MS = 15000  # Local-only expiry checks; no calendar downloads
cached_ics_data = None
calendar_error = None

REFRESH_INTERVAL_MS = 300000  # Refresh calendar every 5 minutes (300,000 ms)
# ==============================================================================


def parse_ics_date(dt_str):
  """Parses iCal date strings into local datetime objects and formatted time strings."""
  dt_str = dt_str.strip()
  val = dt_str.split(":", 1)[-1] if ":" in dt_str and not re.match(r"^\d{8}T", dt_str) else dt_str
  val = val.removesuffix("Z")

  # All-day event (YYYYMMDD)
  if len(val) == 8 and val.isdigit():
    y, m, d = int(val[:4]), int(val[4:6]), int(val[6:8])
    return datetime.date(y, m, d), "All Day", None

  # Timed event (YYYYMMDDTHHMMSS)
  if len(val) >= 15 and "T" in val:
    date_part, time_part = val.split("T")[:2]
    y, m, d = int(date_part[:4]), int(date_part[4:6]), int(date_part[6:8])
    hh, mm, ss = int(time_part[:2]), int(time_part[2:4]), int(time_part[4:6])
    dt = datetime.datetime(y, m, d, hh, mm, ss)
    if dt_str.endswith("Z") or "UTC" in dt_str:
      dt = dt.replace(tzinfo=datetime.timezone.utc)
    elif re.fullmatch(r"[+-]\d{2}:?\d{2}", time_part[6:]):
      offset = time_part[6:].replace(":", "")
      minutes = int(offset[1:3]) * 60 + int(offset[3:5])
      dt = dt.replace(tzinfo=datetime.timezone(datetime.timedelta(
          minutes=minutes if offset[0] == "+" else -minutes)))
    # Floating/local values keep the existing system-local interpretation.
    dt = dt.astimezone()

    event_date = dt.date()
    time_formatted = dt.strftime("%I:%M %p").lstrip("0")
    return event_date, time_formatted, dt

  return None, None, None


def fetch_two_day_schedule(ical_url):
  """Refresh the cached feed; never retain an already-formatted stale schedule."""
  global cached_ics_data, calendar_error
  if CONFIG_ERROR:
    calendar_error = f"CONFIG ERROR\n{CONFIG_ERROR}"
    return format_cached_schedule()
  try:
    req = urllib.request.Request(ical_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as response:
      cached_ics_data = response.read().decode("utf-8", errors="ignore")
    calendar_error = None
  except Exception as error:
    calendar_error = f"CALENDAR UNAVAILABLE\nError loading feed: {type(error).__name__}"
  return format_cached_schedule()


def format_cached_schedule(now=None):
  """Re-evaluate cached starts locally, including after failed network refreshes."""
  now = (now or datetime.datetime.now().astimezone()).astimezone()
  main_header_block = f"{HEADER_TITLE.upper()}\n" + ("═" * 26)
  if calendar_error:
    main_header_block += f"\n\n{calendar_error}"
  if cached_ics_data is None:
    return main_header_block
  ics_data = cached_ics_data
  # Unfold multi-line iCal text wrapping
  ics_data = ics_data.replace("\r\n ", "").replace("\n ", "")
  vevents = re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", ics_data, re.DOTALL)

  today = now.date()
  tomorrow = today + datetime.timedelta(days=1)

  today_events = []
  tomorrow_events = []

  for vevent in vevents:
    summary_match = re.search(r"SUMMARY:(.*)", vevent)
    dtstart_match = re.search(r"DTSTART[;:](.*)", vevent)

    if summary_match and dtstart_match:
      summary = summary_match.group(1).strip().replace("\\,", ",")
      dt_raw = dtstart_match.group(1).strip()

      try:
        event_date, time_str, dt_obj = parse_ics_date(dt_raw)
      except (ValueError, OverflowError):
        continue
      if dt_obj is not None and now >= dt_obj + datetime.timedelta(minutes=30):
        continue

      if event_date == today:
        today_events.append((dt_obj, time_str, summary))
      elif event_date == tomorrow:
        tomorrow_events.append((dt_obj, time_str, summary))

  # Sort events: All-day events first, followed by chronological start times
  today_events.sort(key=lambda x: (x[0] is not None, x[0]))
  tomorrow_events.sort(key=lambda x: (x[0] is not None, x[0]))

  def format_day_section(header, events):
    header_block = f"{header}\n" + ("─" * 26)
    if not events:
      return f"{header_block}\n  No events scheduled"

    event_strings = [
        f"{time_str:<8}  •  {summary}" for _, time_str, summary in events
    ]
    return f"{header_block}\n" + "\n\n".join(event_strings)

  today_header = today.strftime("TODAY — %A, %b %d").upper()
  tomorrow_header = tomorrow.strftime("TOMORROW — %A, %b %d").upper()

  today_block = format_day_section(today_header, today_events)
  tomorrow_block = format_day_section(tomorrow_header, tomorrow_events)

  return f"{main_header_block}\n\n{today_block}\n\n\n{tomorrow_block}"


root = tk.Tk()
update_menu = attach_update_menu(root, __file__)
root.title("Calendar Overlay")

# Remove window borders and force overlay above all applications
root.overrideredirect(True)
root.wm_attributes("-topmost", True)

# Set transparent background
TRANS_COLOR = "#000001"
root.config(bg=TRANS_COLOR)
root.wm_attributes("-transparentcolor", TRANS_COLOR)

# Canvas setup for drawing text + outline
canvas = tk.Canvas(root, bg=TRANS_COLOR, highlightthickness=0)
canvas.pack(expand=True, fill="both")

# Hover Close Button
close_btn = tk.Label(
    root,
    text="✕",
    font=("Segoe UI", 18, "bold"),
    bg=TRANS_COLOR,
    fg="#94A3B8",
    cursor="hand2",
)


def close_app(event=None):
  root.destroy()
  sys.exit(0)


close_btn.bind("<Button-1>", close_app)
close_btn.bind("<Enter>", lambda e: close_btn.config(fg="#F87171"))
close_btn.bind("<Leave>", lambda e: close_btn.config(fg="#94A3B8"))


def show_ui(event):
  close_btn.place(relx=0.96, rely=0.03, anchor="ne")


def hide_ui(event):
  x, y = root.winfo_pointerx(), root.winfo_pointery()
  rx, ry = root.winfo_rootx(), root.winfo_rooty()
  rw, rh = root.winfo_width(), root.winfo_height()

  if not (rx <= x <= rx + rw and ry <= y <= ry + rh):
    close_btn.place_forget()


root.bind("<Enter>", show_ui)
root.bind("<Leave>", hide_ui)


# Drag-and-drop support
def start_move(event):
  root.x = event.x
  root.y = event.y


def do_move(event):
  x = root.winfo_x() + (event.x - root.x)
  y = root.winfo_y() + (event.y - root.y)
  place_within_screen(root, window_w, window_h, (x, y),
                      bounds=calendar_zone(root, POSITION))


canvas.bind("<ButtonPress-1>", start_move)
canvas.bind("<B1-Motion>", do_move)


def redraw_calendar(full_text):
  """Renders outline stroke pixels first, then layers main text over top with word-wrapping."""
  canvas.delete("all")

  w = canvas.winfo_width()
  h = canvas.winfo_height()
  if w <= 1:
    w = window_w
  if h <= 1:
    h = window_h

  # The fixed 20px inset covers every allowed stroke (0–5px) without rewrap.
  cx = 20  # Left padding
  cy = 20  # Top padding
  wrap_pixel_width = max(1, w - 40)  # Constrains text wrapping inside overlay width

  r = OUTLINE_WEIGHT
  if r > 0:
    for dx in range(-r, r + 1):
      for dy in range(-r, r + 1):
        if dx == 0 and dy == 0:
          continue
        if dx * dx + dy * dy <= r * r + 1:
          canvas.create_text(
              cx + dx,
              cy + dy,
              text=full_text,
              font=(FONT_FAMILY, EVENT_FONT_SIZE, "bold"),
              fill=OUTLINE_COLOR,
              anchor="nw",
              justify="left",
              width=wrap_pixel_width,
          )

  # Main foreground text with automatic word wrapping
  canvas.create_text(
      cx,
      cy,
      text=full_text,
      font=(FONT_FAMILY, EVENT_FONT_SIZE, "bold"),
      fill=TEXT_COLOR,
      anchor="nw",
      justify="left",
      width=wrap_pixel_width,
  )


# ==============================================================================
# DYNAMIC POSITIONING LOGIC (3 EQUAL VERTICAL ZONES)
# ==============================================================================
zone = calendar_zone(root, POSITION)
default_window_w = max(1, zone[2] - zone[0] - 40)
default_window_h = max(1, int((zone[3] - zone[1]) * 0.82))
window_w, window_h = place_within_screen(root, default_window_w, default_window_h,
    (zone[0] + 20, zone[1] + (zone[3] - zone[1] - default_window_h) // 2), bounds=zone)
current_schedule_text = ""
layout_in_progress = False


def apply_appearance(settings, refresh=False):
  global EVENT_FONT_SIZE, OUTLINE_WEIGHT, window_w, window_h, layout_in_progress
  if layout_in_progress:
    return
  layout_in_progress = True
  try:
    previous_scroll = canvas.yview()[0]
    EVENT_FONT_SIZE = settings["font_size"]
    OUTLINE_WEIGHT = settings.get("outline_weight", 5)
    zone = calendar_zone(root, POSITION)
    width, height, _ = calendar_layout(root, canvas, current_schedule_text,
        FONT_FAMILY, EVENT_FONT_SIZE, max(1, zone[2] - zone[0] - 40),
        max(1, int((zone[3] - zone[1]) * 0.82)))
    window_w, window_h = place_within_screen(root, width, height, bounds=zone)
    canvas.yview_moveto(0)
    redraw_calendar(current_schedule_text)
    bounds = canvas.bbox("all")
    canvas.configure(scrollregion=(0, 0, window_w,
        max(window_h, bounds[3] + 20 if bounds else 0)))
    canvas.yview_moveto(previous_scroll)
  finally:
    layout_in_progress = False


def scroll_calendar(event):
  if event.delta:
    canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")


canvas.bind("<MouseWheel>", scroll_calendar)
canvas.bind("<Button-4>", lambda event: canvas.yview_scroll(-1, "units"))
canvas.bind("<Button-5>", lambda event: canvas.yview_scroll(1, "units"))
appearance = Appearance(root, update_menu, __file__, 20, apply_appearance, default_outline=5)
EVENT_FONT_SIZE = appearance.settings["font_size"]


def reflow_calendar(event):
  if not layout_in_progress and event.widget is canvas and (event.width != window_w or event.height != window_h):
    root.after_idle(lambda: apply_appearance(appearance.settings, refresh=True))


canvas.bind("<Configure>", reflow_calendar)


def update_calendar():
  global current_schedule_text
  current_schedule_text = fetch_two_day_schedule(ICAL_URL)
  apply_appearance(appearance.settings, refresh=bool(canvas.find_all()))
  root.after(REFRESH_INTERVAL_MS, update_calendar)


def expire_calendar():
  global current_schedule_text
  text = format_cached_schedule()
  if text != current_schedule_text:
    current_schedule_text = text
    apply_appearance(appearance.settings, refresh=True)
  root.after(EXPIRY_INTERVAL_MS, expire_calendar)


# Initial render and independent local expiry timer.
update_calendar()
root.after(EXPIRY_INTERVAL_MS, expire_calendar)


# Keep terminal responsive to Ctrl+C
def check_signals():
  root.after(500, check_signals)


root.after(500, check_signals)

try:
  root.mainloop()
except KeyboardInterrupt:
  sys.exit(0)