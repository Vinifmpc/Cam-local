"""Small independent GRBL 1.1 linear post; no machine connection.

Explicit mm/absolute/mm-min/G54, precompensated XYZ, clockwise spindle.
The required initial state is at/above the calculated clearance in the
configured work coordinate system, with correct tool zero and fixturing.
"""
import hashlib
import math
from pathlib import Path
from tempfile import TemporaryDirectory
from audit_gcode import audit
from cam_project import load_project
from cam_operations import OperationSettings,compose
from motion_planner import validate_motion,NC_COORD_DECIMALS
from cam_tools import positive,write_json

DECIMALS=NC_COORD_DECIMALS
COORD_ERROR=math.sqrt(3)*.5*10**(-DECIMALS)+1e-10


def validate_calculation(result,project_path):
    project_path=Path(project_path)
    if result.get('project_sha256')!=hashlib.sha256(project_path.read_bytes()).hexdigest():
        raise ValueError('Projeto mudou ou resultado é antigo. Recalcule antes de exportar')
    record,mesh,tool,s,inspection=load_project(project_path)
    options=OperationSettings.from_dict(record.get('operations',{}))
    from smart_planner import resolve_smart_plan,validate_smart_retention,validate_smart_geometry
    s,options,smart_plan=resolve_smart_plan(mesh,tool,s,options)
    if result.get('smart_plan')!=smart_plan:
        raise ValueError('Plano inteligente mudou; recalcule antes de exportar')
    sequence=options.sequence()
    if list(result.get('operations',{}))!=sequence:raise ValueError('Ordem calculada não corresponde ao projeto')
    plans=[];prior_roughing=None
    for index,name in enumerate(sequence):
        plan=result['operations'][name];job=result[name]
        if name=='roughing' and plan.get('path_order','layer')!=options.roughing_order:
            raise ValueError('Prioridade do rough mudou; recalcule antes de exportar')
        if name!='drill' and plan['parameters'].get('allow_center_plunge',False)!=(
                name=='roughing' and smart_plan is not None and options.drill_center_cutting):
            raise ValueError('Confirmação de corte pelo centro mudou; recalcule')
        if name=='roughing' and smart_plan is not None:
            validate_smart_retention(job,mesh.triangles,tool,s,smart_plan,motion=plan)
            validate_smart_geometry(job,mesh.triangles,tool,s,options,smart_plan,motion=plan)
        prior=prior_roughing if (name=='cutout' and options.cutout_use_prior_roughing
            and index>0 and sequence[index-1]=='roughing') else None
        if name=='cutout':
            # Rebuild the selected contour geometry from the saved STL. Rest
            # machining may omit only complete passes proved by earlier cuts.
            from cutout import generate_cutout
            from cam_operations import validate_operations
            original=generate_cutout(mesh.triangles,diameter=tool.diameter_mm,
                tool_length=tool.cutting_length_mm,top=s.stock_top_mm,
                bottom=validate_operations(options,s,tool),stepdown=options.cutout_stepdown_mm,
                direction=options.cutout_direction,contours=options.cutout_contours)
            for key in ('parameters','tool','contours','contours_selection',
                        'internal_contours_total','skipped_internal_contours'):
                if job.get(key)!=original[key]:
                    raise ValueError('Contornos do Cutout mudaram; recalcule antes de exportar')
            if prior is not None:
                if (job.get('rest_source_layers')!=original['layers'] or
                        job.get('rest_source_depth_levels')!=original['depth_levels']):
                    raise ValueError('Origem das passadas do Cutout não corresponde ao STL')
                from cutout_rest import validate_cutout_rest
                validate_cutout_rest(job,prior)
            elif (job.get('rest_material') or {}).get('applied') or job['layers']!=original['layers']:
                raise ValueError('Cutout depende de desbaste anterior não executado; recalcule')
        if name=='drill':
            from drill import generate_drill,validate_drill_motion
            original,_=generate_drill(mesh.triangles,diameter=tool.diameter_mm,tool_length=tool.cutting_length_mm,
                stock_top=s.stock_top_mm,bottom=options.drill_bottom_mm if options.drill_bottom_mm is not None else s.bottom_mm,
                peck=options.drill_peck_mm,tolerance=options.drill_tolerance_mm,
                allow_helix=options.drill_allow_helix,center_cutting=options.drill_center_cutting,
                compensate_facets=options.drill_compensate_facets,
                clearance=s.clearance_mm,obstacle_top=s.obstacle_top_mm,
                entry_angle_deg=s.entry_angle_deg,initial_position=plan['initial_position'])
            if job!=original:raise ValueError('Furos ou parâmetros do Drill mudaram; recalcule')
            validate_drill_motion(plan,job,mesh.triangles)
        else:validate_motion(plan,job,prior_motion=prior)
        plans.append((name,plan))
        if name=='roughing':prior_roughing=plan
    expected=compose(plans,options,tool)
    actual=result['motion']
    if len(expected['moves'])!=len(actual['moves']) or expected['initial_position']!=actual['initial_position'] or expected['safe_z']!=actual['safe_z']:
        raise ValueError('Movimentos compostos incompatíveis')
    for a,b in zip(expected['moves'],actual['moves']):
        if any(a.get(k)!=b.get(k) for k in ('kind','start','end','operation','feed_mm_min')):
            raise ValueError('Movimento ou avanço mudou desde o cálculo')
    if not expected['moves']:raise ValueError('Não há movimentos para exportar')
    if not expected['timing']['available']:raise ValueError('Preencha os avanços e recalcule antes de exportar')
    spindle=options.spindle_rpm or tool.spindle_rpm
    if spindle is None:raise ValueError('Preencha o RPM do spindle e recalcule antes de exportar')
    positive(spindle,'spindle_rpm')
    # Trusted bound from the saved setup, rather than cached motion metadata.
    expected['entry_angle_limit_deg']=s.entry_angle_deg
    return expected,spindle,options


