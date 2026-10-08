"""No Git, real HTTP, calendar data or GUI imports required."""
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import sys
import types
from urllib.error import HTTPError, URLError
import overlay_updater as updater


def encoded(value):
    return json.dumps(value).encode()


class FolderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.engine = updater.FolderUpdater(self.root)
        self.sha = 'a' * 40
        self.files = {n: b'x = 1\n' for n in updater.FILES}
        self.files['README.md'] = b'# Windows desktop overlays\n'
        self.files['calendar_config.example.json'] = encoded({
            'cchl_ical_url': 'YOUR_GOOGLE_CALENDAR_SECRET_ICAL_URL',
            'ceel_ical_url': 'YOUR_GOOGLE_CALENDAR_SECRET_ICAL_URL'})
        self.urls = []
        self.mock = patch.object(updater, 'download', side_effect=self.http).start()
        self.addCleanup(patch.stopall)

    def http(self, url, limit=updater.MAX_FILE):
        self.urls.append(url)
        if url == updater.API + '/commits/main':
            return encoded({'sha': self.sha})
        if url == updater.API + '/git/trees/' + self.sha:
            return encoded({'truncated': False, 'tree': [dict(path=n, mode='100644',
                type='blob', size=len(data), sha=updater.blob_digest(data))
                for n, data in self.files.items()]})
        prefix = updater.RAW + '/' + self.sha + '/'
        self.assertTrue(url.startswith(prefix))
        return self.files[url[len(prefix):]]

    def installed(self):
        return {n: (self.root / n).read_bytes() if (self.root / n).exists() else None
                for n in (*updater.FILES, updater.STATE)}

    def test_zip_first_install_current_new_self_update(self):
        (self.root / 'overlay_updater.py').write_bytes(b'old edited code')
        self.assertIn('First-use', self.engine.update())
        backup = next((self.root / updater.BACKUPS).iterdir())
        self.assertEqual((backup / 'overlay_updater.py').read_bytes(), b'old edited code')
        self.assertFalse((self.root / '.git').exists())
        self.assertEqual(self.urls.count(updater.API + '/commits/main'), 1)
        self.assertIn('Already up to date', self.engine.update())
        self.sha = 'b' * 40
        self.files['overlay_updater.py'] = b'x = 2\n'
        self.assertIn('Restart ALL', self.engine.update())
        self.assertEqual((self.root / 'overlay_updater.py').read_bytes(), b'x = 2\n')
        self.assertEqual(json.loads((self.root / updater.STATE).read_text())['commit'], self.sha)

    def test_guarded_transaction_and_stage_release(self):
        guard = Mock()
        engine = updater.FolderUpdater(self.root, guard=guard)
        engine.update()
        names = [call.args[0].name for call in guard.check_path.call_args_list]
        self.assertIn(updater.LOCK, names)
        self.assertIn('recovery.json', names)
        self.assertIn(updater.STATE, names)
        guard.release_temporary.assert_called_once()
        self.assertFalse(guard.release_temporary.call_args.args[0].exists())

    def test_guard_denial_prevents_download(self):
        guard = Mock()
        guard.check_path.side_effect = RuntimeError('ACL changed')
        with self.assertRaisesRegex(updater.UpdateError, 'trust changed'):
            updater.FolderUpdater(self.root, guard=guard).update()
        self.mock.assert_not_called()

    def test_old_manifest_requires_manual_bootstrap(self):
        self.engine.update()
        state = json.loads((self.root / updater.STATE).read_text())
        del state['files']['overlay_windows.py']
        (self.root / updater.STATE).write_bytes(encoded(state))
        with self.assertRaisesRegex(updater.UpdateError, 'baseline'):
            self.engine.update()

    def test_preserve_unmanaged(self):
        names = ['calendar_config.json', 'Nunito.ttf', 'clock_overlay.py',
                 'clock_overlay_v2.py', 'unknown.txt', '.git/index', 'fonts/custom.otf']
        for n in names:
            p = self.root / n; p.parent.mkdir(exist_ok=True); p.write_bytes(b'private')
        self.engine.update()
        for n in names:
            self.assertEqual((self.root / n).read_bytes(), b'private')

    def test_download_failure_no_mutation(self):
        (self.root / 'ip_overlay.py').write_bytes(b'original')
        before = self.installed()
        def fail(url, **kwargs):
            if url.endswith('/ceel_cal_overlay.py'):
                raise updater.UpdateError('offline')
            return self.http(url, **kwargs)
        self.mock.side_effect = fail
        with self.assertRaisesRegex(updater.UpdateError, 'offline'):
            self.engine.update()
        self.assertEqual(self.installed(), before)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['ip_overlay.py'])

    def test_corrupt_hash_no_mutation(self):
        def corrupt(url, **kwargs):
            data = self.http(url, **kwargs)
            return b'corrupt' if url.endswith('/ip_overlay.py') else data
        self.mock.side_effect = corrupt
        with self.assertRaisesRegex(updater.UpdateError, 'blob verification'):
            self.engine.update()
        self.assertFalse(any(self.installed().values()))

    def test_invalid_syntax_and_example(self):
        for name, data in [('ip_overlay.py', b'if :'),
                           ('calendar_config.example.json', b'{}'),
                           ('README.md', b'<html>error</html>')]:
            with self.subTest(name=name):
                original = self.files[name]; self.files[name] = data
                with self.assertRaisesRegex(updater.UpdateError, 'Invalid published content'):
                    self.engine.update()
                self.assertFalse(any(self.installed().values()))
                self.files[name] = original

    def test_missing_file_and_upstream_links(self):
        del self.files['ip_overlay.py']
        with self.assertRaisesRegex(updater.UpdateError, 'missing required'):
            self.engine.update()
        self.files['ip_overlay.py'] = b'x=1'
        def link(url, **kwargs):
            data = self.http(url, **kwargs)
            if '/git/trees/' in url:
                tree = json.loads(data); tree['tree'][0]['mode'] = '120000'; return encoded(tree)
            return data
        self.mock.side_effect = link
        with self.assertRaisesRegex(updater.UpdateError, 'file metadata'):
            self.engine.update()

    def test_local_edits_and_missing_files_block(self):
        self.engine.update()
        path = self.root / 'ip_overlay.py'
        for content in (b'custom', None):
            if content is None: path.unlink()
            else: path.write_bytes(content)
            before = self.installed(); self.mock.reset_mock()
            with self.assertRaisesRegex(updater.UpdateError, 'Local edits'):
                self.engine.update()
            self.assertEqual(self.installed(), before)
            self.mock.assert_not_called()

    def test_invalid_baseline_blocks(self):
        (self.root / updater.STATE).write_bytes(b'{}')
        with self.assertRaisesRegex(updater.UpdateError, 'baseline'):
            self.engine.update()
        self.mock.assert_not_called()

    def test_download_time_edit_blocks(self):
        def edit(url, **kwargs):
            if url.endswith('/README.md'):
                (self.root / 'ip_overlay.py').write_bytes(b'user editing')
            return self.http(url, **kwargs)
        self.mock.side_effect = edit
        with self.assertRaisesRegex(updater.UpdateError, 'changed during download'):
            self.engine.update()
        self.assertEqual((self.root / 'ip_overlay.py').read_bytes(), b'user editing')
        self.assertFalse((self.root / updater.STATE).exists())

    def test_rollback_existing_and_absent(self):
        for existing in (False, True):
            if existing: self.engine.update()
            before = self.installed()
            self.files['overlay_updater.py'] += b'# next\n'
            self.files['clock_overlay_v3.py'] += b'# next\n'
            real = os.replace
            def fail(src, dst):
                if Path(dst).name == 'clock_overlay_v3.py': raise PermissionError('locked')
                real(src, dst)
            with patch.object(updater.os, 'replace', side_effect=fail):
                with self.assertRaisesRegex(updater.UpdateError, 'previous files restored'):
                    self.engine.update()
            self.assertEqual(self.installed(), before)
            self.assertFalse((self.root / updater.LOCK).exists())

    def test_failed_rollback_retains_lock(self):
        (self.root / 'overlay_updater.py').write_bytes(b'original')
        real = os.replace; count = 0
        def fail(src, dst):
            nonlocal count
            count += 1
            if count > 1: raise PermissionError('locked')
            real(src, dst)
        with patch.object(updater.os, 'replace', side_effect=fail):
            with self.assertRaisesRegex(updater.UpdateError, 'Rollback incomplete'):
                self.engine.update()
        self.assertTrue((self.root / updater.LOCK).exists())
        self.assertEqual(next((self.root / updater.BACKUPS).iterdir()).joinpath('overlay_updater.py').read_bytes(), b'original')

    def test_concurrent_instances(self):
        entered, release = threading.Event(), threading.Event()
        def pause(url, **kwargs):
            if url.endswith('/commits/main'):
                entered.set(); self.assertTrue(release.wait(5))
            return self.http(url, **kwargs)
        self.mock.side_effect = pause
        errors = []
        def work():
            try: self.engine.update()
            except Exception as e: errors.append(e)
        thread = threading.Thread(target=work); thread.start()
        self.assertTrue(entered.wait(5))
        try:
            with self.assertRaisesRegex(updater.UpdateError, 'Another overlay'):
                updater.FolderUpdater(self.root).update()
        finally:
            release.set(); thread.join(5)
        self.assertFalse(errors)

    def test_paths_and_symlinks(self):
        with self.assertRaisesRegex(updater.UpdateError, 'Unsafe update path'):
            self.engine.path('../outside')
        (self.root / 'IP_OVERLAY.PY').write_bytes(b'custom')
        with self.assertRaisesRegex(updater.UpdateError, 'Ambiguous'):
            self.engine.update()
        (self.root / 'IP_OVERLAY.PY').unlink()
        if os.name != 'nt':
            (self.root / 'ip_overlay.py').symlink_to(self.root / 'outside')
            with self.assertRaisesRegex(updater.UpdateError, 'Unsafe local path'):
                self.engine.update()


