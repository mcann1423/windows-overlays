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
                (ADMIN, [(9, 0, 1, ADMIN)]), (ADMIN, [(0, 0x80, 1, ADMIN)])]:
            with self.subTest(aces=aces), self.assertRaises(sec.SecurityError):
                sec._acl_policy(owner, aces, True)
    def test_inheritance(self):
        for flags in (0, 1, 2, 7):
            with self.assertRaises(sec.SecurityError):
                sec._acl_policy(ADMIN, [(0, flags, 0x1F01FF, ADMIN)], True, True)
    def test_generic_file_mapping(self):
        for mask, expected in [(0x80000000, 0x120089), (0x40000000, 0x120116),
                               (0x20000000, 0x1200A0), (0x10000000, 0x1F01FF),
                               (0xA0000000, 0x1200A9), (0x82000000, 0x2120089)]:
            self.assertEqual(sec._file_rights(mask), expected)
        for flags in (3, 11, 19, 27):
            sec._acl_policy(ADMIN, [(0, flags, 0x10000000, ADMIN)], True, True)
        for mask in (0x80000000, 0x20000000, 0xA0000000):
            sec._acl_policy(ADMIN, SAFE + [(0, 19, mask, USER)], True, True)

    def test_inherit_only_never_grants_current_object_access(self):
        # Includes screenshot flags 0x1B, but makes no assumption about its SID.
        for sid in (USER, 'S-1-3-0', 'S-1-3-4', 'S-1-1-0', 'S-1-3-1'):
            for flags in (8, 9, 10, 11, 15, 24, 25, 26, 27, 31):
                for directory in (False, True):
                    with self.subTest(sid=sid, flags=flags, directory=directory):
                        sec._acl_policy(ADMIN, SAFE + [(0, flags, 0x10000000, sid)], directory)
                        with self.assertRaises(sec.SecurityError):
                            sec._acl_policy(ADMIN, SAFE + [(0, flags & ~8, 0x10000000, sid)], directory)
        # Unsupported ACEs/flags remain unsupported, even when inherit-only.
        for kind, flags in ((9, 27), (0, 0x9B)):
            with self.assertRaises(sec.SecurityError):
                sec._acl_policy(ADMIN, SAFE + [(kind, flags, 0x10000000, USER)], True)

    def test_child_creation_policy_distinguishes_creator_owner(self):
        sec._acl_policy(ADMIN, SAFE + [(0, 27, 0x10000000, 'S-1-3-0')], True, True)
        for sid in (USER, 'S-1-3-4', 'S-1-1-0', 'S-1-3-1'):
            for flags in (9, 10, 11, 15, 25, 26, 27, 31):
                with self.subTest(sid=sid, flags=flags):
                    with self.assertRaisesRegex(sec.SecurityError, 'child write rights'):
                        sec._acl_policy(ADMIN, SAFE + [(0, flags, 0x10000000, sid)], True, True)
        # CREATOR OWNER cannot supply the required trusted inheritance grant.
        with self.assertRaisesRegex(sec.SecurityError, 'lacks safe inheritable'):
            sec._acl_policy(ADMIN, [(0, 27, 0x10000000, 'S-1-3-0')], True, True)

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

    def test_full_control_is_not_a_trustee_identity(self):
        sec._acl_policy(ADMIN, [(0, 3, 0x1F01FF, ADMIN)], True, ancestor=True)
        for sid, label in [('S-1-1-0', 'Everyone'),
                           ('S-1-5-11', 'Authenticated Users'),
                           ('S-1-3-0', 'CREATOR OWNER'),
                           ('S-1-3-4', 'OWNER RIGHTS'),
                           (USER, 'account/domain SID')]:
            with self.subTest(sid=sid), self.assertRaises(sec.SecurityError) as error:
                sec._acl_policy(ADMIN, SAFE + [(0, 3, 0x1F01FF, sid)], True, ancestor=True)
            self.assertIn(label, str(error.exception))
            self.assertIn('applies to object; ancestor directory', str(error.exception))
            self.assertNotIn(USER, str(error.exception))

    def test_default_style_ancestor_inheritance_not_blanket_trust(self):
        # Representative pattern, not a claim about every Windows installation:
        # Users can create subdirectories; creator full control is inherit-only.
        aces = SAFE + [(0, 2, 4, 'S-1-5-32-545'), (0, 11, 0x1F01FF, 'S-1-3-0')]
        sec._acl_policy(ADMIN, aces, True, ancestor=True)
        # Its actual protected descendants must still pass their own policy.
        for flags in (3, 19):
            with self.assertRaises(sec.SecurityError):
                sec._acl_policy(ADMIN, SAFE + [(0, flags, 0x1F01FF, USER)], True)
        for mask in (0x40, 0x10000, 0x40000, 0x80000, 0x1F01FF):
            with self.assertRaises(sec.SecurityError):
                sec._acl_policy(ADMIN, aces + [(0, 3, mask, USER)], True, ancestor=True)

    def test_trustee_diagnostics_are_bounded_and_sanitized(self):
        for sid in [USER, 'S-1-5-80-123456789', 'malicious\nprivate-path']:
            self.assertNotIn(sid, sec._trustee_label(sid))
        with self.assertRaisesRegex(sec.SecurityError, 'untrusted owner.*redacted'):
            sec._acl_policy(USER, SAFE, True)

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
    def test_default_style_split_generic_creator_acl(self):
        # Representative inherited DACL: effective mapped admin grant plus an
        # unmapped inherit-only CREATOR OWNER grant. Not a captured user DACL.
        for node in self.api.nodes.values():
            node[3] = [(0, 16, 0x1F01FF, ADMIN), (0, 16, 0x1200A9, 'S-1-5-32-545')]
            if node[1]:
                node[3] += [(0, 27, 0x10000000, ADMIN), (0, 27, 0x10000000, 'S-1-3-0')]
        with self.context() as guard:
            self.assertEqual(set(guard.guards), set(self.api.nodes))
            guard.revalidate()
        self.assertFalse(self.api.handles)

    def test_runtime_descendants_checked_after_inherit_only_parent(self):
        for child in ('C:/Python/Lib', 'C:/Python/Lib/os.py', 'C:/Python/python313.dll'):
            for mask in (0x10000000, 0x1F01FF, 2, 4, 0x40000000):
                for sid in (USER, 'S-1-3-4', 'S-1-1-0'):
                    with self.subTest(child=child, mask=mask, sid=sid):
                        self.api = FakeNative()
                        self.api.nodes[p('C:/Python')][3].append((0, 27, 0x10000000, sid))
                        self.api.nodes[p(child)][3].append((0, 16, mask, sid))
                        with self.assertRaisesRegex(sec.SecurityError, 'Python tree entry: .*write rights'):
                            with self.context():
                                pass
                        self.assertFalse(self.api.handles)

    def test_runtime_child_creation_and_revalidation_still_blocked(self):
        with self.context() as guard:
            for directory in ('C:/Python', 'C:/Python/Lib'):
                node = self.api.nodes[p(directory)]
                node[3].append((0, 27, 0x10000000, USER))
                guard.revalidate()  # Non-effective template alone is harmless here.
                for mask in (2, 4, 0x40, 0x10000000):
                    node[3].append((0, 19, mask, USER))
                    with self.assertRaises(sec.SecurityError):
                        guard.revalidate()
                    node[3].pop()

    def test_new_children_must_pass_actual_owner_and_acl(self):
        with self.context() as guard:
            self.api.nodes[p('C:/Overlays')][3].append((0, 27, 0x10000000, 'S-1-3-0'))
            guard.check_path(p('C:/Overlays/new'))
            self.api.add('C:/Overlays/new', True, owner=USER)
            with self.assertRaises(sec.SecurityError):
                guard.check_path(p('C:/Overlays/new'))
            self.api.nodes[p('C:/Overlays/new')][2] = ADMIN
            self.api.nodes[p('C:/Overlays/new')][3].append((0, 16, 0x1F01FF, USER))
            with self.assertRaises(sec.SecurityError):
                guard.check_path(p('C:/Overlays/new'))
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

    def test_landmarks_normalize_windows_case(self):
        self.api.add('C:/Python/DLLs', True)
        self.api.add('C:/Python/Lib/encodings', True)
        self.api.add('C:/Python/Lib/encodings/__init__.py', False)
        with self.context() as guard:
            guard._runtime_landmarks((3,13))
            del guard.guards[p('C:/Python/Lib/os.py')]
            with self.assertRaisesRegex(sec.SecurityError, 'landmark missing: Lib'):
                guard._runtime_landmarks((3,13))

    def test_diagnostic_scope_mask_and_no_private_path(self):
        self.api.nodes[p('C:/Python/Lib/os.py')][3].append((0,0,2,USER))
        with self.assertRaisesRegex(sec.SecurityError, r'Python tree entry: .*ACE 2, mask 0x00000002') as error:
            with self.context():
                pass
        self.assertNotIn(USER,str(error.exception))
        self.assertNotIn('os.py',str(error.exception))
        self.assertFalse(self.api.handles)

    def test_ancestor_depth_is_from_drive_root(self):
        guard = self.context()
        self.assertEqual(guard._label(p('C:/')), 'installation ancestor (depth 0)')
        self.assertEqual(guard._label(p('C:/Program Files')), 'installation ancestor (depth 1)')
        self.assertEqual(guard._label(p('C:/Program Files/Python Software Foundation')),
                         'installation ancestor (depth 2)')
        self.assertEqual(guard._label(p('C:/Overlays')), 'application directory')
        guard.local_details = True
        self.assertEqual(guard._label(p('C:/Program Files')), p('C:/Program Files'))

    def test_ancestor_namespace_replacement_is_rejected(self):
        with self.context() as guard:
            root = p('C:/')
            old = self.api.nodes[root]
            # Even a replacement with equally safe ACLs must not change identity.
            self.api.nodes[root] = [999, *old[1:]]
            with self.assertRaisesRegex(sec.SecurityError, 'pathname identity changed'):
                guard.revalidate()
        self.assertFalse(self.api.handles)

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
