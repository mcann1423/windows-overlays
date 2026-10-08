"""Local-only overlay appearance, menus, and measured screen-bounded layout."""
import ctypes
import json
import os
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import font as tkfont, messagebox, simpledialog

MIN_FONT_SIZE = 8
MAX_FONT_SIZE = 144
MAX_OUTLINE_WEIGHT = 5


def valid_outline(value):
    return type(value) is int and 0 <= value <= MAX_OUTLINE_WEIGHT


def outline_padding(horizontal, vertical):
    """Reserve stroke space without changing the validated layout or anchor.

    Existing single-line padding already exceeds twice the maximum radius.
    Keeping this floor also prevents edge-clamping drift when cycling weights.
    """
    return max(horizontal, 2 * MAX_OUTLINE_WEIGHT + 4), max(vertical, 2 * MAX_OUTLINE_WEIGHT + 4)


CLOCK_THEMES = {
    "Default": ("Nunito-Black.ttf", "Nunito Black", "#E2E8F0", "#0F172A"),
    "Halloween": ("Creepster-Regular.ttf", "Creepster", "#FF5500", "#0F172A"),
    "Fall": ("BerkshireSwash-Regular.ttf", "Berkshire Swash", "#D97706", "#0F172A"),
    "Winter": ("MountainsofChristmas-Bold.ttf", "Mountains of Christmas", "#E0F2FE", "#38BDF8"),
}


def valid_size(value):
    return type(value) is int and MIN_FONT_SIZE <= value <= MAX_FONT_SIZE


def settings_path(script_file):
    # Never write beside the application (which may be in Program Files).
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share")
    return base / "DesktopOverlays" / (Path(script_file).stem + ".json")


def load_settings(path, default_size, default_outline=3):
    result = {"font_size": default_size, "theme": "Default", "outline_weight": default_outline}
    try:
        with path.open("r", encoding="utf-8") as stream:
            text = stream.read(4097)
        if len(text) > 4096:
            return result
        data = json.loads(text)
        if isinstance(data, dict):
            if valid_outline(data.get("outline_weight")):
                result["outline_weight"] = data["outline_weight"]
            if valid_size(data.get("font_size")):
                result["font_size"] = data["font_size"]
            if isinstance(data.get("theme"), str) and data["theme"] in CLOCK_THEMES:
                result["theme"] = data["theme"]
    except (OSError, ValueError, UnicodeError, RecursionError):
        pass
    return result


def save_settings(path, settings):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", suffix=".tmp", delete=False) as stream:
            temporary = stream.name
            json.dump(settings, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


_registered_fonts = set()


def local_clock_font(root, script_file, theme):
    filename, family, _, _ = CLOCK_THEMES[theme]
    path = Path(script_file).resolve().parent / filename
    loaded = str(path) in _registered_fonts
    if not loaded and path.is_file():
        try:
            register = ctypes.windll.gdi32.AddFontResourceExW
            register.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_void_p]
            register.restype = ctypes.c_int
            loaded = bool(register(str(path), 0x10, None))
            if loaded:
                _registered_fonts.add(str(path))
        except (AttributeError, OSError):
            pass
    if loaded and family.casefold() in {name.casefold() for name in tkfont.families(root)}:
        return family
    fallback = "Arial Rounded MT Bold"
    messagebox.showwarning("Clock font fallback",
        f"The local font {filename} ({family}) is missing or unavailable. "
        f"Using {fallback} (or the system substitute). No fonts were downloaded.", parent=root)
    return fallback


