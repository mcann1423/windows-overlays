import ast
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import sys
import types

# CI may not have Tcl/Tk installed; every GUI boundary is mocked below.
try:
    import tkinter
except ModuleNotFoundError:
    tkinter = types.ModuleType("tkinter")
    tkinter.Menu = Mock()
    tkinter.IntVar = Mock()
    tkinter.StringVar = Mock()
    tkinter.font = types.SimpleNamespace(Font=Mock(), families=Mock())
    tkinter.messagebox = types.SimpleNamespace(showwarning=Mock())
    tkinter.simpledialog = types.SimpleNamespace(askinteger=Mock())
    with patch.dict(sys.modules, {"tkinter": tkinter}):
        import overlay_appearance as appearance
else:
    import overlay_appearance as appearance


class FakeFont:
    def __init__(self, **kwargs):
        self.size = kwargs["size"]

    def measure(self, text):
        return len(text) * self.size

    def metrics(self, name):
        return self.size * 2

    def configure(self, **kwargs):
        self.size = kwargs["size"]


class AppearanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.env = patch.dict("os.environ", {"LOCALAPPDATA": str(self.base)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def root(self):
        root = Mock()
        root.winfo_screenwidth.return_value = 800
        root.winfo_screenheight.return_value = 600
        root.winfo_x.return_value = 700
        root.winfo_y.return_value = -10
        return root

    def controller(self, clock=False):
        with patch.object(appearance.tk, "Menu"), patch.object(appearance.tk, "IntVar"), patch.object(appearance.tk, "StringVar"):
            return appearance.Appearance(self.root(), Mock(), "clock_overlay_v3.py", 72, Mock(), clock)

    def test_user_scoped_independent_settings(self):
        one = appearance.settings_path("/Program Files/Overlays/ip_overlay.py")
        two = appearance.settings_path("/Program Files/Overlays/ceel_cal_overlay.py")
        self.assertEqual(one, self.base / "DesktopOverlays/ip_overlay.json")
        self.assertNotEqual(one, two)
        appearance.save_settings(one, {"font_size": 96, "theme": "Winter"})
        self.assertEqual(appearance.load_settings(one, 72), {"font_size": 96, "theme": "Winter"})
        self.assertEqual(appearance.load_settings(two, 20)["font_size"], 20)
        self.assertFalse(list(one.parent.glob("*.tmp")))

    def test_corrupt_and_invalid_settings_preserve_defaults(self):
        path = self.base / "settings.json"
        for value in ['{', '[]', '{"font_size":true,"theme":[]}', '{"font_size":10000,"theme":"bogus"}', '{"font_size":"20"}']:
            path.write_text(value)
            self.assertEqual(appearance.load_settings(path, 72), {"font_size": 72, "theme": "Default"})

    def test_failed_atomic_replace_preserves_previous_file(self):
        path = self.base / "settings.json"
        appearance.save_settings(path, {"font_size": 20})
        with patch.object(appearance.os, "replace", side_effect=PermissionError):
            with self.assertRaises(PermissionError):
                appearance.save_settings(path, {"font_size": 96})
        self.assertEqual(json.loads(path.read_text()), {"font_size": 20})
        self.assertFalse(list(self.base.glob("*.tmp")))

    def test_size_theme_apply_and_persist_immediately(self):
        controller = self.controller(clock=True)
        controller.set_size(96)
        controller.apply.assert_called_once_with(controller.settings)
        controller.set_theme("Winter")
        self.assertEqual(appearance.load_settings(controller.path, 72), {"font_size": 96, "theme": "Winter"})
        controller.set_size(controller.default_size)
        self.assertEqual(controller.settings["font_size"], 72)
        for value in (0, 7, 145, True, "20", 20.5):
            controller.set_size(value)
        self.assertEqual(controller.settings["font_size"], 72)

    def test_custom_size_cancel_and_bounds(self):
        controller = self.controller()
        with patch.object(appearance.simpledialog, "askinteger", return_value=None) as ask:
            controller.custom_size()
        controller.apply.assert_not_called()
        self.assertEqual(ask.call_args.kwargs["minvalue"], 8)
        self.assertEqual(ask.call_args.kwargs["maxvalue"], 144)

    def test_save_error_does_not_undo_live_change(self):
        controller = self.controller()
        with patch.object(appearance, "save_settings", side_effect=PermissionError), patch.object(appearance.messagebox, "showwarning") as warning:
            controller.set_size(48)
        controller.apply.assert_called_once()
        warning.assert_called_once()

    def test_menus_append_without_replacing_update(self):
        menu = Mock()
        with patch.object(appearance.tk, "Menu"), patch.object(appearance.tk, "IntVar"), patch.object(appearance.tk, "StringVar"):
            appearance.Appearance(self.root(), menu, "clock.py", 72, Mock(), True)
        self.assertEqual([c.kwargs["label"] for c in menu.add_cascade.call_args_list], ["Font size", "Theme"])
        menu.delete.assert_not_called()
        menu.entryconfigure.assert_not_called()

    def test_missing_font_is_explicit_local_fallback(self):
        with patch.object(appearance.messagebox, "showwarning") as warning:
            family = appearance.local_clock_font(self.root(), self.base / "clock.py", "Winter")
        self.assertEqual(family, "Arial Rounded MT Bold")
        self.assertIn("No fonts were downloaded", warning.call_args.args[1])

    def test_local_font_registration_uses_script_directory(self):
        (self.base / "Creepster-Regular.ttf").write_bytes(b"font fixture")
        windll = Mock()
        with patch.object(appearance.ctypes, "windll", windll, create=True), patch.object(appearance.tkfont, "families", return_value=["Creepster"]):
            self.assertEqual(appearance.local_clock_font(self.root(), self.base / "clock.py", "Halloween"), "Creepster")
        windll.gdi32.AddFontResourceExW.assert_called_once_with(str(self.base / "Creepster-Regular.ttf"), 0x10, None)

    def test_geometry_bounded_and_preserves_drag_when_possible(self):
        root = self.root()
        self.assertEqual(appearance.place_within_screen(root, 300, 200), (300, 200))
        root.geometry.assert_called_with("300x200+500+0")
        appearance.place_within_screen(root, 9999, 9999)
        root.geometry.assert_called_with("800x600+0+0")
        appearance.place_within_screen(root, 200, 100, (123, 234))
        root.geometry.assert_called_with("200x100+123+234")

    @patch.object(appearance.tkfont, "Font", FakeFont)
    def test_single_line_measured_fit(self):
        size, width, height = appearance.fit_single_line(self.root(), "Arial", 144, "255.255.255.255", (52, 32), "bold")
        self.assertLess(size, 144)
        self.assertLessEqual(width, 800)
        self.assertLessEqual(height, 600)

    @patch.object(appearance.tkfont, "Font", FakeFont)
    def test_calendar_measures_wrapping_and_bounds(self):
        canvas = Mock()
        canvas.bbox.return_value = (20, 20, 780, 1400)
        width, height, content = appearance.calendar_layout(self.root(), canvas, "long event " * 30, "Arial", 96, 220, 492)
        self.assertEqual((width, height, content), (800, 600, 1420))
        self.assertEqual(canvas.create_text.call_args.kwargs["width"], 760)
        canvas.delete.assert_called_once()

    def test_deep_json_and_restart(self):
        path = self.base / 'settings.json'
        path.write_text('[' * 1500 + ']' * 1500)
        self.assertEqual(appearance.load_settings(path, 72)['font_size'], 72)
        first = self.controller(True)
        first.set_size(48)
        first.set_theme('Fall')
        self.assertEqual(self.controller(True).settings, first.settings)

    def test_secondary_monitor_negative_coordinates(self):
        root = self.root()
        root.winfo_x.return_value = -1000
        root.winfo_y.return_value = 100
        with patch.object(appearance, 'monitor_bounds', return_value=(-1920, 0, 0, 1080)):
            appearance.place_within_screen(root, 300, 200)
        root.geometry.assert_called_with('300x200+-1000+100')

    def test_registration_cached_and_failure_falls_back(self):
        font = self.base / 'Creepster-Regular.ttf'
        font.write_bytes(b'font fixture')
        windll = Mock()
        with patch.object(appearance, '_registered_fonts', set()), patch.object(appearance.ctypes, 'windll', windll, create=True), patch.object(appearance.tkfont, 'families', return_value=['Creepster']), patch.object(appearance.messagebox, 'showwarning'):
            for _ in range(3):
                appearance.local_clock_font(self.root(), self.base / 'clock.py', 'Halloween')
            windll.gdi32.AddFontResourceExW.assert_called_once()
        with patch.object(appearance, '_registered_fonts', set()), patch.object(appearance.ctypes, 'windll', windll, create=True), patch.object(appearance.messagebox, 'showwarning') as warning:
            windll.gdi32.AddFontResourceExW.return_value = 0
            self.assertEqual(appearance.local_clock_font(self.root(), self.base / 'clock.py', 'Halloween'), 'Arial Rounded MT Bold')
            warning.assert_called_once()

    def test_calendar_refresh_preserves_scroll_and_dragged_position(self):
        base = Path(appearance.__file__).parent
        for name in ('cchl_cal_overlay.py', 'ceel_cal_overlay.py'):
            tree = ast.parse((base / name).read_text())
            function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'apply_appearance')
            canvas = Mock()
            canvas.yview.return_value = (0.4, 0.8)
            canvas.bbox.return_value = (20, 20, 700, 1300)
            place = Mock(return_value=(700, 600))
            env = dict(canvas=canvas, root=self.root(), EVENT_FONT_SIZE=20,
                       window_w=700, window_h=600, default_window_w=220,
                       default_window_h=492, current_schedule_text='unchanged',
                       FONT_FAMILY='Arial', redraw_calendar=Mock(),
                       place_within_screen=place, calendar_layout=Mock(return_value=(700,600,1300)))
            exec(compile(ast.Module(body=[function], type_ignores=[]), name, 'exec'), env)
            env['apply_appearance']({'font_size':20}, refresh=True)
            place.assert_not_called()
            canvas.yview_moveto.assert_called_with(0.4)
            env['apply_appearance']({'font_size':48})
            place.assert_called_once()
            canvas.yview_moveto.assert_called_with(0)

    def test_all_published_scripts_integrate_without_network(self):
        base = Path(appearance.__file__).parent
        for name in ("clock_overlay_v3.py", "ip_overlay.py", "cchl_cal_overlay.py", "ceel_cal_overlay.py"):
            tree = ast.parse((base / name).read_text())
            calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
            self.assertTrue(any(node.func.id == "Appearance" for node in calls), name)
            self.assertTrue(any(node.func.id == "attach_update_menu" for node in calls), name)


if __name__ == "__main__":
    unittest.main()
