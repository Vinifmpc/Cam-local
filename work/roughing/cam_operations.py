"""Operation settings, continuous composition and ideal constant-feed timing."""
from collections import Counter
from dataclasses import dataclass, asdict
import math
from cam_tools import positive


@dataclass(frozen=True)
class OperationSettings:
    order: str = 'roughing_then_cutout'
    roughing_order: str = 'region_first'
    roughing_enabled: bool = True
    cutout_enabled: bool = False
    cutout_bottom_mm: float | None = None
    cutout_stepdown_mm: float = .635
    cutout_direction: str = 'climb'
    cutout_contours: str = 'external'
    cutout_use_prior_roughing: bool = True
    cutout_use_roughing_regions: bool = False
    roughing_feed_mm_min: float | None = None
    cutout_feed_mm_min: float | None = None
    plunge_mm_min: float | None = None
    rapid_mm_min: float = 3000
    spindle_rpm: float | None = None
    drill_enabled: bool = False
    drill_allow_helix: bool = False
    drill_center_cutting: bool = False
    drill_compensate_facets: bool = False
    drill_bottom_mm: float | None = None
    drill_peck_mm: float = 1.0
    drill_tolerance_mm: float = .03
    drill_feed_mm_min: float | None = None
    operation_sequence: list | None = None
    machining_mode: str = 'manual'
    smart_stock_bottom_mm: float | None = None
    smart_breakthrough_mm: float = 0.0
    smart_skin_mm: float | None = None

    def __post_init__(self):
        if self.machining_mode not in ('manual','smart'):
            raise ValueError('Modo de usinagem inválido')
        for key in ('smart_stock_bottom_mm','smart_skin_mm'):
            value=getattr(self,key)
            if value is not None and (isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value)):
                raise ValueError(key+': número inválido')
        if self.smart_skin_mm is not None:positive(self.smart_skin_mm,'smart_skin_mm')
        positive(self.smart_breakthrough_mm,'smart_breakthrough_mm',zero=True)
        if self.order not in ('roughing_then_cutout','cutout_then_roughing'):
            raise ValueError('Ordem de operações inválida')
        if self.roughing_order not in ('layer','region_first'):
            raise ValueError('Prioridade do desbaste inválida')
        for k in ('roughing_enabled','cutout_enabled','cutout_use_roughing_regions','cutout_use_prior_roughing',
                  'drill_enabled','drill_allow_helix','drill_center_cutting','drill_compensate_facets'):
            if type(getattr(self,k)) is not bool:raise ValueError(k+': informe um booleano')
        if self.operation_sequence is not None:
            names=self.operation_sequence
            if (not isinstance(names,list) or len(names)!=3
                    or any(type(name) is not str for name in names)
                    or set(names)!={'roughing','drill','cutout'}):
                raise ValueError('Sequência deve conter roughing, drill e cutout uma vez cada')
            # Preserve the legacy two-operation enum for clients that still use
            # it, while the complete sequence controls all three operations.
            object.__setattr__(self,'operation_sequence',list(names))
            object.__setattr__(self,'order','roughing_then_cutout' if names.index('roughing')<names.index('cutout')
                               else 'cutout_then_roughing')
        # Kept only to open old project files. Cutout selection is independent
        # of roughing boundaries/keepouts in the current pipeline.
        object.__setattr__(self,'cutout_use_roughing_regions',False)
        if self.machining_mode=='smart':
            object.__setattr__(self,'roughing_enabled',True)
            object.__setattr__(self,'cutout_enabled',True)
            object.__setattr__(self,'cutout_contours','external')
            object.__setattr__(self,'cutout_use_prior_roughing',True)
            object.__setattr__(self,'order','roughing_then_cutout')
            object.__setattr__(self,'operation_sequence',['drill','roughing','cutout'])
        if not any((self.roughing_enabled,self.cutout_enabled,self.drill_enabled)):
            raise ValueError('Ative ao menos uma operação')
        if self.cutout_direction not in ('climb','conventional'):raise ValueError('Sentido do cutout inválido')
        if self.cutout_contours not in ('external','all'):raise ValueError('Contornos do cutout inválidos')
        for k in ('cutout_stepdown_mm','rapid_mm_min','drill_peck_mm','drill_tolerance_mm'):
            positive(getattr(self,k),k)
        for k in ('roughing_feed_mm_min','cutout_feed_mm_min','drill_feed_mm_min','plunge_mm_min','spindle_rpm'):
            v=getattr(self,k)
            if v is not None:positive(v,k)
        for name in ('cutout','drill'):
            v=getattr(self,name+'_bottom_mm')
            if v is not None and (isinstance(v,bool) or not isinstance(v,(float,int)) or not math.isfinite(v)):
                raise ValueError('Z final do '+name+' inválido')

    @classmethod
    def from_dict(cls,record):
        if not isinstance(record,dict):raise ValueError('Operações inválidas')
        try:return cls(**record)
        except TypeError as e:raise ValueError('Campos de operações incompatíveis') from e

    def sequence(self):
        names=self.operation_sequence
        if names is None:
            names=(['roughing','cutout'] if self.order=='roughing_then_cutout' else ['cutout','roughing'])+['drill']
        return [name for name in names if getattr(self,name+'_enabled')]


