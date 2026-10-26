"""Saved STL/tool setups connected to the existing roughing and motion engines."""
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import os
import hashlib
import numpy as np

from cam_tools import Tool, positive, write_json
from mesh_geometry import place_stl, read_stl, topology_report
from cam_operations import OperationSettings, validate_operations, compose


@dataclass(frozen=True)
class RoughingSettings:
    stepdown_mm: float
    stepover_mm: float
    stock_top_mm: float
    bottom_mm: float
    sampling_mm: float = .2
    tolerance_mm: float = 0.0
    radial_allowance_mm: float = 0.0
    axial_allowance_mm: float = 0.0
    boundary_margin_mm: float = .01
    raster_origin_y_mm: float = 0.0
    entry_angle_deg: float = 3.0
    clearance_mm: float = 2.54
    approach_gap_mm: float = .25
    obstacle_top_mm: float | None = None
    boundaries_mm: list | None = None
    exclusions_mm: list | None = None
    strategy: str = 'conformal'
    raster_angle_deg: float = 0.0
    compress_collinear: bool = False
    region_mode: str = 'projected'
    cleanup_contours: bool = False
    domain_mode: str = 'expanded'

    def __post_init__(self):
        if self.region_mode not in ('projected','layer') or self.domain_mode not in ('expanded','silhouette'):
            raise ValueError('Modo de região/domínio inválido')
        if type(self.cleanup_contours) is not bool or (self.cleanup_contours and self.region_mode!='layer'):
            raise ValueError('Contornos de limpeza exigem region_mode=layer')
        if self.strategy not in ('conformal','planar'):
            raise ValueError('Estratégia deve ser conformal ou planar')
        if isinstance(self.raster_angle_deg,bool) or not isinstance(self.raster_angle_deg,(int,float)) or not math.isfinite(self.raster_angle_deg) or not 0<=self.raster_angle_deg<180:
            raise ValueError('Direção das passadas deve estar entre 0 e menos de 180 graus')
        if type(self.compress_collinear) is not bool:
            raise ValueError('compress_collinear deve ser booleano')
        for key in ('stepdown_mm','stepover_mm','sampling_mm','clearance_mm'):
            positive(getattr(self,key),key)
        for key in ('tolerance_mm','radial_allowance_mm','axial_allowance_mm',
                    'boundary_margin_mm','approach_gap_mm'):
            positive(getattr(self,key),key,zero=True)
        for key in ('stock_top_mm','bottom_mm','raster_origin_y_mm','entry_angle_deg'):
            value=getattr(self,key)
            if isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value):
                raise ValueError(key+': número inválido')
        if self.obstacle_top_mm is not None:
            value=self.obstacle_top_mm
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
                raise ValueError('Altura de obstáculo inválida')
        if not 0<self.entry_angle_deg<90 or self.approach_gap_mm>self.clearance_mm:
            raise ValueError('Ângulo de rampa ou aproximação inválido')
        if self.stock_top_mm<=self.bottom_mm+self.tolerance_mm:
            raise ValueError('Topo deve ficar acima do fundo efetivo')
        for key in ('boundaries_mm','exclusions_mm'):
            paths=getattr(self,key)
            if paths is None:
                continue
            if not isinstance(paths,list):
                raise ValueError(key+': informe uma lista de polígonos XY')
            for polygon in paths:
                p=np.asarray(polygon,float)
                if p.ndim!=2 or p.shape[1:]!=(2,) or len(p)<3 or not np.isfinite(p).all():
                    raise ValueError(key+': polígono XY inválido')
                area=np.sum(p[:,0]*np.roll(p[:,1],-1)-p[:,1]*np.roll(p[:,0],-1))/2
                if not math.isfinite(float(area)) or abs(area)<1e-12:
                    raise ValueError(key+': polígono degenerado')
                # Reject crossings instead of relying on an implicit fill rule.
                def cross(a,b,c):
                    u,v=b-a,c-a
                    return float(u[0]*v[1]-u[1]*v[0])
                def intersects(a,b,c,d):
                    if np.any(np.maximum(np.minimum(a,b),np.minimum(c,d))>
                              np.minimum(np.maximum(a,b),np.maximum(c,d))):
                        return False
                    return cross(a,b,c)*cross(a,b,d)<=0 and cross(c,d,a)*cross(c,d,b)<=0
                # Optional repeated closing vertex is accepted.
                q=p[:-1] if np.array_equal(p[0],p[-1]) else p
                if len(q)<3 or np.any(np.linalg.norm(np.roll(q,-1,axis=0)-q,axis=1)==0):
                    raise ValueError(key+': aresta de comprimento zero')
                if len(q)>2000:
                    raise ValueError('Limite de 2000 vértices por polígono')
                for i in range(len(q)):
                    for j in range(i+1,len(q)):
                        if j==i+1 or (i==0 and j==len(q)-1):
                            continue
                        if intersects(q[i],q[(i+1)%len(q)],q[j],q[(j+1)%len(q)]):
                            raise ValueError(key+': polígono autointersectante')

    @classmethod
    def from_dict(cls, record):
        if not isinstance(record,dict):
            raise ValueError('Configuração de desbaste inválida')
        try:
            return cls(**record)
        except TypeError as error:
            raise ValueError('Campos de desbaste ausentes ou desconhecidos') from error


