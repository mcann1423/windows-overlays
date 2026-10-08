"""Static batch validation and mocked selection; native Windows remains untested."""
from pathlib import Path
import re
import unittest
from unittest.mock import Mock

BATCH = Path(__file__).resolve().parents[1] / 'overlay.bat'
BS = chr(92)

class LauncherTests(unittest.TestCase):
    def test_envelope_and_order(self):
        raw = BATCH.read_bytes()
        self.assertTrue(raw.startswith(b'@echo off'+bytes([13,10])))
        self.assertNotIn(bytes([10]), raw.replace(bytes([13,10]), b''))
        text = raw.decode()
        self.assertIn('setlocal DisableDelayedExpansion', text)
        self.assertIn('set "OVERLAY_APP=%~dp0"', text)
        self.assertIn(BS.join(['C:', 'Program Files', 'Python314', 'pythonw.exe']), text)
        self.assertEqual(text.count('# POWERSHELL PAYLOAD'), 1)
        payload = text.split('# POWERSHELL PAYLOAD')[1]
        self.assertLess(text.index('exit /b 0'), text.index('# POWERSHELL PAYLOAD'))
        for prerequisite in ('WindowsBuiltInRole]::Administrator', 'Required file missing', 'Get-CimInstance', '$process.Handle'):
            self.assertLess(payload.index(prerequisite), payload.index('$process.Kill()'))
        self.assertLess(payload.index('WaitForExit(10000)'), payload.index('Start-Process'))
        self.assertIn('-WorkingDirectory $app -PassThru -ErrorAction Stop', payload)
        self.assertIn('$process.ExecutablePath -ieq $python', payload)
        self.assertIn('$mutex.WaitOne(0)', payload)
        self.assertNotIn('taskkill /', payload.lower())

    def test_actual_regex_fragments_mocked_selection(self):
        text = BATCH.read_text()
        line = next(line for line in text.splitlines() if "'(?i)^" in line)
        fragments = re.findall("'([^']*)'", line)
        self.assertEqual(len(fragments), 3)
        python = BS.join(['C:', 'Program Files', 'Python314', 'pythonw.exe'])
        app = BS.join(['C:', 'Program Files', "Clock Overlay & Joe's"])
        scripts = re.findall("'([^']+[.]py)'", next(l for l in text.splitlines() if l.startswith('$scripts =')))
        self.assertEqual(set(scripts), {'clock_overlay_v3.py','ip_overlay.py','cchl_cal_overlay.py','ceel_cal_overlay.py'})
        patterns = [re.compile(fragments[0]+re.escape(python)+fragments[1]+re.escape(app+BS+s)+fragments[2]) for s in scripts]
        def matches(executable, command):
            return executable.lower() == python.lower() and any(p.fullmatch(command) for p in patterns)
        stop = Mock()
        wanted = ['"'+python+'" "'+app+BS+s+'"' for s in scripts]
        ignored = ['"'+python+'" "'+app+BS+s+'"' for s in ('overlay_updater.py', 'clock_overlay_v2.py', 'ip_overlay.py.bak')]
        ignored += [wanted[0]+' --extra', '"'+python+'" ip_overlay.py', wanted[0].replace(app, app+' other')]
        for command in wanted + ignored:
            if matches(python, command): stop(command)
        self.assertEqual(stop.call_count, 4)
        self.assertFalse(matches('C:'+BS+'Other'+BS+'pythonw.exe', wanted[0]))