def validate_operations(options,rough,tool):
    # Before STL placement is available the smart final depth can only be
    # provisional. The planner revalidates its resolved depth against reach.
    bottom=((options.smart_stock_bottom_mm if options.smart_stock_bottom_mm is not None else rough.bottom_mm)
            -options.smart_breakthrough_mm if options.machining_mode=='smart' else
            options.cutout_bottom_mm if options.cutout_bottom_mm is not None else rough.bottom_mm)
    known_smart_depth=options.machining_mode!='smart' or options.smart_stock_bottom_mm is not None
    if options.cutout_enabled and known_smart_depth:
        if bottom>=rough.stock_top_mm:raise ValueError('Profundidade do cutout precisa ser positiva')
        if rough.stock_top_mm-bottom>tool.cutting_length_mm+1e-8:
            raise ValueError('Profundidade do cutout excede o comprimento de corte cadastrado')
    if options.drill_enabled and (known_smart_depth or options.drill_bottom_mm is not None):
        drill_bottom=options.drill_bottom_mm if options.drill_bottom_mm is not None else rough.bottom_mm
        if drill_bottom>=rough.stock_top_mm:raise ValueError('Profundidade do drill precisa ser positiva')
        if rough.stock_top_mm-drill_bottom>tool.cutting_length_mm+1e-8:
            raise ValueError('Profundidade do drill excede o comprimento de corte cadastrado')
    return bottom


def add_timing(motion,options,tool):
    """F is the 3D path speed in mm/min; vertical descents use plunge rate.

    G0 is an explicitly configured rapid approximation. No acceleration,
    spindle dwell or controller look-ahead is modelled. Missing feeds never
    receive an invented value: legacy untimed projects can still be opened.
    """
    elapsed=0.;complete=True
    feeds={'roughing':options.roughing_feed_mm_min,'cutout':options.cutout_feed_mm_min,
           'drill':options.drill_feed_mm_min}
    for m in motion['moves']:
        rapid=m['kind'] in ('travel','retract','clearance_adjust')
        vertical=math.dist(m['start'][:2],m['end'][:2])<1e-9 and m['end'][2]<m['start'][2]
        feed=feeds.get(m.get('operation'),options.roughing_feed_mm_min) or tool.feed_mm_min
        rate=options.rapid_mm_min if rapid else ((options.plunge_mm_min or tool.plunge_mm_min) if vertical else feed)
        m['feed_mm_min']=rate
        m['duration_s']=None if rate is None else 60*math.dist(m['start'],m['end'])/rate
        if rate is None:complete=False
        else:elapsed+=m['duration_s']
    motion['timing']={'available':complete,'duration_s':elapsed if complete else None,
        'rapid_mm_min':options.rapid_mm_min,'model':'constant_path_feed_no_acceleration',
        'rapid_is_assumption':True}
    return motion


def compose(plans,options,tool):
    moves=[];entries=[];offsets={}
    for name,plan in plans:
        if moves and math.dist(moves[-1]['end'],plan['initial_position'])>1e-8:
            raise ValueError('Descontinuidade entre operações')
        offset=len(moves)
        if plan.get('prior_roughing') and (name!='cutout' or 'roughing' not in offsets
                or not options.cutout_use_prior_roughing):
            raise ValueError('Cutout usa desbaste anterior incompatível com a ordem das operações')
        for m in plan['moves']:
            proof=dict(m['proof'])
            if isinstance(proof.get('source_cut_move'),int):proof['source_cut_move']+=offset
            if isinstance(proof.get('source_prior_cut_move'),int):
                if 'roughing' not in offsets:raise ValueError('Prova de corte anterior sem desbaste executado')
                proof['source_cut_move']=offsets['roughing']+proof.pop('source_prior_cut_move')
            moves.append({**m,'id':len(moves),'operation':name,'proof':proof})
        entries.extend({**e,'operation':name} for e in plan['entries'])
        offsets[name]=offset
    first=plans[0][1];last=plans[-1][1]
    combined={'moves':moves,'entries':entries,'initial_position':first['initial_position'],
        'final_position':last['final_position'],'safe_z':first['safe_z'],
        'move_counts':dict(Counter(m['kind'] for m in moves)),
        'validation':{'status':'passed','scope':'Each operation replayed independently; inter-operation continuity checked',
                      'source_edges_preserved':sum(p['validation']['source_edges_preserved'] for _,p in plans),
                      'operations':{name:p['validation'] for name,p in plans}},
        'operation_ranges':[{'name':name,'moves':len(p['moves'])} for name,p in plans]}
    return add_timing(combined,options,tool)