def render(motion,spindle,order):
    def number(v):
        if not math.isfinite(v):raise ValueError('Coordenada/avanço não finito')
        s=f'{v:.{DECIMALS}f}'
        return '0.00000' if float(s)==0 else s
    if round(spindle,DECIMALS)<=0:raise ValueError('RPM perde precisão no formato NC')
    lines=['(CAM LOCAL - EXPERIMENTAL GRBL MM)',
        '(VERIFY G54 ZERO TOOL AND FIXTURING)',
        '(START AT OR ABOVE CLEARANCE Z)',
        '(CUTOUT FIRST REQUIRES RETAINING THE PART)',
        'G21','G90','G94','G17','G40','G49','G54','M5']
    initial=motion['initial_position']
    lines+=['G0 Z'+number(initial[2]),'G0 X'+number(initial[0])+' Y'+number(initial[1]),
            'S'+number(spindle)+' M3']
    mapped=[];operation=None
    for m in motion['moves']:
        if m['operation']!=operation:
            operation=m['operation'];lines.append('(OP '+operation.upper()+')')
        rapid=m['kind'] in ('travel','retract','clearance_adjust')
        row=('G0' if rapid else 'G1')+' '+ ' '.join(axis+number(v) for axis,v in zip('XYZ',m['end']))
        if not rapid:
            if round(m['feed_mm_min'],DECIMALS)<=0:raise ValueError('Avanço perde precisão no formato NC')
            row+=' F'+number(m['feed_mm_min'])
        if len(row)>79:raise ValueError('Linha excede o perfil GRBL de 79 caracteres')
        mapped.append(len(lines)+1);lines.append(row)
    if motion['final_position'][2]<motion['safe_z']-1e-8:raise ValueError('Percurso não termina em segurança')
    lines+=['M5','M2']
    return '\n'.join(lines)+'\n',mapped


