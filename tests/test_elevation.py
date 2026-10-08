"""Mock Windows process calls; these are not native UAC integration tests."""
import ctypes
from ctypes import wintypes as w
from pathlib import Path, PureWindowsPath
import unittest
from unittest.mock import Mock, patch
import overlay_updater as u


class ElevationTests(unittest.TestCase):
    def test_quoting_and_isolation(self):
        script = PureWindowsPath('C:/Program Files/Clöck Overlays/overlay_updater.py')
        self.assertEqual(u.child_parameters(script),
                         r'-I -S -B "C:\Program Files\Clöck Overlays\overlay_updater.py" --protected-update')

    def api(self, success=True, error=0, code=0):
        class Info(ctypes.Structure):
            _fields_ = [('cbSize', w.DWORD), ('fMask', w.DWORD),
                        ('lpVerb', w.LPCWSTR), ('lpFile', w.LPCWSTR),
                        ('lpParameters', w.LPCWSTR), ('lpDirectory', w.LPCWSTR),
                        ('nShow', ctypes.c_int), ('hProcess', w.HANDLE)]
        shell, kernel = Mock(), Mock()
        def launch(pointer):
            pointer._obj.hProcess = 123 if success else None
            return success
        shell.ShellExecuteExW.side_effect = launch
        kernel.WaitForSingleObject.return_value = 0
        def result(handle, pointer):
            pointer._obj.value = code
            return True
        kernel.GetExitCodeProcess.side_effect = result
        c = Mock(wraps=ctypes)
        c.get_last_error = Mock(return_value=error)
        return (c, w, Info, shell, kernel)

    def test_accept_results_and_handle_cleanup(self):
        for code in (0, 10, 20, 0xC0000005):
            api = self.api(code=code)
            with patch.object(u, 'windows_api', return_value=api):
                if code in (0, 10):
                    self.assertEqual(u.run_elevated(Path('/Python/pythonw.exe'), Path('/Python/python.exe')), u.CHILD_RESULTS[code])
                else:
                    with self.assertRaisesRegex(u.UpdateError, 'did not complete'):
                        u.run_elevated(Path('/app/overlay_updater.py'), Path('/Python/python.exe'))
            api[4].CloseHandle.assert_called_once_with(123)
            info = api[3].ShellExecuteExW.call_args.args[0]._obj
            self.assertEqual(info.lpVerb, 'runas')
            self.assertEqual(info.lpFile, '/Python/python.exe')
            self.assertEqual(info.lpDirectory, '/Python')

    def test_cancel_and_launch_error_no_retry(self):
        for error, message in ((1223, 'cancelled'), (5, 'could not start')):
            api = self.api(success=False, error=error)
            with patch.object(u, 'windows_api', return_value=api):
                with self.assertRaisesRegex(u.UpdateError, message):
                    u.run_elevated(Path('/app/overlay_updater.py'), Path('/Python/pythonw.exe'))
            api[3].ShellExecuteExW.assert_called_once()
            api[4].CloseHandle.assert_not_called()

    def test_wait_error_closes_handle(self):
        api = self.api()
        api[4].WaitForSingleObject.return_value = 0xFFFFFFFF
        with patch.object(u, 'windows_api', return_value=api):
            with self.assertRaisesRegex(u.UpdateError, 'Cannot observe'):
                u.run_elevated(Path('/app/overlay_updater.py'), Path('/Python/pythonw.exe'))
        api[4].CloseHandle.assert_called_once()

    def test_preflight_only_permission_denial(self):
        with patch.object(u.tempfile, 'TemporaryFile', side_effect=PermissionError):
            self.assertTrue(u.elevation_required('/app'))
        with patch.object(u.tempfile, 'TemporaryFile', side_effect=OSError):
            with self.assertRaisesRegex(u.UpdateError, 'no elevation'):
                u.elevation_required('/app')

    def test_standard_admin_and_protected_routes(self):
        directory = Path(u.__file__).parent
        guard = Mock()
        guard.__enter__ = Mock(return_value=guard)
        guard.__exit__ = Mock(return_value=False)
        with patch.object(u.sys, 'platform', 'win32'), \
             patch.object(u, 'is_admin', return_value=False) as admin, \
             patch.object(u, 'elevation_required', return_value=False) as probe,              patch.object(u, 'protected_install', return_value=guard) as trust,              patch.object(u, 'run_elevated', return_value='elevated') as elevate,              patch.object(u, 'FolderUpdater') as folder:
            folder.return_value.update.return_value = 'ordinary'
            self.assertEqual(u.update_checkout(directory), 'ordinary')
            trust.assert_not_called()
            probe.return_value = True
            self.assertEqual(u.update_checkout(directory), 'elevated')
            guard.release_script.assert_called_once()
            elevate.assert_called_once()
            admin.return_value = True
            with self.assertRaisesRegex(u.UpdateError, 'launch normally'):
                u.update_checkout(directory)
            elevate.assert_called_once()

    def test_transaction_failure_never_elevates(self):
        with patch.object(u.sys, 'platform', 'win32'),              patch.object(u, 'is_admin', return_value=False),              patch.object(u, 'elevation_required', return_value=False),              patch.object(u, 'run_elevated') as elevate,              patch.object(u, 'FolderUpdater') as folder:
            folder.return_value.update.side_effect = u.UpdateError('Rollback incomplete')
            with self.assertRaisesRegex(u.UpdateError, 'Rollback incomplete'):
                u.update_checkout(Path(u.__file__).parent)
            elevate.assert_not_called()

    def test_manifest_includes_all_runtime_helpers(self):
        import overlay_windows
        for name in ('overlay_updater.py', 'overlay_windows.py', 'overlay_appearance.py'):
            self.assertIn(name, u.FILES)
            self.assertIn(name, overlay_windows.MANAGED)

    def test_helper_load_ignores_bytecode_cache(self):
        import importlib.machinery
        with patch.object(u, '_windows_helper_module', None), patch.object(importlib.machinery.SourceFileLoader, 'exec_module', side_effect=AssertionError('bytecode loader')):
            helper = u.windows_helper()
            self.assertTrue(hasattr(helper, 'ProtectedInstall'))
            self.assertIs(u.windows_helper(), helper)

    def test_startup_override_never_launches(self):
        api = self.api()
        with patch.object(u, 'windows_api', return_value=api), patch.dict(u.os.environ, {'PYTHONEXECUTABLE': 'untrusted'}):
            with self.assertRaisesRegex(u.UpdateError, 'environment overrides'):
                u.run_elevated(Path('/app/overlay_updater.py'), Path('/Python/python.exe'))
        api[3].ShellExecuteExW.assert_not_called()

    def test_machine_only_tls_context(self):
        import ssl
        helper = Mock()
        helper.machine_root_certificates.return_value = [b'certificate']
        with patch.object(u.sys, 'platform', 'win32'), patch.object(u, 'windows_helper', return_value=helper), patch.object(ssl, 'SSLContext') as context, patch.object(ssl, 'DER_cert_to_PEM_cert', return_value='PEM'):
            u.https_context()
            context.return_value.load_default_certs.assert_not_called()
            context.return_value.load_verify_locations.assert_called_once_with(cadata='PEM')

    def test_sanitized_failure_and_read_only_diagnostic(self):
        helper = u.windows_helper()
        self.assertEqual(u.trust_failure(helper.SecurityError('application directory: untrusted owner')),
                         'application directory: untrusted owner')
        self.assertNotIn('secret', u.trust_failure(OSError('secret private path')))
        guard = Mock()
        guard.__enter__ = Mock(side_effect=helper.SecurityError('Python directory: untrusted owner'))
        guard.__exit__ = Mock(return_value=False)
        with patch.object(helper, 'ProtectedInstall', return_value=guard), patch.object(u, 'FolderUpdater') as update, patch.object(u, 'run_elevated') as elevate, patch('builtins.print') as output:
            self.assertEqual(u.diagnose_trust(), 20)
            update.assert_not_called()
            elevate.assert_not_called()
            self.assertIn('Python directory: untrusted owner', output.call_args.args)

    def test_child_rejects_extra_arguments_or_nonisolated(self):
        with patch.object(u.sys, 'platform', 'win32'),              patch.object(u.sys, 'argv', ['overlay_updater.py', u.CHILD_FLAG, '/target']),              patch.object(u, 'FolderUpdater') as folder:
            self.assertEqual(u.elevated_main(), 20)
            folder.assert_not_called()