def validate_setup(mesh,tool,settings,*,roughing_enabled=True,operations=None):
    smart_plan=None
    if operations is not None and operations.machining_mode=='smart':
        from smart_planner import resolve_smart_plan
        settings,operations,smart_plan=resolve_smart_plan(mesh,tool,settings,operations)
        roughing_enabled=True
    low=mesh.triangles.reshape(-1,3).min(axis=0)
    high=mesh.triangles.reshape(-1,3).max(axis=0)
    if settings.stock_top_mm<high[2]-1e-8:
        raise ValueError('Topo do bruto está abaixo do topo da peça')
    if roughing_enabled and settings.bottom_mm<low[2]-1e-8:
        raise ValueError('Fundo abaixo do STL; este desbaste não corta além do modelo')
    if roughing_enabled and settings.stock_top_mm-settings.bottom_mm>tool.cutting_length_mm+1e-8:
        raise ValueError('Profundidade solicitada excede o comprimento de corte cadastrado')
    if roughing_enabled and settings.stepover_mm>tool.diameter_mm:
        raise ValueError('Passo lateral maior que o diâmetro deixa faixas sem corte')
    if settings.bottom_mm+settings.tolerance_mm>=settings.stock_top_mm:
        raise ValueError('Não há intervalo de camadas')
    warnings=[]
    topology=topology_report(mesh)
    if not topology['closed_consistent_edges'] or topology['duplicate_faces']:
        warnings.append('Malha com bordas abertas, conectividade/orientação irregular ou faces duplicadas; sem reparo automático.')
    if settings.sampling_mm>tool.diameter_mm/2:
        warnings.append('Amostragem grossa em relação ao diâmetro: envelope conservador pode reter detalhes.')
    options=operations or OperationSettings(roughing_enabled=roughing_enabled,cutout_enabled=not roughing_enabled)
    feeds=[options.roughing_feed_mm_min or tool.feed_mm_min] if options.roughing_enabled else []
    if options.cutout_enabled:feeds.append(options.cutout_feed_mm_min or tool.feed_mm_min)
    if options.drill_enabled and options.drill_allow_helix:feeds.append(options.drill_feed_mm_min or tool.feed_mm_min)
    if any(value is None for value in (*feeds,options.plunge_mm_min or tool.plunge_mm_min,options.spindle_rpm or tool.spindle_rpm)):
        warnings.append('Avanços/rotação não estão todos preenchidos; nenhum valor será escolhido automaticamente.')
    warnings.append('Haste e porta-fresa não são simulados; dimensões cadastradas não certificam colisões.')
    report={'status':'passed','tool':tool.as_dict(),'mesh':mesh.summary(),
            'topology':topology,'settings':asdict(settings),'warnings':warnings,
            'limits':{'tool_cutting_length_mm':tool.cutting_length_mm,
                      'requested_depth_mm':settings.stock_top_mm-settings.bottom_mm,
                      'stepover_percent':100*settings.stepover_mm/tool.diameter_mm}}
    if smart_plan is not None:report['smart_plan']=smart_plan
    return report


