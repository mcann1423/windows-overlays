import socket
import sys
import tkinter as tk
from overlay_updater import attach_update_menu
from overlay_appearance import Appearance, fit_single_line, place_within_screen
import tkinter.font as tkfont


def get_ip_address():
  """Retrieves the active local IPv4 address of the primary network interface."""
  try:
    # Connects to a public IP to determine the local outbound network interface (does not send data)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    ip = s.getsockname()[0]
    s.close()
    return ip
  except Exception:
    return "127.0.0.1"


# Styling & Configuration Options
FONT_FAMILY = "Arial Narrow"
FONT_SIZE = 72  # Adjusted for longer IP strings (e.g. 192.168.1.100)
OUTLINE_WEIGHT = 3  # Outline stroke thickness
OUTLINE_COLOR = "#0F172A"  # Dark slate stroke border
TEXT_COLOR = "#E2E8F0"  # Main soft slate text color
CORNER_MARGIN = 15  # Distance in pixels from screen edge

root = tk.Tk()
update_menu = attach_update_menu(root, __file__)
root.title("IP Overlay")

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
  close_btn.place(relx=0.98, rely=0.05, anchor="ne")


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
  root.geometry(f"+{x}+{y}")


canvas.bind("<ButtonPress-1>", start_move)
canvas.bind("<B1-Motion>", do_move)

current_ip_str = ""


def redraw_ip(ip_str):
  """Renders outline stroke pixels first, then layers main text over top."""
  canvas.delete("all")

  w = canvas.winfo_width()
  h = canvas.winfo_height()
  if w <= 1:
    w = window_w
  if h <= 1:
    h = window_h

  cx = w / 2
  cy = h / 2

  # Draw circular pixel stroke for smooth outline weight
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
              text=ip_str,
              font=(FONT_FAMILY, FONT_SIZE, "bold"),
              fill=OUTLINE_COLOR,
              anchor="center",
          )

  # Draw main foreground text
  canvas.create_text(
      cx,
      cy,
      text=ip_str,
      font=(FONT_FAMILY, FONT_SIZE, "bold"),
      fill=TEXT_COLOR,
      anchor="center",
  )


def apply_appearance(settings, initial=False):
  global FONT_SIZE, window_w, window_h
  FONT_SIZE, width, height = fit_single_line(root, FONT_FAMILY, settings["font_size"],
      "255.255.255.255", (OUTLINE_WEIGHT * 4 + 40, OUTLINE_WEIGHT * 4 + 20), "bold")
  position = None
  if initial:
    position = (root.winfo_screenwidth() - width - CORNER_MARGIN,
                root.winfo_screenheight() - height - CORNER_MARGIN)
  window_w, window_h = place_within_screen(root, width, height, position)
  redraw_ip(current_ip_str)


appearance = Appearance(root, update_menu, __file__, 72, apply_appearance)
apply_appearance(appearance.settings, initial=True)


def update_ip():
  global current_ip_str
  new_ip = get_ip_address()
  if new_ip != current_ip_str:
    current_ip_str = new_ip
    redraw_ip(current_ip_str)
  # Re-check network IP every 5 seconds
  root.after(5000, update_ip)


# Initial IP draw
update_ip()


# Keep terminal responsive to Ctrl+C
def check_signals():
  root.after(500, check_signals)


root.after(500, check_signals)

try:
  root.mainloop()
except KeyboardInterrupt:
  sys.exit(0)