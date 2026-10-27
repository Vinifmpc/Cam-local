"""Atomic, profile-local machining preferences. Never stores part geometry."""
import copy
from dataclasses import asdict
import json
from pathlib import Path
import threading
import uuid
from cam_tools import Tool,positive,write_json
from cam_project import RoughingSettings
from cam_operations import OperationSettings

SETTING_KEYS=('stepdown_mm','sampling_mm','tolerance_mm','radial_allowance_mm',
    'axial_allowance_mm','boundary_margin_mm','entry_angle_deg','clearance_mm',
    'approach_gap_mm','strategy','raster_angle_deg','cleanup_contours')
OPERATION_KEYS=tuple(k for k in asdict(OperationSettings()) if k not in (
    'cutout_bottom_mm','drill_bottom_mm','smart_stock_bottom_mm','cutout_use_roughing_regions'))


def normalize_profile(record):
    if not isinstance(record,dict) or set(record)-{'tool','settings','operations','stepover_percent'}:
        raise ValueError('Perfil de usinagem inválido')
    tool=Tool.from_dict(record['tool']);settings=record.get('settings',{});operations=record.get('operations',{})
    if not isinstance(settings,dict) or set(settings)-set(SETTING_KEYS):raise ValueError('Ajustes do preset inválidos')
    if not isinstance(operations,dict) or set(operations)-set(OPERATION_KEYS):raise ValueError('Operações do preset inválidas')
    percent=positive(record.get('stepover_percent',40),'Stepover do preset')
    if percent>100:raise ValueError('Stepover do preset maior que 100%')
    defaults={'stepdown_mm':.7,'stepover_mm':tool.diameter_mm*percent/100,'stock_top_mm':0,
        'bottom_mm':-1,'region_mode':'layer','cleanup_contours':True,'compress_collinear':True}
    s=asdict(RoughingSettings(**{**defaults,**settings}))
    paused=(operations.get('machining_mode','manual')=='manual' and all(
        operations.get(k,k=='roughing_enabled') is False for k in ('roughing_enabled','cutout_enabled','drill_enabled')))
    o=asdict(OperationSettings.from_dict({**operations,**({'roughing_enabled':True} if paused else {})}))
    if paused:o['roughing_enabled']=False
    return {'tool':tool.as_dict(),'settings':{k:s[k] for k in SETTING_KEYS},
            'operations':{k:o[k] for k in OPERATION_KEYS},'stepover_percent':percent}


class PresetStore:
    def __init__(self,path):self.path=Path(path);self.lock=threading.RLock()

    def read(self):
        with self.lock:
            if not self.path.exists():return {'version':1,'presets':[],'last_used':None,'selected_id':None}
            if self.path.stat().st_size>2*1024*1024:raise ValueError('Arquivo de presets muito grande')
            try:
                d=json.loads(self.path.read_text('utf-8'))
                if d['version']!=1 or not isinstance(d['presets'],list) or len(d['presets'])>64:raise ValueError()
                ids=set()
                for p in d['presets']:
                    if not isinstance(p['id'],str) or p['id'] in ids:raise ValueError()
                    ids.add(p['id']);self.name(p['name']);p['profile']=normalize_profile(p['profile'])
                if d.get('last_used') is not None:d['last_used']=normalize_profile(d['last_used'])
                if d.get('selected_id') not in ids:d['selected_id']=None
                return d
            except (ValueError,TypeError,KeyError) as e:raise ValueError('Não foi possível ler os presets salvos; o arquivo foi preservado') from e

    @staticmethod
    def name(value):
        if not isinstance(value,str) or not 1<=len(value.strip())<=80 or any(ord(c)<32 for c in value):
            raise ValueError('Nome do preset: use de 1 a 80 caracteres')
        return value.strip()

    def update(self,record):
        with self.lock:
            d=self.read();action=record.get('action')
            if action=='remember':
                d['last_used']=normalize_profile(record['profile'])
                identifier=record.get('selected_id')
                if identifier is not None and not any(p['id']==identifier for p in d['presets']):raise ValueError('Preset não encontrado')
                d['selected_id']=identifier
            elif action=='save':
                p={'id':record.get('id') or uuid.uuid4().hex,'name':self.name(record.get('name')),
                   'profile':normalize_profile(record['profile'])}
                old=next((i for i,x in enumerate(d['presets']) if x['id']==p['id']),None)
                if record.get('id') and old is None:raise ValueError('Preset não encontrado')
                if old is None:
                    if len(d['presets'])>=64:raise ValueError('Limite de 64 presets atingido')
                    d['presets'].append(p)
                else:d['presets'][old]=p
                d.update(last_used=copy.deepcopy(p['profile']),selected_id=p['id'])
            elif action=='delete':
                identifier=record.get('id')
                if not any(p['id']==identifier for p in d['presets']):raise ValueError('Preset não encontrado')
                d['presets']=[p for p in d['presets'] if p['id']!=identifier]
                if d.get('selected_id')==identifier:d['selected_id']=None
            else:raise ValueError('Ação de preset inválida')
            write_json(self.path,d);return copy.deepcopy(d)

    def migrate_latest(self,projects):
        """Recover the user's own last settings when upgrading older builds."""
        if self.path.exists():return
        for project in sorted(Path(projects).glob('*/project.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:16]:
            try:
                d=json.loads(project.read_text('utf-8'));s=d['roughing'];tool=d['tool']
                profile=normalize_profile({'tool':tool,'settings':{k:s[k] for k in SETTING_KEYS if k in s},
                    'operations':{k:v for k,v in d.get('operations',{}).items() if k in OPERATION_KEYS},
                    'stepover_percent':100*s['stepover_mm']/tool['diameter_mm']})
                self.update({'action':'remember','profile':profile});return
            except (OSError,ValueError,KeyError,TypeError):continue