class Appearance:
    def __init__(self, root, menu, script_file, default_size, apply, clock=False, default_outline=3):
        self.root, self.path, self.apply = root, settings_path(script_file), apply
        self.default_size, self.clock = default_size, clock
        self.settings = load_settings(self.path, default_size, default_outline)
        self.size_var = tk.IntVar(master=root, value=self.settings["font_size"])
        self.theme_var = tk.StringVar(master=root, value=self.settings["theme"])
        menu.add_separator()
        sizes = tk.Menu(menu, tearoff=False)
        for size in sorted({12, 14, 16, 20, 24, 32, 48, 60, 72, 96, 120, 144, default_size}):
            sizes.add_radiobutton(label=f"{size} pt", variable=self.size_var, value=size,
                                  command=lambda value=size: self.set_size(value))
        sizes.add_command(label="Custom…", command=self.custom_size)
        sizes.add_command(label=f"Reset default ({default_size} pt)",
                          command=lambda: self.set_size(default_size))
        menu.add_cascade(label="Font size", menu=sizes)
        self.outline_var = tk.IntVar(master=root, value=self.settings["outline_weight"])
        outlines = tk.Menu(menu, tearoff=False)
        for weight in range(MAX_OUTLINE_WEIGHT + 1):
            label = "None (0 px)" if weight == 0 else f"{weight} px"
            outlines.add_radiobutton(label=label, variable=self.outline_var, value=weight,
                                     command=lambda value=weight: self.set_outline(value))
        outlines.add_command(label=f"Reset default ({default_outline} px)",
                             command=lambda: self.set_outline(default_outline))
        menu.add_cascade(label="Outline weight", menu=outlines)
        if clock:
            themes = tk.Menu(menu, tearoff=False)
            for name in CLOCK_THEMES:
                themes.add_radiobutton(label=name, variable=self.theme_var, value=name,
                                      command=lambda value=name: self.set_theme(value))
            menu.add_cascade(label="Theme", menu=themes)

    def custom_size(self):
        value = simpledialog.askinteger("Font size", f"Size in points ({MIN_FONT_SIZE}–{MAX_FONT_SIZE}):",
            parent=self.root, initialvalue=self.settings["font_size"],
            minvalue=MIN_FONT_SIZE, maxvalue=MAX_FONT_SIZE)
        if value is not None:
            self.set_size(value)

    def set_size(self, size):
        if not valid_size(size):
            return
        self.settings["font_size"] = size
        self.size_var.set(size)
        self.changed()

    def set_outline(self, weight):
        if valid_outline(weight):
            self.settings["outline_weight"] = weight
            self.outline_var.set(weight)
            self.changed()

    def set_theme(self, theme):
        if self.clock and theme in CLOCK_THEMES:
            self.settings["theme"] = theme
            self.theme_var.set(theme)
            self.changed()

    def changed(self):
        self.apply(self.settings)
        try:
            save_settings(self.path, self.settings)
        except OSError:
            messagebox.showwarning("Appearance settings", "Appearance applied, but could not save your per-user settings.", parent=self.root)


def monitor_bounds(root):
    """Use the current Windows monitor, with a portable primary-screen fallback."""
    if os.name == 'nt':
        try:
            from ctypes import wintypes as w
            class MonitorInfo(ctypes.Structure):
                _fields_ = [('size', w.DWORD), ('monitor', w.RECT),
                            ('work', w.RECT), ('flags', w.DWORD)]
            user = ctypes.WinDLL('user32', use_last_error=True)
            user.MonitorFromWindow.argtypes = [w.HWND, w.DWORD]
            user.MonitorFromWindow.restype = w.HANDLE
            user.GetMonitorInfoW.argtypes = [w.HANDLE, ctypes.POINTER(MonitorInfo)]
            user.GetMonitorInfoW.restype = w.BOOL
            info = MonitorInfo()
            info.size = ctypes.sizeof(info)
            if user.GetMonitorInfoW(user.MonitorFromWindow(root.winfo_id(), 2), ctypes.byref(info)):
                r = info.work
                return r.left, r.top, r.right, r.bottom
        except (AttributeError, OSError):
            pass
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


def place_within_screen(root, width, height, position=None, bounds=None):
    left, top, right, bottom = bounds or monitor_bounds(root)
    sw, sh = right - left, bottom - top
    width, height = max(1, min(int(width), sw)), max(1, min(int(height), sh))
    x, y = position if position is not None else (root.winfo_x(), root.winfo_y())
    x, y = max(left, min(int(x), right - width)), max(top, min(int(y), bottom - height))
    root.geometry(f"{width}x{height}+{x}+{y}")
    root.update_idletasks()
    return width, height


def fit_single_line(root, family, size, text, padding, weight="normal"):
    """Keep the selected size in settings; shrink rendering only on small screens."""
    font = tkfont.Font(root=root, family=family, size=size, weight=weight)
    left, top, right, bottom = monitor_bounds(root)
    while size > 1:
        width = font.measure(text) + padding[0]
        height = font.metrics("linespace") + padding[1]
        if width <= right - left and height <= bottom - top:
            break
        size -= 1
        font.configure(size=size)
    return size, font.measure(text) + padding[0], font.metrics("linespace") + padding[1]


def calendar_zone(root, position):
    """Original three columns, relative to the current monitor work area."""
    left, top, right, bottom = monitor_bounds(root)
    index = {"left": 0, "center": 1, "right": 2}.get(position.lower().strip(), 2)
    span = right - left
    return left + span * index // 3, top, left + span * (index + 1) // 3, bottom


def calendar_layout(root, canvas, text, family, size, default_width, default_height):
    """Wrap at the designated column width; never grow horizontally for text."""
    left, top, right, bottom = monitor_bounds(root)
    width = max(1, min(default_width, (right - left) // 3))
    item = canvas.create_text(20, 20, text=text, font=(family, size, "bold"),
                              anchor="nw", width=max(1, width - 40))
    bounds = canvas.bbox(item)
    canvas.delete(item)
    content_height = (bounds[3] + 20) if bounds else 40
    return width, max(1, min(bottom - top, default_height)), content_height


def clock_position(bounds, width, height, anchor=None):
    """Keep an invariant center, not the previous size's top-left corner."""
    left, top, right, bottom = bounds
    cx, cy = anchor if anchor is not None else ((left + right) / 2,
                                               top + (bottom - top) // 3 / 2)
    return round(cx - width / 2), round(cy - height / 2)
