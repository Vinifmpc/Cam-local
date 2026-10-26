"""Bounded, authenticated command mailbox for the application's own UI.

Commands are acknowledged once. Pending commands expire before execution; a
running command is never retried automatically after a client timeout.
"""
import copy
import math
import threading
import time
import uuid

UI_ACTIONS = {
    'state', 'demo.open', 'stl.open', 'project.adopt', 'project.save',
    'config.patch', 'placement.set', 'tools.list', 'tool.set', 'tool.save',
    'regions.add', 'regions.remove', 'regions.clear', 'regions.picker', 'regions.draw', 'regions.cancel',
    'operation.tab', 'operations.set', 'drill.inspect', 'cutout.recovery.apply', 'machining.plan',
    'calculate.start', 'calculate.cancel', 'nc.export', 'view.set',
    'view.capture', 'simulation.set', 'simulation.play', 'simulation.pause',
    'simulation.seek', 'simulation.reset', 'simulation.sample',
}


class CommandMailbox:
    def __init__(self):
        self.condition = threading.Condition()
        self.records = {}
        self.client = None
        self.last_poll = 0.
        self.closed = False

    def submit(self, command, timeout_s=30):
        if not isinstance(command, dict) or command.get('action') not in UI_ACTIONS:
            raise ValueError('Comando desconhecido; consulte a ação schema')
        if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)) or not math.isfinite(timeout_s) or not 1 <= timeout_s <= 300:
            raise ValueError('timeout_s deve ficar entre 1 e 300 segundos')
        with self.condition:
            if self.closed:raise RuntimeError('Aplicativo encerrando')
            self._expire()
            while len(self.records) >= 128:
                old = next((key for key, record in self.records.items() if record['status'] in ('complete', 'failed', 'expired')), None)
                if old is None:raise RuntimeError('Fila de comandos cheia')
                del self.records[old]
            identifier = uuid.uuid4().hex
            self.records[identifier] = {'status': 'pending', 'command': copy.deepcopy(command),
                                        'deadline': time.monotonic() + timeout_s}
            self.condition.notify_all()
            return {'command_id': identifier, 'status': 'pending'}

    def _expire(self):
        now = time.monotonic()
        for record in self.records.values():
            if record['status'] == 'pending' and record['deadline'] < now:
                record.update(status='expired', error='A interface não recebeu o comando dentro do prazo; ele não foi executado')
                record.pop('command', None)

    def next(self, client, wait_s=20):
        if not isinstance(client, str) or not 1 <= len(client) <= 80:raise ValueError('Cliente inválido')
        if not isinstance(wait_s, (float, int)) or not 0 <= wait_s <= 20:raise ValueError('Espera inválida')
        with self.condition:
            now = time.monotonic()
            if self.client not in (None, client) and now-self.last_poll < 45:
                raise RuntimeError('Outra interface já controla esta sessão')
            self.client = client
            self.last_poll = now
            deadline = now + wait_s
            while not self.closed:
                self._expire()
                for identifier, record in self.records.items():
                    if record['status'] == 'pending':
                        record['status'] = 'running'
                        record['client'] = client
                        return {'command_id': identifier, 'command': record.pop('command')}
                remaining = deadline-time.monotonic()
                if remaining <= 0:break
                self.condition.wait(min(remaining, 1))
            return {'command_id': None}

    def complete(self, identifier, client, result=None, error=None):
        with self.condition:
            record = self.records.get(identifier)
            if record is None:raise ValueError('Comando não encontrado')
            if record.get('client') != client:raise ValueError('Comando pertence a outra interface')
            # Retried acknowledgement must not execute or replace a result twice.
            if record['status'] == 'running':
                record.update(status='failed' if error is not None else 'complete')
                if error is not None:record['error'] = str(error)[:4000]
                else:record['result'] = result
                self.condition.notify_all()
            return {'status': record['status']}

    def result(self, identifier):
        with self.condition:
            self._expire()
            if identifier not in self.records:raise ValueError('Comando não encontrado')
            return {key: value for key, value in self.records[identifier].items()
                    if key in ('status', 'result', 'error')}

    def close(self):
        with self.condition:
            self.closed = True
            for record in self.records.values():
                if record['status'] in ('pending', 'running'):
                    record.update(status='failed', error='Aplicativo encerrado durante o comando')
                    record.pop('command', None)
            self.condition.notify_all()
