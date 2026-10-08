"""Offline regression: execute the actual predecessor updater, then the new one."""
import json
from pathlib import Path
import subprocess
import types
import unittest
from unittest.mock import patch
import overlay_updater as new
import overlay_windows as sec
from test_overlay_updater import FolderTests, encoded
from test_overlay_windows import FakeNative, SCRIPT, PYTHON, USER, SAFE, p


class MigrationTests(unittest.TestCase):
    setUp = FolderTests.setUp
    http = FolderTests.http
    def first_pass(self):
        source = subprocess.check_output(['git', 'show',
            '4d2f9d88e55fb8648f601b7374f9b1679a4c246e:overlay_updater.py'])
        old = types.ModuleType('pre_launcher_updater')
        exec(compile(source, 'pre_launcher_updater.py', 'exec'), old.__dict__)
        self.assertEqual(set(old.FILES), new.PRE_LAUNCHER_FILES)
        # Realistic existing installation and baseline, not a blank first-use state.
        for name in old.FILES:
            data = subprocess.check_output(['git', 'show',
                '4d2f9d88e55fb8648f601b7374f9b1679a4c246e:' + name])
            (self.root / name).write_bytes(data)
        (self.root / new.STATE).write_bytes(encoded({'version': 1, 'commit': 'c'*40,
            'files': {n: new.digest((self.root/n).read_bytes()) for n in old.FILES}}))
        # Published commit contains new code but the already-running updater requests nine.
        for name in new.FILES:
            self.files[name] = (Path(new.__file__).parent/name).read_bytes()
        with patch.object(old, 'download', side_effect=self.http):
            old.FolderUpdater(self.root).update()
        self.assertFalse((self.root/'overlay.bat').exists())
        self.assertEqual(set(json.loads((self.root/new.STATE).read_bytes())['files']), set(old.FILES))
        self.urls.clear()

    def test_real_old_then_new_manifest(self):
        self.first_pass()
        # Trust is established BEFORE the second download with launcher absent.
        api = FakeNative()
        with sec.ProtectedInstall(SCRIPT, PYTHON, _api=api) as guard:
            guard.check_path(p('C:/Overlays/overlay.bat'))
        self.assertEqual(self.urls, [])
        self.engine.update()
        self.assertEqual((self.root/'overlay.bat').read_bytes(), self.files['overlay.bat'])
        self.assertEqual(set(json.loads((self.root/new.STATE).read_bytes())['files']), set(new.FILES))
        self.assertIn('Already up to date', self.engine.update())

    def test_migration_preserves_old_edit_guards(self):
        self.first_pass()
        for name in new.PRE_LAUNCHER_FILES:
            original = (self.root/name).read_bytes()
            for content in (None, b'edited'):
                if content is None: (self.root/name).unlink()
                else: (self.root/name).write_bytes(content)
                with self.assertRaisesRegex(new.UpdateError, 'Local edits'):
                    self.engine.update()
                self.assertFalse(self.urls)
                (self.root/name).write_bytes(original)

    def test_untracked_launcher_collision(self):
        self.first_pass()
        (self.root/'overlay.bat').write_bytes(b'custom launcher')
        with self.assertRaisesRegex(new.UpdateError, 'Untracked overlay.bat'):
            self.engine.update()
        self.assertEqual((self.root/'overlay.bat').read_bytes(), b'custom launcher')
        self.assertFalse(self.urls)
        (self.root/new.STATE).unlink()
        with self.assertRaisesRegex(new.UpdateError, 'Untracked overlay.bat'):
            self.engine.update()

    def test_tracked_launcher_missing_or_edited_blocks(self):
        self.engine.update()
        (self.root/'overlay.bat').unlink()
        with self.assertRaisesRegex(new.UpdateError, 'Local edits'):
            self.engine.update()

    def test_launcher_is_managed_by_trust_policy(self):
        self.assertIn('overlay.bat', sec.MANAGED)
        api = FakeNative()
        api.add('C:/Overlays/overlay.bat', False, aces=SAFE + [(0, 0, 2, USER)])
        with self.assertRaises(sec.SecurityError):
            with sec.ProtectedInstall(SCRIPT, PYTHON, _api=api): pass

    def test_identical_fresh_zip_launcher_adopted_without_replacement(self):
        (self.root/'overlay.bat').write_bytes(self.files['overlay.bat'])
        self.engine.update()
        backup = next((self.root/new.BACKUPS).iterdir())
        self.assertFalse((backup/'overlay.bat').exists())
        self.assertIn('overlay.bat', json.loads((self.root/new.STATE).read_bytes())['files'])

    def test_unknown_baseline_entry_not_accepted(self):
        self.first_pass()
        path = self.root/new.STATE
        state = json.loads(path.read_bytes())
        state['files']['unknown.py'] = 'a'*64
        path.write_bytes(encoded(state))
        with self.assertRaisesRegex(new.UpdateError, 'baseline'):
            self.engine.update()
        self.assertFalse(self.urls)
