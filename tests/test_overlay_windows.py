import ntpath
import unittest
from unittest.mock import Mock
import overlay_windows as sec

ADMIN = 'S-1-5-32-544'
USER = 'S-1-5-21-1-2-3-1001'
SAFE = [(0, 3, 0x1F01FF, ADMIN), (0, 3, 0x1200A9, USER)]
BS = chr(92)
def p(value):
    return value.replace('/', BS).lower()
SCRIPT = p('C:/Overlays/overlay_updater.py')
PYTHON = p('C:/Python/python.exe')

class FakeNative:
    def __init__(self):
        self.nodes, self.handles = {}, {}
        self.serial = 0
        self.bad = set()
        for path, directory in [('C:/', True), ('C:/Overlays', True),
                (SCRIPT, False), ('C:/Overlays/overlay_windows.py', False),
                ('C:/Python', True), (PYTHON, False), ('C:/Python/Lib', True),
                ('C:/Python/Lib/os.py', False), ('C:/Python/python313.dll', False),
                ('C:/Overlays/.overlay-update-backups', True)]:
            self.add(path, directory)
    def add(self, path, directory, owner=ADMIN, aces=None):
        self.nodes[p(path)] = [len(self.nodes) + 1, directory, owner,
                              list(SAFE if aces is None else aces)]
    def volume(self, path):
        pass
    def open(self, path, directory):
        if path not in self.nodes:
            raise FileNotFoundError(path)
        if path in self.bad:
            raise sec.SecurityError('Simulated reparse/access failure')
        self.serial += 1
        self.handles[self.serial] = self.nodes[path]
        return self.serial
    def close(self, handle):
        del self.handles[handle]
    def inspect(self, handle):
        return self.handles[handle]
    def children(self, path):
        return [(ntpath.basename(n), v[1]) for n, v in self.nodes.items()
                if n != path and ntpath.dirname(n) == path]

class PolicyTests(unittest.TestCase):
    def test_safe(self):
        sec._acl_policy(ADMIN, SAFE, True, True)
    def test_untrusted_write_rights(self):
        for mask in (2, 4, 16, 64, 256, 0x10000, 0x40000, 0x80000,
                     0x40000000, 0x10000000, 0x02000000):
            with self.subTest(mask=mask), self.assertRaises(sec.SecurityError):
                sec._acl_policy(ADMIN, SAFE + [(0, 0, mask, USER)], False)
    def test_invalid_acl(self):
        for owner, aces in [(USER, SAFE), (ADMIN, None),
                (ADMIN, [(9, 0, 1, ADMIN)]), (ADMIN, [(0, 0x80, 1, ADMIN)]),
                (ADMIN, SAFE + [(0, 8, 2, USER)])]:
            with self.subTest(aces=aces), self.assertRaises(sec.SecurityError):
                sec._acl_policy(owner, aces, True)
    def test_inheritance(self):
        for flags in (0, 1, 2, 7):
            with self.assertRaises(sec.SecurityError):
                sec._acl_policy(ADMIN, [(0, flags, 0x1F01FF, ADMIN)], True, True)
    def test_deny_not_used_to_override_allow(self):
        with self.assertRaises(sec.SecurityError):
            sec._acl_policy(ADMIN, [(1, 0, 2, USER), (0, 0, 2, USER)], False)
    def test_ancestor_creation_is_not_replacement(self):
        sec._acl_policy(ADMIN, SAFE + [(0, 0, 4, USER), (0, 11, 0x1F01FF, 'S-1-3-0')], True, ancestor=True)
        for mask in (2, 64, 0x10000, 0x40000, 0x80000):
            with self.assertRaises(sec.SecurityError):
                sec._acl_policy(ADMIN, SAFE + [(0, 0, mask, USER)], True, ancestor=True)
        with self.assertRaises(sec.SecurityError):
            sec._acl_policy(ADMIN, SAFE + [(0, 0, 4, USER)], True, True)

    def test_paths(self):
        for path in ['relative/x', 'C:x', '//server/x', '//?/C:/x',
                'C:/x:ads', 'C:/x/../y', 'C:/x.', 'C:/x ', 'C:/PROGRA~1/x',
                'C:/NUL.txt', 'C:/x' + chr(0)]:
            with self.subTest(path=path), self.assertRaises(sec.SecurityError):
                sec._path(p(path))

class ContextTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeNative()
    def context(self):
        return sec.ProtectedInstall(SCRIPT, PYTHON, _api=self.api)
    def test_whole_tree_and_cleanup(self):
        with self.context() as guard:
            self.assertEqual(set(self.api.nodes), set(guard.guards))
            guard.revalidate()
        self.assertFalse(self.api.handles)
    def test_runtime_dependency_owner(self):
        self.api.nodes[p('C:/Python/Lib/os.py')][2] = USER
        with self.assertRaises(sec.SecurityError):
            with self.context():
                pass
        self.assertFalse(self.api.handles)
    def test_hostile_backup_acl(self):
        self.api.nodes[p('C:/Overlays/.overlay-update-backups')][3].append((0, 3, 2, USER))
        with self.assertRaises(sec.SecurityError):
            with self.context():
                pass
    def test_bad_ancestor(self):
        self.api.bad.add(p('C:/'))
        with self.assertRaises(sec.SecurityError):
            with self.context():
                pass
        self.assertFalse(self.api.handles)
    def test_identity_and_acl_revalidation(self):
        with self.context() as guard:
            old = self.api.nodes[PYTHON]
            self.api.nodes[PYTHON] = [999, *old[1:]]
            with self.assertRaises(sec.SecurityError):
                guard.revalidate()
            self.api.nodes[PYTHON] = old
            old[3].append((0, 0, 2, USER))
            with self.assertRaises(sec.SecurityError):
                guard.revalidate()
    def test_release_and_destination_checks(self):
        with self.context() as guard:
            guard.release_script()
            self.assertNotIn(SCRIPT, guard.guards)
            self.assertIn(PYTHON, guard.guards)
            self.assertIn(p('C:/Overlays'), guard.guards)
            guard.check_path(SCRIPT)
            guard.check_path(p('C:/Overlays/new.json'))
            with self.assertRaises(sec.SecurityError):
                guard.check_path(p('C:/Other/new.json'))
            self.api.nodes[SCRIPT][2] = USER
            with self.assertRaises(sec.SecurityError):
                guard.check_path(SCRIPT)
    def test_new_directory(self):
        with self.context() as guard:
            guard.release_script()
            guard.check_path(p('C:/Overlays/new'))
            self.api.add('C:/Overlays/new', True)
            guard.check_path(p('C:/Overlays/new'))
            guard.check_path(p('C:/Overlays/new/child.json'))
            self.assertIn(p('C:/Overlays/new'), guard.guards)
    def test_venv_and_custom_paths(self):
        for name in ('pyvenv.cfg', 'python313._pth'):
            api = FakeNative()
            api.add('C:/Python/' + name, False)
            with self.assertRaises(sec.SecurityError):
                with sec.ProtectedInstall(SCRIPT, PYTHON, _api=api):
                    pass
            self.assertFalse(api.handles)
    def test_parent_venv_configuration(self):
        self.api.add('C:/pyvenv.cfg', False)
        with self.assertRaises(sec.SecurityError):
            with self.context():
                pass
        self.assertFalse(self.api.handles)
    def test_pythonw(self):
        self.api.add('C:/Python/pythonw.exe', False)
        with sec.ProtectedInstall(SCRIPT, p('C:/Python/pythonw.exe'), _api=self.api):
            pass

    def test_release_staging(self):
        with self.context() as guard:
            guard.release_script()
            self.api.add('C:/Overlays/.overlay-update-stage-abc', True)
            stage = p('C:/Overlays/.overlay-update-stage-abc')
            guard.check_path(stage)
            self.assertIn(stage, guard.guards)
            guard.release_temporary(stage)
            self.assertNotIn(stage, guard.guards)
            self.assertIn(p('C:/Overlays'), guard.guards)
            with self.assertRaises(sec.SecurityError):
                guard.release_temporary(p('C:/Overlays/.overlay-update-backups'))

    def test_inactive(self):
        with self.assertRaises(sec.SecurityError):
            self.context().check_path(SCRIPT)

class NativeContractTests(unittest.TestCase):
    def test_handle_sharing(self):
        native = object.__new__(sec._Native)
        native.k = Mock()
        native.k.CreateFileW.return_value = 42
        native.open('file', False)
        args = native.k.CreateFileW.call_args.args
        self.assertEqual(args[2], 1)
        self.assertEqual(args[5], 0x02200000)
        native.open('directory', True)
        self.assertEqual(native.k.CreateFileW.call_args.args[2], 3)
    def test_reparse_and_hardlinks_before_acl(self):
        for attrs, links in ((sec.REPARSE, 1), (0, 2)):
            native = object.__new__(sec._Native)
            native.k, native.a = Mock(), Mock()
            def fill(handle, ptr):
                ptr._obj.attrs, ptr._obj.links = attrs, links
                return True
            native.k.GetFileInformationByHandle.side_effect = fill
            with self.assertRaises(sec.SecurityError):
                native.inspect(42)
            native.a.GetSecurityInfo.assert_not_called()

if __name__ == '__main__':
    unittest.main()
