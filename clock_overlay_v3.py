import ctypes
import os
import sys
import tkinter as tk
from overlay_updater import attach_update_menu
import tkinter.font as tkfont
from time import strftime


# Original Default theme and size.
FONT_SIZE = 72
OUTLINE_WEIGHT = 3
FONT_FAMILY = "Arial Rounded MT Bold"
TEXT_COLOR = "#E2E8F0"
OUTLINE_COLOR = "#0F172A"
from overlay_appearance import (Appearance, CLOCK_THEMES, local_clock_font,
                                fit_single_line, place_within_screen)

root = tk.Tk()
update_menu = attach_update_menu(root, __file__)
root.title("Clock Overlay")

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

current_time_str = ""


def redraw_clock(time_str):
  """Renders outline stroke pixels first, then layer main text over top."""
  canvas.delete("all")

  # Fall back to calculated window dimensions if canvas hasn't drawn layout bounds yet
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
              text=time_str,
              font=(FONT_FAMILY, FONT_SIZE),
              fill=OUTLINE_COLOR,
              anchor="center",
          )

  # Draw main foreground text
  canvas.create_text(
      cx,
      cy,
      text=time_str,
      font=(FONT_FAMILY, FONT_SIZE),
      fill=TEXT_COLOR,
      anchor="center",
  )


active_theme = None


def apply_appearance(settings, initial=False):
  global FONT_SIZE, FONT_FAMILY, TEXT_COLOR, OUTLINE_COLOR, window_w, window_h, active_theme
  theme = settings["theme"]
  if theme != active_theme:
    FONT_FAMILY = local_clock_font(root, __file__, theme)
    active_theme = theme
  _, _, TEXT_COLOR, OUTLINE_COLOR = CLOCK_THEMES[theme]
  font = tkfont.Font(root=root, family=FONT_FAMILY, size=settings["font_size"])
  samples = [f"{hour}:{minute:02d} {period}" for hour in range(1, 13)
             for minute in range(60) for period in ("AM", "PM")]
  widest = max(samples, key=font.measure)
  FONT_SIZE, width, height = fit_single_line(root, FONT_FAMILY, settings["font_size"],
      widest, (OUTLINE_WEIGHT * 4 + 80, OUTLINE_WEIGHT * 4 + 40))
  position = None
  if initial:
    position = ((root.winfo_screenwidth() - width) // 2,
                max(0, (root.winfo_screenheight() // 3 - height) // 2))
  window_w, window_h = place_within_screen(root, width, height, position)
  redraw_clock(current_time_str or strftime("%I:%M %p").lstrip("0"))


appearance = Appearance(root, update_menu, __file__, 72, apply_appearance, clock=True)
apply_appearance(appearance.settings, initial=True)


def update_time():
  global current_time_str
  new_time = strftime("%I:%M %p").lstrip("0")
  if new_time != current_time_str:
    current_time_str = new_time
    redraw_clock(current_time_str)
  root.after(1000, update_time)


# Initial clock draw
update_time()


# Keep terminal responsive to Ctrl+C
def check_signals():
  root.after(500, check_signals)


root.after(500, check_signals)

try:
  root.mainloop()
except KeyboardInterrupt:
  sys.exit(0)