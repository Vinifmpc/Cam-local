"""Bounded GRBL profile transfer. No motion, reset, unlock or program streaming.

The serial port is owned exclusively for the duration of one explicit operation.
Opening a port can reset some USB boards despite disabling DTR/RTS beforehand.
The only transmitted strings are ?, $$ and the six profile setting assignments.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import threading
import time
import uuid


PROFILE_KEYS = {
    'machine_max_rate_mm_min': (110, 111, 112),
    'machine_acceleration_mm_s2': (120, 121, 122),
}
SETTING_IDS = tuple(i for values in PROFILE_KEYS.values() for i in values)
_SETTING = re.compile(r'^\$(\d+)\s*=\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*(?:\(.*\))?$')
_STATUS = re.compile(r'^<([A-Za-z]+)(?::\d+)?(?:[|,].*)?>$')


def _connection(record):
    if not isinstance(record, dict) or set(record)-{'port', 'baudrate'}:
        raise ValueError('Conexão GRBL inválida')
    port = record.get('port', '')
    if not isinstance(port, str) or not re.fullmatch(r'(?:COM[1-9]\d{0,3}|/dev/(?:tty|cu\.)[A-Za-z0-9_.-]+)', port, re.I):
        raise ValueError('Selecione uma porta serial válida, como COM3')
    baudrate = record.get('baudrate', 115200)
    if isinstance(baudrate, bool) or not isinstance(baudrate, int) or not 9600 <= baudrate <= 2_000_000:
        raise ValueError('Baud rate GRBL inválido')
    return {'port': port.upper() if port.upper().startswith('COM') else port, 'baudrate': baudrate}


def _profile(record):
    if not isinstance(record, dict) or set(record) != set(PROFILE_KEYS):
        raise ValueError('Informe apenas os máximos e as acelerações dos três eixos')
    settings = {}
    for key, identifiers in PROFILE_KEYS.items():
        values = record[key]
        if not isinstance(values, (list, tuple)) or len(values) != 3:
            raise ValueError('O perfil GRBL precisa de três valores por campo')
        for identifier, value in zip(identifiers, values):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= 1_000_000:
                raise ValueError('Máximos e acelerações devem ser positivos e finitos')
            # GRBL stores floats and normally reports three decimal places.
            # Reject positive values that would become zero in its report.
            rounded = round(float(value), 3)
            if rounded <= 0:
                raise ValueError('O menor valor aceito é 0,001')
            settings[f'${identifier}'] = rounded
    return settings


def _values(settings):
    return {key: [settings[f'${identifier}'] for identifier in identifiers]
            for key, identifiers in PROFILE_KEYS.items()}


def _same(a, b):
    return all(key in a and key in b and abs(a[key]-b[key]) <= .00051 for key in (f'${i}' for i in SETTING_IDS))


class _SerialSession:
    def __init__(self, connection, factory, timeout_s):
        self.connection = connection
        self.factory = factory
        self.timeout_s = timeout_s
        self.serial = None
        self.startup_seen = False
        self.disallow_startup = False
        self.rx_buffer = bytearray()

    def __enter__(self):
        try:
            # Use an unopened instance so handshake outputs are disabled before
            # the OS opens the handle. No reset/flush command is sent.
            self.serial = self.factory(port=None, baudrate=self.connection['baudrate'], timeout=.1, write_timeout=2, exclusive=True)
            self.serial.dtr = False
            self.serial.rts = False
            self.serial.port = self.connection['port']
            self.serial.open()
            return self
        except Exception as error:
            self.close()
            raise RuntimeError('Não foi possível abrir a porta GRBL. Desconecte essa porta no CNCjs durante a transferência e confira a porta/baud rate.') from error

    def close(self):
        if self.serial is not None:
            try:
                self.serial.close()
            except Exception:
                pass

    def __exit__(self, *_):
        self.close()

    def _line(self):
        # pySerial readline may return a fragment when its timeout expires.
        # Preserve it until LF rather than parsing a truncated status/setting.
        if b'\n' not in self.rx_buffer:
            raw = self.serial.readline(8193)
            if not raw:
                return ''
            self.rx_buffer.extend(raw)
        if len(self.rx_buffer) > 8192:
            raise RuntimeError('Resposta serial maior que o permitido')
        if b'\n' not in self.rx_buffer:
            return ''
        raw, _, remaining = self.rx_buffer.partition(b'\n')
        self.rx_buffer = bytearray(remaining)
        try:
            line = raw.decode('ascii').strip()
        except (UnicodeDecodeError, AttributeError) as error:
            raise RuntimeError('Resposta GRBL inválida; confira o baud rate') from error
        if line.lower().startswith('grbl '):
            self.startup_seen = True
            if self.disallow_startup:
                raise RuntimeError('A controladora reiniciou durante a transferência. Leia os valores novamente.')
        return line

    def _drain(self):
        # Discard already received bytes without toggling RTS/DTR or resetting
        # the firmware. A response to our subsequent query must arrive afresh.
        deadline = time.monotonic()+self.timeout_s
        count = 0
        while getattr(self.serial, 'in_waiting', 0):
            self._line()
            count += 1
            if count > 1024 or time.monotonic() >= deadline:
                raise RuntimeError('A porta GRBL está ocupada recebendo dados')
        self.rx_buffer.clear()

    def status(self):
        self._drain()
        self.serial.write(b'?')
        deadline = time.monotonic()+self.timeout_s
        while time.monotonic() < deadline:
            line = self._line()
            match = _STATUS.fullmatch(line)
            if match:
                return match.group(1)
            if line.startswith(('error:', 'ALARM:')):
                raise RuntimeError('GRBL: '+line)
        raise TimeoutError('GRBL não respondeu à consulta de estado; confira porta e baud rate')

    def require_idle(self):
        state = self.status()
        if state != 'Idle':
            raise RuntimeError(f'GRBL está em {state}. A transferência exige Idle, sem trabalho em execução.')
        return state

    def command(self, command):
        if command != '$$' and not re.fullmatch(r'\$(?:110|111|112|120|121|122)=[0-9]+(?:\.[0-9]+)?', command):
            raise ValueError('Comando fora do perfil GRBL permitido')
        self._drain()
        self.serial.write((command+'\n').encode('ascii'))
        lines = []
        deadline = time.monotonic()+self.timeout_s
        while time.monotonic() < deadline:
            line = self._line()
            if not line:
                continue
            if line == 'ok':
                return lines
            if line.startswith(('error:', 'ALARM:')):
                raise RuntimeError('GRBL: '+line)
            if line.lower().startswith('grbl '):
                raise RuntimeError('A controladora reiniciou durante a transferência. Leia os valores novamente.')
            if not _STATUS.fullmatch(line):
                lines.append(line)
            if len(lines) > 1024:
                raise RuntimeError('Resposta GRBL maior que o permitido')
        raise TimeoutError('Sem confirmação do GRBL. O último comando pode ter sido aplicado; leia os valores novamente, sem repetir a gravação.')

    def settings(self):
        settings = {}
        for line in self.command('$$'):
            match = _SETTING.fullmatch(line)
            if match:
                value = float(match.group(2))
                if not math.isfinite(value):
                    raise RuntimeError('Configuração GRBL não finita')
                settings['$'+match.group(1)] = value
        if any(f'${identifier}' not in settings for identifier in SETTING_IDS):
            raise RuntimeError('A resposta $$ não contém o perfil XYZ completo do GRBL')
        return settings


class GrblController:
    """Stateful read tokens, exclusive transactions and on-disk prewrite backups."""
    def __init__(self, backup_dir, *, serial_factory=None, ports_provider=None, timeout_s=4, token_ttl_s=300):
        self.backup_dir = Path(backup_dir)
        self.serial_factory = serial_factory
        self.ports_provider = ports_provider
        self.timeout_s = timeout_s
        self.token_ttl_s = token_ttl_s
        self.lock = threading.Lock()
        self.reads = {}

    @contextmanager
    def _operation(self):
        if not self.lock.acquire(blocking=False):
            raise RuntimeError('Já existe uma transferência GRBL em andamento')
        try:
            yield
        finally:
            self.lock.release()

    def _factory(self):
        if self.serial_factory is not None:
            return self.serial_factory
        try:
            from serial import Serial
            return Serial
        except ImportError as error:
            raise RuntimeError('O suporte serial não está instalado nesta versão do aplicativo') from error

    def ports(self):
        provider = self.ports_provider
        if provider is None:
            try:
                from serial.tools.list_ports import comports
                provider = comports
            except ImportError as error:
                raise RuntimeError('O suporte serial não está instalado nesta versão do aplicativo') from error
        return {'ports': [{'port': p.device, 'description': p.description, 'hwid': p.hwid}
                          for p in provider()]}

    def read(self, connection):
        connection = _connection(connection)
        with self._operation():
            with _SerialSession(connection, self._factory(), self.timeout_s) as port:
                state = port.require_idle()
                settings = port.settings()
                port.require_idle()
            now = time.monotonic()
            self.reads = {key: value for key, value in self.reads.items() if value['expires'] > now}
            # One current snapshot per controller; old tokens cannot be reused
            # to approve a later connection or a changed controller profile.
            self.reads = {key: value for key, value in self.reads.items() if value['connection'] != connection}
            if len(self.reads) >= 32:
                del self.reads[next(iter(self.reads))]
            identifier = uuid.uuid4().hex
            self.reads[identifier] = {'connection': connection, 'settings': settings, 'expires': now+self.token_ttl_s}
            return {'status': 'read', 'read_id': identifier, **connection, 'connection': connection,
                    'machine_state': state, 'settings': dict(settings), 'values': _values(settings),
                    'expires_in_s': self.token_ttl_s, 'startup_seen': port.startup_seen}

    def _backup(self, connection, before, requested):
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        path = self.backup_dir/('grbl-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8]+'.json')
        # Exclusive creation prevents overwrites. Backup failure forbids writes.
        with path.open('x', encoding='utf-8') as output:
            json.dump({'created_utc': datetime.now(timezone.utc).isoformat(), 'connection': connection,
                       'before': before, 'requested': requested}, output, ensure_ascii=False, indent=2, allow_nan=False)
            output.flush()
            import os
            os.fsync(output.fileno())
        return str(path.resolve())

    def apply(self, connection, profile, read_id):
        connection = _connection(connection)
        requested = _profile(profile)
        with self._operation():
            snapshot = self.reads.pop(read_id, None) if isinstance(read_id, str) else None
            if snapshot is None or snapshot['expires'] < time.monotonic() or snapshot['connection'] != connection:
                raise ValueError('Leia o GRBL novamente nesta porta antes de gravar o perfil')
            report = {'status': 'failed', 'verified': False, 'values': None, 'before': None,
                      'after': None, 'requested': requested, 'written_settings': [], 'backup_path': None}
            attempted = False
            try:
                with _SerialSession(connection, self._factory(), self.timeout_s) as port:
                    port.require_idle()
                    before = port.settings()
                    report['before'] = before
                    previous = snapshot['settings']
                    if set(before) != set(previous) or any(abs(before[key]-previous[key]) > .00051 for key in previous):
                        raise RuntimeError('O perfil da controladora mudou desde a leitura. Leia novamente antes de gravar.')
                    port.disallow_startup = True
                    changed = [(key, value) for key, value in requested.items() if abs(value-before[key]) > .00051]
                    if changed:
                        report['backup_path'] = self._backup(connection, before, requested)
                    for key, value in changed:
                        port.require_idle()
                        attempted = True
                        port.command(key+'='+format(value, '.3f').rstrip('0').rstrip('.'))
                        report['written_settings'].append(key)
                    port.require_idle()
                    after = port.settings()
                    report['after'] = after
                    report['values'] = _values(after)
                    if not _same(after, requested):
                        raise RuntimeError('A leitura final não corresponde ao perfil solicitado. Confira os valores lidos.')
                    report.update(status='verified', verified=True, message='Perfil gravado e confirmado no GRBL.' if changed else 'O GRBL já usa esses valores; leitura confirmada.')
                    return report
            except Exception as error:
                # A missing acknowledgement can mean the last write succeeded.
                # Never retry or automatically roll back a partial transaction.
                report['status'] = 'partial' if attempted else 'failed'
                report['error'] = str(error)
                report['message'] = ('Gravação não confirmada por completo. Leia o GRBL novamente antes de qualquer nova gravação. ' if attempted else '')+str(error)
                return report
