import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest

from grbl_controller import GrblController, _SerialSession


CONNECTION = {'port': 'COM3', 'baudrate': 115200}
PROFILE = {'machine_max_rate_mm_min': [1500, 1500, 1500], 'machine_acceleration_mm_s2': [80, 80, 100]}


class FakeBoard:
    def __init__(self):
        self.settings = {'$3': 6., '$11': .01, '$100': 400., '$101': 400., '$102': 400.,
                         '$110': 1500., '$111': 1500., '$112': 1500., '$120': 10., '$121': 10., '$122': 10.}
        self.state = 'Idle'
        self.commands = []
        self.opened = []
        self.fail_key = None
        self.timeout_key = None
        self.ignore_key = None
        self.fail_open = False
        self.busy_after_key = None
        self.startup_after_key = None
        self.stale = []

    def factory(self, **kwargs):
        board = self

        class Port:
            def __init__(self):
                self.port = kwargs['port']
                self.queue = list(board.stale)
                self.closed = False
                self.dtr = True
                self.rts = True

            def open(self):
                board.opened.append((self.port, self.dtr, self.rts, kwargs))
                if board.fail_open:
                    raise OSError('Access denied')

            @property
            def in_waiting(self):
                return len(self.queue)

            def write(self, data):
                command = data.decode('ascii').strip()
                board.commands.append(command)
                if command == '?':
                    self.queue.append(f'<{board.state}|MPos:0,0,0|FS:0,0>')
                elif command == '$$':
                    self.queue.extend(f'{key}={value:.3f} (setting)' for key, value in board.settings.items())
                    self.queue.append('ok')
                else:
                    key, value = command.split('=')
                    if key == board.fail_key:
                        self.queue.append('error:3')
                        return
                    if key != board.ignore_key:
                        board.settings[key] = float(value)
                    if key == board.busy_after_key:
                        board.state = 'Run'
                    if key != board.timeout_key:
                        self.queue.append('ok')
                    if key == board.startup_after_key:
                        self.queue.append('Grbl 1.1h [\'$\' for help]')

            def readline(self, size=8193):
                if self.queue:
                    return (self.queue.pop(0)+'\r\n').encode('ascii')
                time.sleep(.0001)
                return b''

            def close(self):
                self.closed = True

        port = Port()
        board.last_port = port
        return port


class GrblControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.board = FakeBoard()
        # Leave room for a Windows scheduling slice while other geometry tests
        # run. This is the fake transport's deadline, not the device default.
        self.controller = GrblController(self.folder, serial_factory=self.board.factory, timeout_s=.1,
                                         ports_provider=lambda: [SimpleNamespace(device='COM3', description='USB serial', hwid='USB PID')])

    def tearDown(self):
        self.temp.cleanup()

    def read(self):
        return self.controller.read(CONNECTION)

    def apply(self, read=None, profile=None):
        return self.controller.apply(CONNECTION, profile or PROFILE, (read or self.read())['read_id'])

    def test_ports_enumeration_never_opens_a_controller(self):
        self.assertEqual(self.controller.ports()['ports'][0]['port'], 'COM3')
        self.assertFalse(self.board.opened)

    def test_read_queries_fresh_idle_and_settings_then_closes(self):
        self.board.stale = ['ok', '<Run|MPos:0,0,0>', '$120=999']
        report = self.read()
        self.assertEqual(report['status'], 'read')
        self.assertEqual(report['values']['machine_acceleration_mm_s2'], [10]*3)
        self.assertEqual(report['settings']['$3'], 6)
        self.assertEqual(self.board.commands, ['?', '$$', '?'])
        self.assertTrue(self.board.last_port.closed)
        self.assertEqual(self.board.opened[0][:3], ('COM3', False, False))
        self.assertTrue(self.board.opened[0][3]['exclusive'])

    def test_apply_writes_only_changed_whitelist_and_verifies(self):
        before = dict(self.board.settings)
        read = self.read()
        report = self.apply(read)
        self.assertEqual(report['status'], 'verified')
        self.assertTrue(report['verified'])
        self.assertEqual(report['values'], PROFILE)
        self.assertEqual(report['written_settings'], ['$120', '$121', '$122'])
        self.assertEqual([c for c in self.board.commands if '=' in c], ['$120=80', '$121=80', '$122=100'])
        backup = json.loads(Path(report['backup_path']).read_text(encoding='utf-8'))
        self.assertEqual(backup['before'], before)
        self.assertEqual(self.board.settings['$3'], 6)
        self.assertTrue(self.board.last_port.closed)

    def test_applies_rates_and_accelerations_and_never_other_settings(self):
        profile = {**PROFILE, 'machine_max_rate_mm_min': [1200, 1000, 900]}
        report = self.apply(profile=profile)
        self.assertEqual(report['status'], 'verified')
        self.assertEqual(report['written_settings'], ['$110', '$111', '$112', '$120', '$121', '$122'])
        self.assertEqual(set(self.board.settings)-set(report['written_settings']), {'$3', '$11', '$100', '$101', '$102'})

    def test_read_refuses_running_or_paused_controllers(self):
        for state in ('Run', 'Hold:0', 'Alarm', 'Jog'):
            self.board.state = state
            with self.assertRaisesRegex(RuntimeError, 'exige Idle'):
                self.read()
        self.assertFalse(any('=' in c for c in self.board.commands))

    def test_apply_refuses_a_controller_that_started_after_read(self):
        read = self.read()
        self.board.state = 'Run'
        report = self.apply(read)
        self.assertEqual(report['status'], 'failed')
        self.assertFalse(any('=' in c for c in self.board.commands))
        self.assertIsNone(report['backup_path'])

    def test_apply_refuses_profile_changed_since_read(self):
        read = self.read()
        self.board.settings['$120'] = 20
        report = self.apply(read)
        self.assertEqual(report['status'], 'failed')
        self.assertIn('mudou', report['error'])
        self.assertFalse(any('=' in c for c in self.board.commands))

    def test_unrelated_configuration_changes_also_require_a_fresh_read(self):
        read = self.read()
        self.board.settings['$101'] = 800
        report = self.apply(read)
        self.assertEqual(report['status'], 'failed')
        self.assertFalse(any('=' in c for c in self.board.commands))

    def test_token_is_bound_to_connection_and_one_use(self):
        read = self.read()
        with self.assertRaises(ValueError):
            self.controller.apply({**CONNECTION, 'port': 'COM4'}, PROFILE, read['read_id'])
        with self.assertRaises(ValueError):
            self.apply(read)
        read = self.read()
        self.apply(read)
        with self.assertRaises(ValueError):
            self.apply(read)

    def test_new_read_replaces_previous_snapshot_and_expiry_is_enforced(self):
        old = self.read()
        new = self.read()
        with self.assertRaises(ValueError):
            self.apply(old)
        self.controller.reads[new['read_id']]['expires'] = 0
        with self.assertRaises(ValueError):
            self.apply(new)

    def test_invalid_profile_or_connection_never_opens_port(self):
        for value in (0, -1, float('nan'), float('inf'), True, .00001):
            bad = {**PROFILE, 'machine_acceleration_mm_s2': [value, 10, 10]}
            with self.assertRaises(ValueError):
                self.controller.apply(CONNECTION, bad, 'missing')
        for port in ('COM3\n$3=0', 'socket://localhost:1234', '../../thing', ''):
            with self.assertRaises(ValueError):
                self.controller.read({'port': port})
        with self.assertRaises(ValueError):
            self.controller.apply(CONNECTION, {**PROFILE, 'machine_steps_per_mm': [1, 1, 1]}, 'missing')
        self.assertFalse(self.board.opened)

    def test_port_conflict_reports_cncjs_instructions(self):
        self.board.fail_open = True
        with self.assertRaisesRegex(RuntimeError, 'CNCjs'):
            self.read()
        self.assertTrue(self.board.last_port.closed)

    def test_backup_failure_prevents_all_writes(self):
        read = self.read()
        self.controller.backup_dir = self.folder/'file'
        self.controller.backup_dir.write_text('occupied')
        report = self.apply(read)
        self.assertEqual(report['status'], 'failed')
        self.assertFalse(any('=' in c for c in self.board.commands))

    def test_acknowledged_partial_write_stops_and_does_not_roll_back(self):
        read = self.read()
        self.board.fail_key = '$121'
        report = self.apply(read)
        self.assertEqual(report['status'], 'partial')
        self.assertEqual(report['written_settings'], ['$120'])
        self.assertEqual(self.board.settings['$120'], 80)
        self.assertEqual(self.board.settings['$121'], 10)
        self.assertFalse(any(c.startswith('$122=') for c in self.board.commands))
        self.assertTrue(Path(report['backup_path']).exists())

    def test_uncertain_ack_timeout_is_partial_and_never_retried(self):
        read = self.read()
        self.board.timeout_key = '$120'
        report = self.apply(read)
        self.assertEqual(report['status'], 'partial')
        self.assertEqual(report['written_settings'], [])
        self.assertEqual(self.board.settings['$120'], 80)
        self.assertEqual(self.board.commands.count('$120=80'), 1)
        self.assertIn('pode ter sido aplicado', report['error'])

    def test_idle_is_rechecked_between_writes(self):
        read = self.read()
        self.board.busy_after_key = '$120'
        report = self.apply(read)
        self.assertEqual(report['status'], 'partial')
        self.assertEqual(report['written_settings'], ['$120'])
        self.assertFalse(any(c.startswith('$121=') for c in self.board.commands))

    def test_startup_between_writes_aborts_even_if_next_status_is_idle(self):
        read = self.read()
        self.board.startup_after_key = '$120'
        report = self.apply(read)
        self.assertEqual(report['status'], 'partial')
        self.assertEqual(report['written_settings'], ['$120'])
        self.assertIn('reiniciou', report['error'])
        self.assertFalse(any(c.startswith('$121=') for c in self.board.commands))

    def test_final_readback_mismatch_is_never_reported_as_success(self):
        read = self.read()
        self.board.ignore_key = '$121'
        report = self.apply(read)
        self.assertEqual(report['status'], 'partial')
        self.assertFalse(report['verified'])
        self.assertEqual(report['values']['machine_acceleration_mm_s2'], [80, 10, 100])

    def test_unchanged_profile_performs_no_eeprom_writes(self):
        read = self.read()
        report = self.apply(read, read['values'])
        self.assertEqual(report['status'], 'verified')
        self.assertEqual(report['written_settings'], [])
        self.assertIsNone(report['backup_path'])
        self.assertFalse(any('=' in c for c in self.board.commands))

    def test_simultaneous_operation_is_rejected(self):
        self.controller.lock.acquire()
        try:
            with self.assertRaisesRegex(RuntimeError, 'andamento'):
                self.read()
        finally:
            self.controller.lock.release()

    def test_timeout_fragments_are_buffered_until_a_complete_line(self):
        chunks = iter([b'<Id', b'', b'le|MPos:0,0,0>\r', b'\n', b'$120=8', b'0.000\r\n'])
        session = _SerialSession(CONNECTION, self.board.factory, .01)
        session.serial = SimpleNamespace(readline=lambda size: next(chunks))
        self.assertEqual(session._line(), '')
        self.assertEqual(session._line(), '')
        self.assertEqual(session._line(), '')
        self.assertEqual(session._line(), '<Idle|MPos:0,0,0>')
        self.assertEqual(session._line(), '')
        self.assertEqual(session._line(), '$120=80.000')


if __name__ == '__main__':
    unittest.main()
