"""Crypt32 contract tests; no Windows store, network or private config access."""
import ctypes
from ctypes import wintypes as w
from pathlib import Path
import ssl
import tempfile
import unittest
from unittest.mock import Mock, patch

import overlay_updater as updater
import overlay_windows as sec


class Crypt32:
    """Consume previous contexts on every enum result, as Crypt32 documents."""
    def __init__(self, rows=((1, b'first'), (1, b'second')), error=-2146885628, opens=True):
        self.rows = iter(rows)
        self.error = error
        self.last_error = 0
        self.active = None
        self.storage = []
        self.CertOpenStore = Mock(side_effect=self.open if opens else lambda *args: self.fail(error))
        self.CertEnumCertificatesInStore = Mock(side_effect=self.enum)
        self.CertFreeCertificateContext = Mock(side_effect=self.free)
        self.CertCloseStore = Mock(side_effect=self.close)

    def fail(self, error):
        self.last_error = error
        return None

    def open(self, provider, encoding, cryptprov, flags, parameter):
        assert ctypes.cast(provider, ctypes.c_void_p).value == 10
        assert encoding == 0 and cryptprov is None
        assert flags == 0x2C000  # LOCAL_MACHINE | OPEN_EXISTING | READONLY
        assert ctypes.wstring_at(parameter) == 'ROOT'
        return 123

    def enum(self, store, previous):
        assert store == 123
        assert previous is self.active
        self.active = None  # consumed even when returning NULL/error
        row = next(self.rows, None)
        if row is None:
            return self.fail(self.error)
        encoding, data = row
        pointer_type = self.CertEnumCertificatesInStore.restype
        buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        context = pointer_type._type_(encoding, buffer, len(data), None, store)
        self.storage.append((buffer, context))
        self.active = ctypes.pointer(context)
        return self.active

    def free(self, pointer):
        assert pointer is self.active  # would detect double-free
        self.active = None
        return True

    def close(self, store, flags):
        assert store == 123 and flags == 0
        assert self.active is None
        self.last_error = 999  # original error must already have been captured
        return True


class MachineTLS(unittest.TestCase):
    def install(self, api):
        loader = patch.object(ctypes, 'WinDLL', return_value=api, create=True)
        self.loader = loader.start()
        self.addCleanup(loader.stop)
        error = patch.object(ctypes, 'get_last_error', side_effect=lambda: api.last_error, create=True)
        error.start()
        self.addCleanup(error.stop)

    def test_success_signed_and_unsigned_end(self):
        for error in (-2146885628, 0x80092004):
            with self.subTest(error=error):
                api = Crypt32(error=error)
                self.install(api)
                self.assertEqual(sec.machine_root_certificates(), [b'first', b'second'])
                self.loader.assert_called_once_with('crypt32', use_last_error=True)
                api.CertFreeCertificateContext.assert_not_called()
                api.CertCloseStore.assert_called_once_with(123, 0)
                self.assertEqual(api.CertOpenStore.argtypes, [w.LPCSTR, w.DWORD, w.HANDLE, w.DWORD, w.LPVOID])
                self.assertIs(api.CertOpenStore.restype, w.HANDLE)
                self.assertEqual(api.CertEnumCertificatesInStore.argtypes,
                                 [w.HANDLE, api.CertEnumCertificatesInStore.restype])
                self.assertEqual(api.CertCloseStore.argtypes, [w.HANDLE, w.DWORD])
                self.assertIs(api.CertCloseStore.restype, w.BOOL)
                self.doCleanups()

    def test_empty_or_non_x509_fails_closed(self):
        for rows in ((), ((0x10000, b'not X509'),)):
            with self.subTest(rows=rows):
                api = Crypt32(rows=rows)
                self.install(api)
                with self.assertRaisesRegex(sec.SecurityError, 'no X.509 root'):
                    sec.machine_root_certificates()
                api.CertFreeCertificateContext.assert_not_called()
                api.CertCloseStore.assert_called_once()
                self.doCleanups()

    def test_open_access_denied(self):
        api = Crypt32(opens=False, error=5)
        self.install(api)
        with self.assertRaisesRegex(sec.SecurityError, r'open machine TLS trust store.*Win32 0x00000005'):
            sec.machine_root_certificates()
        api.CertEnumCertificatesInStore.assert_not_called()
        api.CertCloseStore.assert_not_called()

    def test_enum_errors_never_return_partial_roots(self):
        for error, code in ((5, '00000005'), (-2147024809, '80070057'), (0, '00000000'), (18, '00000012')):
            with self.subTest(error=error):
                api = Crypt32(error=error)
                self.install(api)
                with self.assertRaisesRegex(sec.SecurityError, 'enumerate machine TLS trust store.*0x' + code):
                    sec.machine_root_certificates()
                api.CertFreeCertificateContext.assert_not_called()
                api.CertCloseStore.assert_called_once()
                self.doCleanups()

    def test_copy_failure_frees_current_context_then_closes(self):
        api = Crypt32()
        self.install(api)
        with patch.object(ctypes, 'string_at', side_effect=ValueError('copy failed')):
            with self.assertRaisesRegex(ValueError, 'copy failed'):
                sec.machine_root_certificates()
        api.CertFreeCertificateContext.assert_called_once()
        api.CertCloseStore.assert_called_once()

    def test_windows_ssl_requires_verification_and_machine_roots_only(self):
        api = Crypt32()
        self.install(api)
        with (patch.object(updater.sys, 'platform', 'win32'),
              patch.object(updater, 'windows_helper', return_value=sec),
              patch.object(ssl.SSLContext, 'load_default_certs') as defaults,
              patch.object(ssl.SSLContext, 'load_verify_locations') as load):
            context = updater.https_context()
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        defaults.assert_not_called()
        self.assertEqual([c.kwargs for c in load.call_args_list],
                         [{'cadata': ssl.DER_cert_to_PEM_cert(data)} for data in (b'first', b'second')])

    def test_tls_failure_before_network_stage_or_replacement_cleans_owned_lock(self):
        api = Crypt32(error=5)
        self.install(api)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'overlay_updater.py').write_bytes(b'original')
            engine = updater.FolderUpdater(root)
            with (patch.object(updater.sys, 'platform', 'win32'),
                  patch.object(updater, 'windows_helper', return_value=sec),
                  patch.object(updater, 'build_opener') as network,
                  patch.object(engine, 'staging') as staging):
                with self.assertRaisesRegex(sec.SecurityError, '0x00000005'):
                    engine.update()
            network.assert_not_called()
            staging.assert_not_called()
            self.assertEqual(list(root.iterdir()), [root / 'overlay_updater.py'])
            self.assertEqual((root / 'overlay_updater.py').read_bytes(), b'original')

    def test_preexisting_lock_is_never_cleared(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock = root / updater.LOCK
            lock.write_bytes(b'previous transaction')
            with patch.object(updater, 'download') as download:
                with self.assertRaisesRegex(updater.UpdateError, 'interrupted'):
                    updater.FolderUpdater(root).update()
            download.assert_not_called()
            self.assertEqual(lock.read_bytes(), b'previous transaction')


if __name__ == '__main__':
    unittest.main()