class HTTPTests(unittest.TestCase):
    def response(self, data=b'ok', headers=None):
        response = Mock(); response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.status = 200; response.geturl.return_value = updater.API + '/commits/main'
        response.headers = headers or {}; response.read1.side_effect = io.BytesIO(data).read1
        return response

    def test_bounds_timeouts_and_no_auth(self):
        opener = Mock(); opener.open.return_value = self.response()
        with patch.object(updater, 'build_opener', return_value=opener):
            self.assertEqual(updater.download(updater.API + '/commits/main'), b'ok')
            args, kwargs = opener.open.call_args
            self.assertEqual(kwargs['timeout'], 15)
            self.assertFalse(args[0].has_header('Authorization'))
            opener.open.return_value = self.response(b'long')
            with self.assertRaisesRegex(updater.UpdateError, 'size or time'):
                updater.download(updater.API + '/commits/main', limit=2)
            opener.open.return_value = self.response(headers={'Content-Length': '99999999'})
            with self.assertRaisesRegex(updater.UpdateError, 'size limit'):
                updater.download(updater.API + '/commits/main')
            opener.open.return_value = self.response()
            with patch.object(updater.time, 'monotonic', side_effect=[0, 46]):
                with self.assertRaisesRegex(updater.UpdateError, 'time limit'):
                    updater.download(updater.API + '/commits/main')

    def test_hosts_redirects_and_errors(self):
        for url in ('http://api.github.com/x', 'https://evil.invalid/x',
                    'https://api.github.com@evil.invalid/x', 'https://api.github.com:444/x'):
            with self.assertRaises(updater.UpdateError): updater.valid_url(url)
        with self.assertRaisesRegex(updater.UpdateError, 'redirected'):
            updater.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.invalid/')
        for error, message in [(HTTPError('url', 404, '', {}, None), '404'),
                               (HTTPError('url', 403, '', {}, None), 'rate limit'),
                               (HTTPError('url', 429, '', {}, None), 'rate limit'),
                               (URLError('secret'), 'internet'), (TimeoutError(), 'internet')]:
            with patch.object(updater, 'build_opener') as factory:
                factory.return_value.open.side_effect = error
                with self.assertRaisesRegex(updater.UpdateError, message):
                    updater.download(updater.API + '/commits/main')