def create_project(stl_path,project_path,*,units,tool,settings,rotation=None,
                   xy_origin='keep',z_origin='keep',translation_mm=(0,0,0),notes='',operations=None):
    mesh=place_stl(stl_path,units=units,rotation=rotation,xy_origin=xy_origin,
                   z_origin=z_origin,translation_mm=translation_mm)
    options=operations or OperationSettings()
    report=validate_setup(mesh,tool,settings,roughing_enabled=options.roughing_enabled,operations=options)
    if options.machining_mode=='smart':
        from smart_planner import resolve_smart_plan
        effective,resolved,_=resolve_smart_plan(mesh,tool,settings,options)
        validate_operations(resolved,effective,tool)
    else:validate_operations(options,settings,tool)
    destination=Path(project_path).resolve()
    source=Path(stl_path).resolve()
    if source==destination:
        raise ValueError('Projeto não pode sobrescrever o STL')
    if not isinstance(notes,str):
        raise ValueError('Notas devem ser texto')
    # Relocatable when the input and project are packaged together. Cross-drive
    # Windows setups keep an absolute input path, with the same hash check.
    try:
        relative=os.path.relpath(source,destination.parent)
    except ValueError:
        relative=str(source)
    project={'schema_version':1,'units':'mm','source':{'path':relative,
             'sha256':mesh.source_sha256,'units':units},
             'alignment':{'rotation':mesh.rotation,'translation_mm':mesh.translation},
             'tool':tool.as_dict(),'roughing':asdict(settings),'notes':notes,
             'inspection':report,
             'tool_binding':'snapshot: alterações posteriores na biblioteca não mudam este projeto'}
    if operations is not None:project['operations']=asdict(options)
    write_json(destination,project)
    return project


def load_project(path):
    path=Path(path).resolve()
    record=json.loads(path.read_text(encoding='utf-8-sig'))
    expected={'schema_version','units','source','alignment','tool','roughing','notes','inspection','tool_binding'}
    if not isinstance(record,dict) or set(record)-{'operations'}!=expected or record['schema_version']!=1 or record['units']!='mm':
        raise ValueError('Versão/formato de projeto incompatível')
    try:
        source=record['source'];alignment=record['alignment']
        if set(source)!={'path','sha256','units'} or set(alignment)!={'rotation','translation_mm'}:
            raise ValueError('Campos da fonte/alinhamento incompatíveis')
        stl_path=Path(source['path'])
        if not stl_path.is_absolute():stl_path=path.parent/stl_path
        mesh=read_stl(stl_path,units=source['units'],rotation=alignment['rotation'],
                      translation=alignment['translation_mm'])
        if mesh.source_sha256!=source['sha256']:
            raise ValueError('STL mudou desde que o projeto foi salvo; importe novamente')
        tool=Tool.from_dict(record['tool'])
        settings=RoughingSettings.from_dict(record['roughing'])
        options=OperationSettings.from_dict(record.get('operations',{}))
        if options.machining_mode=='smart':
            from smart_planner import resolve_smart_plan
            effective,resolved,_=resolve_smart_plan(mesh,tool,settings,options)
            validate_operations(resolved,effective,tool)
        else:validate_operations(options,settings,tool)
    except (KeyError,TypeError) as error:
        raise ValueError('Fonte/alinhamento de projeto inválido') from error
    # Recompute validation; never trust the cached inspection as authority.
    inspection=validate_setup(mesh,tool,settings,roughing_enabled=options.roughing_enabled,operations=options)
    return record,mesh,tool,settings,inspection