def verify_readback(path,motion,line_map,spindle):
    summary,parsed=audit(path)
    actual={m.line:m for m in parsed}
    if len(parsed)!=len(motion['moves'])+2:raise ValueError('Quantidade de movimentos mudou na exportação')
    worst=0.;max_feed_error=0.;max_entry_angle=0.;ramp_count=0;plunge_count=0;max_plunge_depth=0.
    entry_limit=motion.get('entry_angle_limit_deg')
    if entry_limit is not None:positive(entry_limit,'entry_angle_limit_deg')
    for m,line in zip(motion['moves'],line_map,strict=True):
        p=actual[line]
        if None in p.start+p.end:raise ValueError('Estado inicial desconhecido após o posicionamento')
        error=max(math.dist(m['start'],p.start),math.dist(m['end'],p.end));worst=max(worst,error)
        rapid=m['kind'] in ('travel','retract','clearance_adjust')
        if p.mode!=(0 if rapid else 1) or error>COORD_ERROR:raise ValueError('Geometria/modo mudou na releitura do NC')
        if not rapid:
            feed_error=abs(p.feed-m['feed_mm_min']);max_feed_error=max(max_feed_error,feed_error)
            if feed_error>5.0001e-6 or abs(p.spindle-spindle)>5.0001e-6:
                raise ValueError('Avanço ou spindle mudou na releitura')
        if m['kind']=='ramp':
            ramp_count+=1
            angle=math.degrees(math.atan2(max(0,p.start[2]-p.end[2]),math.dist(p.start[:2],p.end[:2])))
            max_entry_angle=max(max_entry_angle,angle)
            if entry_limit is not None and angle>entry_limit+1e-7:
                raise ValueError('Ângulo da rampa excede o limite após arredondar o NC; recalcule os percursos')
        if m['kind']=='plunge':
            plunge_count+=1;max_plunge_depth=max(max_plunge_depth,p.start[2]-p.end[2])
    if summary['assumptions']:raise ValueError('Saída depende de modos não declarados')
    return {'status':'passed','mapped_motion_moves':len(line_map),'initial_positioning_moves':2,
        'maximum_coordinate_error_mm':worst,'maximum_feed_error_mm_min':max_feed_error,
        'maximum_entry_descent_angle_deg':max_entry_angle,'entry_angle_limit_deg':entry_limit,
        'maximum_ramp_descent_angle_deg':max_entry_angle,'ramp_moves_replayed':ramp_count,
        'center_plunge_moves_replayed':plunge_count,'maximum_center_plunge_depth_mm':max_plunge_depth,
        'coordinate_decimals':DECIMALS,'maximum_line_characters':max(map(len,Path(path).read_text(encoding='ascii').splitlines())),
        'summary':summary,'scope':'Modal G0/G1 readback against the calculated motion, not physical machine certification'}


def export_grbl(result,project_path,destination):
    motion,spindle,options=validate_calculation(result,project_path)
    program,line_map=render(motion,spindle,options.order)
    # Check in a temporary file first, so a rejected export never looks final.
    with TemporaryDirectory() as temporary:
        stage=Path(temporary)/'program.nc';stage.write_text(program,encoding='ascii')
        report=verify_readback(stage,motion,line_map,spindle)
    destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
    report_path=destination.with_suffix('.validacao.json')
    published={destination.resolve(),report_path.resolve()}
    if Path(project_path).resolve() in published:raise ValueError('Destino ou relatório não pode sobrescrever o projeto')
    source=(Path(project_path).resolve().parent/load_project(project_path)[0]['source']['path']).resolve()
    if source in published:raise ValueError('Destino ou relatório não pode sobrescrever o STL')
    destination.write_text(program,encoding='ascii')
    report.update({'file':destination.name,'sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),
        'order':options.sequence(),'spindle_rpm':spindle,'experimental':True})
    # Store compact summary: per-depth/run details remain in the reference audit.
    report['summary']={k:v for k,v in report['summary'].items() if k not in ('flat_feed_levels','raster_rows','feed_runs','comments','explicit_z_values')}
    write_json(report_path,report)
    return report
