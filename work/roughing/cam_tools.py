"""Versioned local tool catalogue. Lengths and feeds are stored in mm/mm-min.

Only flat end mills are executable by the current roughing/motion engine.
No cutting data are inferred from diameter, flute count, or material.
"""
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import re
import os
import tempfile


def positive(value, name, *, zero=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{name}: informe um número finito')
    if value < 0 or (value == 0 and not zero):
        raise ValueError(f'{name}: valor fora do intervalo')
    return float(value)


def unit_scale(units):
    if units not in ('mm', 'inch'):
        raise ValueError('Unidade deve ser mm ou inch; STL não informa unidade')
    return 1.0 if units == 'mm' else 25.4


def write_json(path, value):
    """Atomic replacement, preserving the prior catalogue/project on failure."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf8') as stream:
            stream.write(payload)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@dataclass(frozen=True)
class Tool:
    id: str
    name: str
    diameter_mm: float
    cutting_length_mm: float
    kind: str = 'flat_end_mill'
    shank_diameter_mm: float | None = None
    overall_length_mm: float | None = None
    flutes: int | None = None
    feed_mm_min: float | None = None
    plunge_mm_min: float | None = None
    spindle_rpm: float | None = None
    notes: str = ''

    def __post_init__(self):
        if not isinstance(self.id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', self.id):
            raise ValueError('ID da ferramenta inválido')
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError('Informe o nome da ferramenta')
        if self.kind != 'flat_end_mill':
            raise ValueError('Motor atual aceita somente fresa de topo reto (flat_end_mill)')
        if not isinstance(self.notes, str):
            raise ValueError('Notas devem ser texto')
        for key in ('diameter_mm', 'cutting_length_mm'):
            positive(getattr(self, key), key)
        for key in ('shank_diameter_mm', 'overall_length_mm', 'feed_mm_min', 'plunge_mm_min', 'spindle_rpm'):
            if getattr(self, key) is not None:
                positive(getattr(self, key), key)
        if self.overall_length_mm is not None and self.overall_length_mm < self.cutting_length_mm:
            raise ValueError('Comprimento total menor que o comprimento de corte')
        if self.flutes is not None and (type(self.flutes) is not int or not 1 <= self.flutes <= 100):
            raise ValueError('Número de cortes deve ser inteiro entre 1 e 100')

    @classmethod
    def from_dict(cls, record):
        if not isinstance(record, dict):
            raise ValueError('Registro de ferramenta inválido')
        try:
            return cls(**record)
        except TypeError as error:
            raise ValueError('Campos de ferramenta ausentes ou desconhecidos') from error

    @classmethod
    def from_units(cls, *, units, diameter, cutting_length, shank_diameter=None,
                   overall_length=None, feed=None, plunge=None, **metadata):
        scale = unit_scale(units)
        def convert(value):
            return None if value is None else positive(value, 'dimensão/avanço') * scale
        return cls(diameter_mm=convert(diameter), cutting_length_mm=convert(cutting_length),
                   shank_diameter_mm=convert(shank_diameter), overall_length_mm=convert(overall_length),
                   feed_mm_min=convert(feed), plunge_mm_min=convert(plunge), **metadata)

    def as_dict(self):
        return asdict(self)


class ToolLibrary:
    def __init__(self, tools=()):
        self._tools = {}
        for tool in tools:
            self.add(tool)

    def add(self, tool, *, replace=False):
        if not isinstance(tool, Tool):
            raise ValueError('Esperado um Tool validado')
        if tool.id in self._tools and not replace:
            raise ValueError('ID já cadastrado; substituição exige replace explícito')
        self._tools[tool.id] = tool

    def get(self, tool_id):
        try:
            return self._tools[tool_id]
        except KeyError as error:
            raise ValueError(f'Ferramenta não cadastrada: {tool_id}') from error

    def as_dict(self):
        return {'schema_version': 1, 'units': 'mm',
                'tools': [self._tools[key].as_dict() for key in sorted(self._tools)]}

    def save(self, path):
        write_json(path, self.as_dict())

    @classmethod
    def load(cls, path):
        record = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        if (not isinstance(record, dict) or set(record) != {'schema_version', 'units', 'tools'}
                or record['schema_version'] != 1 or record['units'] != 'mm'
                or not isinstance(record['tools'], list)):
            raise ValueError('Biblioteca de ferramentas incompatível')
        return cls(Tool.from_dict(item) for item in record['tools'])
