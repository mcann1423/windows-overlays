"""Load only definitions: no Tk startup, private configuration or real feeds."""
import ast
import datetime as dt
from pathlib import Path
import re
import unittest
import urllib.request
from unittest.mock import Mock, patch


class CalendarExpiryTests(unittest.TestCase):
    def environments(self):
        for name in ('cchl_cal_overlay.py', 'ceel_cal_overlay.py'):
            tree = ast.parse((Path(__file__).resolve().parents[1] / name).read_text())
            names = {'parse_ics_date', 'format_cached_schedule', 'fetch_two_day_schedule', 'expire_calendar'}
            functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
            env = dict(datetime=dt, re=re, urllib=urllib, HEADER_TITLE=name, CONFIG_ERROR=None,
                       cached_ics_data=None, calendar_error=None, root=Mock(),
                       EXPIRY_INTERVAL_MS=15000, apply_appearance=Mock(),
                       appearance=Mock(settings={'font_size':20}), current_schedule_text='')
            exec(compile(ast.Module(body=functions, type_ignores=[]), name, 'exec'), env)
            yield env

    def feed(self, start, title='Appointment'):
        return f'BEGIN:VEVENT\nDTSTART:{start}\nSUMMARY:{title}\nEND:VEVENT\n'

    def test_cutoff_offsets_seconds_and_all_day(self):
        start = dt.datetime(2026, 10, 8, 12, 0, 15, tzinfo=dt.timezone.utc)
        for env in self.environments():
            for value in ('20261008T120015Z', '20261008T080015-0400',
                          '20261008T140015+0200', '20261008T14' + '0015+02:00',
                          'TZID=UTC:20261008T120015'):
                env['cached_ics_data'] = self.feed(value)
                for delta, visible in ((dt.timedelta(microseconds=-1), True),
                                       (dt.timedelta(0), False), (dt.timedelta(seconds=1), False)):
                    now = start + dt.timedelta(minutes=30) + delta
                    self.assertEqual('Appointment' in env['format_cached_schedule'](now), visible, value)
            local_start = start.astimezone()
            date = local_start.strftime('%Y%m%d')
            tomorrow = (local_start + dt.timedelta(days=1)).strftime('%Y%m%dT%H%M%S')
            env['cached_ics_data'] = (self.feed(date, 'All day fixture') +
                                      self.feed(tomorrow, 'Tomorrow fixture') +
                                      self.feed(local_start.strftime('%Y%m%dT%H%M%S'), 'Floating fixture'))
            text = env['format_cached_schedule'](start + dt.timedelta(minutes=30))
            self.assertIn('All day fixture', text)
            self.assertIn('Tomorrow fixture', text)
            self.assertNotIn('Floating fixture', text)
            self.assertNotIn('All day fixture', env['format_cached_schedule'](start + dt.timedelta(days=1)))

    def test_timer_expires_cached_events_even_after_failed_fetch(self):
        for env in self.environments():
            now = dt.datetime.now().astimezone()
            old = (now - dt.timedelta(minutes=31)).astimezone(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
            env['cached_ics_data'] = self.feed(old, 'Expired fixture')
            env['current_schedule_text'] = 'Expired fixture'
            with patch.object(urllib.request, 'urlopen', side_effect=OSError) as network:
                env['expire_calendar']()
                network.assert_not_called()
                self.assertNotIn('Expired fixture', env['current_schedule_text'])
                env['apply_appearance'].assert_called_once_with(env['appearance'].settings, refresh=True)
                env['root'].after.assert_called_once_with(15000, env['expire_calendar'])
                text = env['fetch_two_day_schedule']('https://example.invalid/calendar')
                self.assertIn('CALENDAR UNAVAILABLE', text)
                self.assertNotIn('Expired fixture', text)
                network.assert_called_once()
                env['apply_appearance'].reset_mock()
                env['current_schedule_text'] = text
                env['expire_calendar']()
                env['apply_appearance'].assert_not_called()
                network.assert_called_once()

    def test_timer_is_registered_independently(self):
        for name in ('cchl_cal_overlay.py', 'ceel_cal_overlay.py'):
            source = (Path(__file__).resolve().parents[1] / name).read_text()
            self.assertIn('root.after(EXPIRY_INTERVAL_MS, expire_calendar)', source)
            self.assertIn('root.after(REFRESH_INTERVAL_MS, update_calendar)', source)


if __name__ == '__main__':
    unittest.main()
