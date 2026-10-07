import ctypes
import os
import sys
import tkinter as tk
import tkinter.font as tkfont
from time import strftime


def resolve_font(
    font_path, font_name, fallback_font="Arial Rounded MT Bold"
):
  """Registers custom font file if present; falls back to built-in Windows rounded font if missing."""
  if os.path.exists(font_path):
    ctypes.windll.gdi32.AddFontResourceExW(
        os.path.abspath(font_path), 0x10, 0
    )
    return font_name
  return fallback_font


# Font & Styling Configuration

# DEFAULT THEME
FONT_FILE = "Nunito-Black.ttf"
TARGET_FONT = "Nunito Black"
TEXT_COLOR = "#E2E8F0"
FONT_SIZE = 72
OUTLINE_WEIGHT = 3
OUTLINE_COLOR = "#0F172A"  # Dark slate stroke border

# HALLOWEEN THEME
#FONT_FILE = "Creepster-Regular.ttf"
#TARGET_FONT = "Creepster"
#TEXT_COLOR = "#FF5500"
#FONT_SIZE = 72
#OUTLINE_WEIGHT = 3
#OUTLINE_COLOR = "#0F172A"  # Dark slate stroke border

# FALL THEME
#FONT_FILE = "BerkshireSwash-Regular.ttf"
#TARGET_FONT = "Berkshire Swash"
#TEXT_COLOR = "#D97706"
#FONT_SIZE = 72
#OUTLINE_WEIGHT = 3
#OUTLINE_COLOR = "#0F172A"  # Dark slate stroke border

# WINTER THEME
#FONT_FILE = "MountainsofChristmas-Bold.ttf"
#TARGET_FONT = "Mountains of Christmas"
#TEXT_COLOR = "#E0F2FE"
#FONT_SIZE = 72
#OUTLINE_WEIGHT = 3
#OUTLINE_COLOR = "#38BDF8"  # Dark slate stroke border



FONT_FAMILY = resolve_font(FONT_FILE, TARGET_FONT, "Arial Rounded MT Bold")

root = tk.Tk()
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


# Calculate geometry using font metrics
measure_font = tkfont.Font(family=FONT_FAMILY, size=FONT_SIZE)
estimated_text = "12:59 PM"
window_w = measure_font.measure(estimated_text) + (OUTLINE_WEIGHT * 4) + 80
window_h = measure_font.metrics("linespace") + (OUTLINE_WEIGHT * 4) + 40

screen_w = root.winfo_screenwidth()
screen_h = root.winfo_screenheight()

top_third_height = screen_h // 3
center_x = (screen_w - window_w) // 2
center_y = max(0, (top_third_height - window_h) // 2)

# Position and size window
root.geometry(f"{window_w}x{window_h}+{center_x}+{center_y}")

# Force window layout update BEFORE executing the first canvas render pass
root.update()


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