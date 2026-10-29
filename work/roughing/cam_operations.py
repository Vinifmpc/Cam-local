"""Operation settings, composition and configurable machine motion timing."""
from collections import Counter
from dataclasses import dataclass, asdict, field
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
    cutout_smoothing_mm: float = 0.0
    cutout_direction: str = 'climb'
    cutout_contours: str = 'external'
    cutout_use_prior_roughing: bool = True
    cutout_use_roughing_regions: bool = False
    roughing_feed_mm_min: float | None = None
    cutout_feed_mm_min: float | None = None
    plunge_mm_min: float | None = None
    rapid_mm_min: float = 3000
    timing_model: str = 'acceleration'
    machine_max_rate_mm_min: list = field(default_factory=lambda:[1500.,1500.,1500.])
    machine_acceleration_mm_s2: list = field(default_factory=lambda:[10.,10.,10.])
    machine_steps_per_mm: list = field(default_factory=lambda:[400.,400.,400.])
    machine_junction_deviation_mm: float = .01
    machine_planner_blocks: int = 15
    spindle_rpm: float | None = None
    drill_enabled: bool = False
    drill_allow_helix: bool = False
    drill_center_cutting: bool = False
    drill_compensate_facets: bool = False
    drill_bottom_mm: float | None = None
    drill_peck_mm: float = 1.0
    drill_tolerance_mm: float = .03
    drill_feed_mm_min: float | None = None
    drill_retract_mode: str = 'full'
    drill_retract_mm: float = 1.0
    drill_rapid_reentry: bool = True
    drill_reentry_gap_mm: float = .25
    operation_sequence: list | None = None
    machining_mode: str = 'manual'
    smart_part_released: bool = False
    smart_stock_bottom_mm: float | None = None
    smart_breakthrough_mm: float = 0.0
    smart_skin_mm: float | None = None

    def __post_init__(self):
        if self.timing_model not in ('acceleration','constant'):raise ValueError('Modelo de tempo inválido')
        for key in ('machine_max_rate_mm_min','machine_acceleration_mm_s2','machine_steps_per_mm'):
            values=getattr(self,key)
            if not isinstance(values,(list,tuple)) or len(values)!=3:raise ValueError(key+': informe X, Y e Z')
            object.__setattr__(self,key,[positive(value,key) for value in values])
        positive(self.machine_junction_deviation_mm,'machine_junction_deviation_mm',zero=True)
        if type(self.machine_planner_blocks) is not int or not 2<=self.machine_planner_blocks<=128:
            raise ValueError('Antecipação do planejador deve ficar entre 2 e 128 blocos')
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
                  'drill_enabled','drill_allow_helix','drill_center_cutting','drill_compensate_facets','drill_rapid_reentry','smart_part_released'):
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
            if not self.smart_part_released:object.__setattr__(self,'cutout_enabled',True)
            object.__setattr__(self,'cutout_contours','internal' if self.smart_part_released else 'external')
            object.__setattr__(self,'cutout_use_prior_roughing',True)
            object.__setattr__(self,'order','roughing_then_cutout')
            object.__setattr__(self,'operation_sequence',['drill','roughing','cutout'])
        if not any((self.roughing_enabled,self.cutout_enabled,self.drill_enabled)):
            raise ValueError('Ative ao menos uma operação')
        if self.cutout_direction not in ('climb','conventional'):raise ValueError('Sentido do cutout inválido')
        if self.cutout_contours not in ('external','internal','all'):raise ValueError('Contornos do cutout inválidos')
        if self.drill_retract_mode not in ('full','chip_break'):raise ValueError('Retração do Drill inválida')
        positive(self.cutout_smoothing_mm,'cutout_smoothing_mm',zero=True)
        if self.cutout_smoothing_mm>.1:raise ValueError('Fluidez do Cutout deve ficar entre 0 e 0,1 mm')
        for k in ('cutout_stepdown_mm','rapid_mm_min','drill_peck_mm','drill_tolerance_mm','drill_retract_mm','drill_reentry_gap_mm'):
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
    """Set programmed feeds first, then estimate physical timing separately.

    Machine profile affects estimates and playback only. It never rewrites
    F or emits controller settings. Missing feeds retain the untimed contract.
    """
    elapsed=0.;complete=True
    feeds={'roughing':options.roughing_feed_mm_min,'cutout':options.cutout_feed_mm_min,
           'drill':options.drill_feed_mm_min}
    for m in motion['moves']:
        rapid=m['kind'] in ('travel','retract','clearance_adjust','approach_rapid')
        vertical=math.dist(m['start'][:2],m['end'][:2])<1e-9 and m['end'][2]<m['start'][2]
        feed=feeds.get(m.get('operation'),options.roughing_feed_mm_min) or tool.feed_mm_min
        rate=options.rapid_mm_min if rapid else ((options.plunge_mm_min or tool.plunge_mm_min) if vertical else feed)
        m['feed_mm_min']=rate
        m['duration_s']=None if rate is None else 60*math.dist(m['start'],m['end'])/rate
        m.pop('timing_profile',None)
        if rate is None:complete=False
        else:elapsed+=m['duration_s']
    motion['timing']={'available':complete,'duration_s':elapsed if complete else None,
        'rapid_mm_min':options.rapid_mm_min,'model':'constant_path_feed_no_acceleration',
        'rapid_is_assumption':True}
    if complete and options.timing_model=='acceleration':
        if any(move['kind'] not in ('travel','retract','clearance_adjust','approach_rapid')
                and round(move['feed_mm_min'],5)<=0 for move in motion['moves']):
            for move in motion['moves']:move['duration_s']=None
            motion['timing'].update(available=False,duration_s=None,
                reason='Avanço perde precisão no NC; preencha um avanço representável e recalcule')
            return motion
        from motion_timing import estimate_acceleration
        report=estimate_acceleration(motion['moves'],max_rates_mm_min=options.machine_max_rate_mm_min,
            accelerations_mm_s2=options.machine_acceleration_mm_s2,
            junction_deviation_mm=options.machine_junction_deviation_mm,
            steps_per_mm=options.machine_steps_per_mm,planner_blocks=options.machine_planner_blocks)
        profiles=report.pop('profiles')
        for move,profile in zip(motion['moves'],profiles,strict=True):
            move['duration_s']=profile['duration_s'];move['timing_profile']=profile
        motion['timing']={**report,'constant_feed_duration_s':elapsed,
            'rapid_mm_min':options.rapid_mm_min,'rapid_is_assumption':True,
            'profile_controls_estimate_only':True}
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