class GuiTests(unittest.TestCase):
    def test_platform_guard(self):
        with patch.object(updater.sys, 'platform', 'linux'):
            with self.assertRaisesRegex(updater.UpdateError, 'Windows only'):
                updater.update_checkout('.')

    def test_gui_explicit_worker_and_main_thread_delivery(self):
        root, menu, dialogs = Mock(), Mock(), Mock()
        tk = types.ModuleType("tkinter")
        tk.Menu = Mock(return_value=menu)
        tk.messagebox = dialogs
        with patch.dict(sys.modules, {"tkinter": tk, "tkinter.messagebox": dialogs}), \
             patch.object(updater.threading, "Thread") as thread, \
             patch.object(updater, "update_checkout", return_value="done") as update:
            updater.attach_update_menu(root, __file__)
            update.assert_not_called()
            thread.assert_not_called()
            root.bind.assert_called_once()
            self.assertEqual(root.bind.call_args.args[0], "<Button-3>")
            self.assertEqual(root.bind.call_args.kwargs, {"add": "+"})
            start = menu.add_command.call_args.kwargs["command"]
            dialogs.askyesno.return_value = False
            start()
            thread.assert_not_called()
            dialogs.askyesno.return_value = True
            start()
            thread.return_value.start.assert_called_once()
            update.assert_not_called()
            start()  # busy: no duplicate worker
            thread.assert_called_once()
            worker = thread.call_args.kwargs["target"]
            poll = root.after.call_args.args[1]
            poll()  # queue empty, schedules next poll
            worker()
            dialogs.showinfo.assert_not_called()
            poll()
            dialogs.showinfo.assert_called_once()