def calculate_project(path,*,include_motion=False,progress=None):
    notify=progress or (lambda phase,fraction:None)
    notify('Lendo STL e conferindo a configuração',.03)
    project_hash=hashlib.sha256(Path(path).read_bytes()).hexdigest()
    record,mesh,tool,s,inspection=load_project(path)
    # Lazy imports allow catalogue/STL inspection without Clipper/OCL installed.
    from stl_roughing import generate_stl_roughing
    options=OperationSettings.from_dict(record.get('operations',{}))
    from smart_planner import (resolve_smart_plan,retention_parameters,validate_smart_retention,
                               add_preparation_contours,validate_smart_geometry)
    s,options,smart_plan=resolve_smart_plan(mesh,tool,s,options)
    retention=retention_parameters(mesh.triangles,tool,s,smart_plan)
    # Validate/build the inexpensive silhouette cutout BEFORE the expensive
    # roughing and material-depth proofs. A tool that cannot fit an internal
    # contour must fail promptly, regardless of the chosen execution order.
    # Keep the generated job for later planning; do not compute it twice.
    cutout=None;drill=None;drill_plan=None
    drill_arguments=dict(diameter=tool.diameter_mm,tool_length=tool.cutting_length_mm,
        stock_top=s.stock_top_mm,bottom=options.drill_bottom_mm if options.drill_bottom_mm is not None else s.bottom_mm,
        peck=options.drill_peck_mm,tolerance=options.drill_tolerance_mm,
        allow_helix=options.drill_allow_helix,center_cutting=options.drill_center_cutting,
        compensate_facets=options.drill_compensate_facets,
        clearance=s.clearance_mm,obstacle_top=s.obstacle_top_mm,entry_angle_deg=s.entry_angle_deg)
    if options.drill_enabled:
        notify('Detectando furos circulares e conferindo a ferramenta do Drill',.04)
        from drill import generate_drill
        drill,drill_plan=generate_drill(mesh.triangles,**drill_arguments,
            progress=(lambda phase,fraction:notify(phase,.04+.015*fraction)) if progress else None)
    if options.cutout_enabled:
        notify('Conferindo se a fresa cabe nos contornos do cutout',.06)
        from cutout import generate_cutout
        bottom=validate_operations(options,s,tool)
        cutout=generate_cutout(mesh.triangles,diameter=tool.diameter_mm,tool_length=tool.cutting_length_mm,
            top=s.stock_top_mm,bottom=bottom,stepdown=options.cutout_stepdown_mm,direction=options.cutout_direction,
            contours=options.cutout_contours,
            internal_indices=(smart_plan['internal_cutouts']['selected_indices'] or None) if smart_plan is not None else None)
        notify('Contornos do cutout conferidos',.10)
    notify('Calculando regiões e passadas de desbaste',.12)
    result=generate_stl_roughing(mesh.triangles,diameter=tool.diameter_mm,
        tool_length=tool.cutting_length_mm,stepdown=s.stepdown_mm,stepover=s.stepover_mm,
        sampling=s.sampling_mm,z_top=s.stock_top_mm,z_bottom=s.bottom_mm,
        tolerance=s.tolerance_mm,radial_allowance=s.radial_allowance_mm,
        axial_allowance=s.axial_allowance_mm,boundaries=s.boundaries_mm,
        exclusions=s.exclusions_mm,boundary_margin=s.boundary_margin_mm,
        raster_origin_y=s.raster_origin_y_mm,strategy=s.strategy,
        raster_angle_deg=s.raster_angle_deg,compress_collinear=s.compress_collinear,
        region_mode=s.region_mode,cleanup_contours=s.cleanup_contours,domain_mode=s.domain_mode,
        retention=retention,
        center_domain=smart_plan['automatic_regions'].get('source_polygons_mm',smart_plan['automatic_regions']['polygons_mm']) if smart_plan is not None else None,
        protected_overlap_mm=smart_plan['automatic_regions']['quantized_boundary_overlap_mm'] if smart_plan is not None else 0,
        defer_depth_staging=smart_plan is not None,
        progress=(lambda phase,fraction:notify(phase,.12+.32*fraction)) if progress else None) if options.roughing_enabled else {
            'layers':[],'cutting_edges':0,'parameters':{'z_top':s.stock_top_mm,'stepdown':s.stepdown_mm},
            'tool':{'diameter':tool.diameter_mm,'length':tool.cutting_length_mm}}
    if smart_plan is not None:
        notify(('Ordenando os rebaixos e bolsões do Rough' if
                smart_plan['exterior_strategy']['mode']=='features_then_cutout' else
                'Preparando o canal externo para liberar a peça'),.445)
        result=add_preparation_contours(result,mesh.triangles,tool,s,options,smart_plan,
            progress=(lambda phase,fraction:notify(phase,.445+.005*fraction)) if progress else None)
        validate_smart_geometry(result,mesh.triangles,tool,s,options,smart_plan)
    result['tool_profile']=tool.as_dict()
    result['source']=mesh.summary()
    result['setup_inspection']=inspection
    result['project_notes']=record['notes']
    if smart_plan is not None:validate_smart_retention(result,mesh.triangles,tool,s,smart_plan)
    motion=None
    operations=[]
    if options.cutout_enabled:
        notify('Contornos e profundidades do cutout preparados',.45)
    if include_motion:
        from motion_planner import plan_ramps_and_links
        initial=None;prior_roughing=None
        jobs={'roughing':result,'cutout':cutout,'drill':drill}
        sequence=options.sequence()
        for index,name in enumerate(sequence):
            notify('Planejando movimentos: '+{'roughing':'desbaste','cutout':'Cutout','drill':'Drill'}[name],.52+.35*index/len(sequence))
            job=jobs[name]
            # The existing stock-proof contract also requires exact continuity
            # from Rough's final position. An intervening Drill uses its own
            # motion and therefore conservatively leaves Cutout unadapted.
            prior=prior_roughing if (name=='cutout' and options.cutout_use_prior_roughing
                and index>0 and sequence[index-1]=='roughing') else None
            if name=='drill':
                if initial is not None:
                    drill,drill_plan=generate_drill(mesh.triangles,initial_position=initial,**drill_arguments,
                        progress=(lambda phase,fraction:notify(phase,.52+.35*(index+fraction)/len(sequence))) if progress else None)
                plan=drill_plan
                initial=plan['final_position'];operations.append((name,plan));continue
            if prior is not None:
                from cutout_rest import adapt_cutout_to_prior
                job=adapt_cutout_to_prior(job,prior)
                cutout=jobs['cutout']=job
            plan=plan_ramps_and_links(job,mesh.triangles,entry_angle_deg=s.entry_angle_deg,
                clearance=s.clearance_mm,approach_gap=s.approach_gap_mm,
                stock_top=s.stock_top_mm,obstacle_top=s.obstacle_top_mm,initial_position=initial,
                path_order=options.roughing_order if name=='roughing' else 'layer',
                prior_motion=prior,
                allow_center_plunge=smart_plan is not None and options.drill_center_cutting and name=='roughing',
                progress=(lambda phase,fraction:notify(phase,.52+.35*(index+fraction)/len(sequence))) if progress else None)
            initial=plan['final_position'];operations.append((name,plan))
            if name=='roughing':
                prior_roughing=plan
                if smart_plan is not None:
                    validate_smart_retention(result,mesh.triangles,tool,s,smart_plan,motion=plan)
                    validate_smart_geometry(result,mesh.triangles,tool,s,options,smart_plan,motion=plan)
        notify('Compondo operações e calculando os tempos',.90)
        motion=compose(operations,options,tool)
        motion['tool_profile']=tool.as_dict()
    if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=project_hash:
        raise ValueError('Projeto mudou durante o cálculo; recalcule')
    notify('Percursos conferidos',.95)
    return {'schema_version':1,'units':'mm','roughing':result,'cutout':cutout,'drill':drill,'motion':motion,
            'project_sha256':project_hash,'smart_plan':smart_plan,
            'operations':{name:plan for name,plan in operations},
            'gcode_emitted':False}
