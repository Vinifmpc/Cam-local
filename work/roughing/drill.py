"""Conservative vertical circular-hole machining for a flat centre-cutting mill.

Hole footprints are the *empty* loops of the complete projected material above
the requested floor.  This preserves floors and overhangs: a circle visible in
one waterline alone is never sufficient. The inscribed STL radius limits the
cutter unless bounded nominal-circle reconstruction is explicitly requested.
"""
from collections import Counter
import math
import numpy as np
from cam_tools import positive
from layer_regions import shadow_above
from region_core import signed_area

EPS=1e-8
MAX_SECTIONS=64
MAX_HOLES=500
MAX_MOVES=250000


def _mesh(triangles):
    mesh=np.asarray(triangles,float)
    if (mesh.ndim!=3 or mesh.shape[1:]!=(3,3) or not len(mesh)
            or len(mesh)>200000 or not np.isfinite(mesh).all()):
        raise ValueError('Drill: STL inválido ou acima do limite de 200.000 triângulos')
    return mesh


def _circle(path,tolerance):
    p=np.asarray(path,float)[:,:2]
    if len(p)>1 and np.linalg.norm(p[-1]-p[0])<EPS:p=p[:-1]
    if len(p)<12:return None
    # Centring before the solve avoids loss of precision for translated jobs.
    origin=p.mean(axis=0);q=p-origin
    matrix=np.column_stack((2*q[:,0],2*q[:,1],np.ones(len(q))))
    fit,_,rank,_=np.linalg.lstsq(matrix,np.einsum('ij,ij->i',q,q),rcond=None)
    if rank!=3:return None
    center=origin+fit[:2];radii=np.linalg.norm(p-center,axis=1)
    radius=float(np.mean(radii))
    if radius<=EPS or float(np.max(np.abs(radii-radius)))>tolerance:return None
    edges=np.roll(p,-1,axis=0)-p;length=np.linalg.norm(edges,axis=1)
    if np.any(length<=EPS):return None
    cross=edges[:,0]*(center[1]-p[:,1])-edges[:,1]*(center[0]-p[:,0])
    # Negative winding means the empty loop is on the right of every facet.
    if np.any(cross>=-EPS):return None
    edge_turn=edges[:,0]*np.roll(edges[:,1],-1)-edges[:,1]*np.roll(edges[:,0],-1)
    if np.any(edge_turn>EPS):return None
    safe=float(np.min(-cross/length))
    if radius-safe>tolerance:return None
    return {'center':center.tolist(),'diameter_mm':2*radius,
            'safe_diameter_mm':2*safe,'segments_xy':p.tolist()}


def _inside(point,polygon):
    """Inclusive containment for non-crossing loops of one Clipper union."""
    x,y=point;inside=False
    for a,b in zip(polygon,np.roll(polygon,-1,axis=0)):
        edge=b-a;relative=np.asarray(point)-a;length=float(np.linalg.norm(edge))
        if length>0:
            cross=float(edge[0]*relative[1]-edge[1]*relative[0]);dot=float(relative@edge)
            if abs(cross)<=EPS*length and -EPS*length<=dot<=length*length+EPS*length:
                return True
        if (a[1]>y)!=(b[1]>y):
            cross_x=a[0]+(y-a[1])*(b[0]-a[0])/(b[1]-a[1])
            if cross_x>x:inside=not inside
    return inside


def _nested_island(island,loop):
    # Clipper union contours do not cross, but can touch at vertices. Testing
    # just the first island vertex loses such tangencies and can miss a large
    # obstruction. Inclusive containment of every candidate vertex handles
    # tangencies and inscribed islands. The outer material contour has all
    # its vertices outside the hole, even though it surrounds the hole.
    low=np.min(loop,axis=0)-EPS;high=np.max(loop,axis=0)+EPS
    candidates=np.asarray(island)
    candidates=candidates[np.all((candidates>=low)&(candidates<=high),axis=1)]
    return any(_inside(point,loop) for point in candidates)


def detect_circular_holes(triangles,*,tolerance=.03):
    """Return bounded JSON data, including conservative skips and floor heights.

    Sampling levels selects candidates only.  Every accepted footprint is an
    exact Clipper union of *all* triangles above its floor, so sparse discovery
    cannot invent clearance.  Variable-radius openings sharing a centre are
    deliberately omitted rather than silently boring only a partial shape.
    """
    tolerance=positive(tolerance,'Drill: tolerância')
    if tolerance>1:raise ValueError('Drill: tolerância máxima de 1 mm')
    mesh=_mesh(triangles);heights=np.unique(mesh[:,:,2]);low=float(heights[0])
    top=float(heights[-1]);skipped=[];groups=[]
    if top-low<=EPS:return {'holes':[],'skipped':[{'reason':'STL sem altura de furação'}],
        'sections_checked':0,'section_limit_reached':False}
    levels=np.unique(np.concatenate((heights[:-1],(heights[:-1]+heights[1:])/2)))
    limited=len(levels)>MAX_SECTIONS
    if limited:levels=levels[np.unique(np.linspace(0,len(levels)-1,MAX_SECTIONS,dtype=int))]
    rejected=0
    for z in levels:
        # exclude_coplanar intentionally permits touching, but not crossing, a
        # blind floor exactly at z. Any material above it remains protected.
        shadow=shadow_above(mesh,float(z))
        positive_loops=[loop for loop in shadow if signed_area(loop)>0]
        for loop in shadow:
            if signed_area(loop)>=0:continue
            candidate=_circle(loop,tolerance)
            if candidate is None:rejected+=1;continue
            # A negative winding loop can enclose material islands. Its ring
            # alone does not prove an empty disk: reject every nested island.
            if any(_nested_island(island,loop) for island in positive_loops):
                rejected+=1;continue
            candidate['bottom_z']=float(z)
            above=heights[heights>z+EPS]
            candidate['opening_z']=float(above[0]) if len(above) else top
            group=next((g for g in groups if math.dist(g[0]['center'],candidate['center'])<=tolerance),None)
            if group is None:
                if len(groups)>=MAX_HOLES:raise ValueError('Drill: mais de 500 furos candidatos')
                groups.append([candidate])
            else:group.append(candidate)
    holes=[]
    # Through status needs a second, stronger certificate than merely reaching
    # the model's minimum Z: even a zero-thickness/nonmanifold horizontal floor
    # at that Z must block breakthrough. Build this whole projection once.
    bottom_shadow=shadow_above(mesh,low,include_coplanar=True)
    bottom_positive=[loop for loop in bottom_shadow if signed_area(loop)>0]
    through_circles=[]
    for loop in bottom_shadow:
        if signed_area(loop)>=0:continue
        circle=_circle(loop,tolerance)
        if circle is not None and not any(_nested_island(island,loop) for island in bottom_positive):
            through_circles.append(circle)
    for group in groups:
        nominal=[c['diameter_mm'] for c in group]
        if max(nominal)-min(nominal)>2*tolerance:
            skipped.append({'center':group[0]['center'],'reason':'Abertura com diâmetro variável; cilindro completo não confirmado'})
            continue
        # Minimum z means all the material above the whole hole was included.
        candidate=min(group,key=lambda c:c['bottom_z']).copy()
        candidate['opening_z']=max(c['opening_z'] for c in group)
        candidate['through']=candidate['bottom_z']<=low+EPS and any(
            math.dist(candidate['center'],circle['center'])+candidate['safe_diameter_mm']/2
                <=circle['safe_diameter_mm']/2+EPS
            and math.dist(candidate['center'],circle['center'])+candidate['diameter_mm']/2
                <=circle['diameter_mm']/2+EPS for circle in through_circles)
        if candidate['opening_z']-candidate['bottom_z']<=EPS:continue
        holes.append(candidate)
    holes.sort(key=lambda c:(c['center'][0],c['center'][1],c['bottom_z']))
    for index,hole in enumerate(holes):hole['id']=index
    if rejected:skipped.append({'reason':'Contornos internos sem circularidade/cilindro confirmados','section_contours':rejected})
    if limited:skipped.append({'reason':'Descoberta limitada a 64 alturas; outros furos podem não ser identificados'})
    return {'holes':holes,'skipped':skipped,'sections_checked':len(levels),'section_limit_reached':limited}


def _parameters(*,diameter,tool_length,stock_top,bottom,peck,tolerance,allow_helix,
                center_cutting,clearance,obstacle_top,entry_angle_deg,max_moves,compensate_facets=False,
                retract_mode='full',retract_mm=1.,rapid_reentry=True,reentry_gap=.25,fixture_travel=None):
    for value,key in ((diameter,'diâmetro'),(tool_length,'comprimento'),(peck,'passo vertical'),
                      (tolerance,'tolerância'),(clearance,'folga')):
        positive(value,'Drill: '+key)
    for value in (stock_top,bottom,obstacle_top):
        if value is not None and (isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value)):
            raise ValueError('Drill: altura inválida')
    if any(type(value) is not bool for value in (allow_helix,center_cutting,compensate_facets)):
        raise ValueError('Drill: opções de hélice e corte central precisam ser booleanas')
    if type(rapid_reentry) is not bool:raise ValueError('Drill: retorno rápido deve ser booleano')
    if retract_mode not in ('full','chip_break'):raise ValueError('Drill: modo de retração inválido')
    positive(retract_mm,'Drill: subida entre mergulhos');positive(reentry_gap,'Drill: folga de reentrada')
    if not center_cutting:raise ValueError('Drill: confirme que a fresa permite corte central/mergulho')
    positive(entry_angle_deg,'Drill: ângulo de hélice')
    if entry_angle_deg>=45:raise ValueError('Drill: ângulo de hélice precisa ser menor que 45 graus')
    if type(max_moves) is not int or not 1<=max_moves<=MAX_MOVES:
        raise ValueError('Drill: limite de movimentos inválido')
    return dict(diameter=float(diameter),tool_length=float(tool_length),stock_top=float(stock_top),
        bottom=None if bottom is None else float(bottom),peck=float(peck),tolerance=float(tolerance),
        allow_helix=allow_helix,center_cutting=center_cutting,compensate_facets=compensate_facets,clearance=float(clearance),
        obstacle_top=float(stock_top if obstacle_top is None else obstacle_top),
        entry_angle_deg=float(entry_angle_deg),max_moves=max_moves,retract_mode=retract_mode,
        retract_mm=float(retract_mm),rapid_reentry=rapid_reentry,reentry_gap=float(reentry_gap),
        **({'fixture_travel':fixture_travel} if fixture_travel is not None else {}))


def _compatibility(hole,*,diameter,tool_length,stock_top,bottom,tolerance,allow_helix,center_cutting,compensate_facets=False):
    target=hole['bottom_z'] if bottom is None else bottom
    reason=None
    if target<hole['bottom_z']-EPS and not hole['through']:reason='Z final ultrapassa o fundo do furo cego'
    if target>=hole['opening_z']-EPS:reason='Z final não alcança a abertura do furo'
    if stock_top-target>tool_length+EPS:reason='Profundidade excede o comprimento de corte da fresa'
    # Reconstruction is opt-in and bounded by the circle-fit tolerance. The
    # 1e-6 diameter epsilon handles float32 STL nominal dimensions only; it
    # never permits a tool oversize by the user-entered geometry tolerance.
    machining_diameter=hole['diameter_mm'] if compensate_facets else hole['safe_diameter_mm']
    fit_epsilon=1e-6 if compensate_facets else EPS
    if diameter>machining_diameter+fit_epsilon:
        reason=('Fresa maior que o diâmetro circular reconstruído' if compensate_facets
            else 'Fresa maior que o diâmetro livre mínimo do STL')
    matching=abs(hole['diameter_mm']-diameter)<=tolerance+EPS
    if not matching and not allow_helix and reason is None:reason='Furo maior que a fresa; habilite interpolação helicoidal'
    if not center_cutting and reason is None:reason='Confirme que a fresa permite corte central/mergulho'
    return {**hole,'target_z':float(target),'strategy':'plunge' if matching else 'helix',
        'method':'peck' if matching else 'helix','compatible':reason is None,'reason':reason,
        'basis':'fitted_circle' if compensate_facets else 'inscribed_stl',
        'fit_basis':'nominal' if compensate_facets else 'inscribed',
        'facet_allowance_mm':max(0.,(hole['diameter_mm']-hole['safe_diameter_mm'])/2) if compensate_facets else 0.,
        'machining_diameter_mm':machining_diameter}


def inspect_drill_compatibility(triangles,*,diameter,tool_length,stock_top,bottom=None,
                                tolerance=.03,allow_helix=False,center_cutting=False,compensate_facets=False):
    """Read-only tool comparison; an unchecked option returns reasons, not errors."""
    positive(diameter,'Drill: diâmetro');positive(tool_length,'Drill: comprimento')
    for value in (stock_top,bottom):
        if value is not None and (isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value)):
            raise ValueError('Drill: altura inválida')
    if any(type(value) is not bool for value in (allow_helix,center_cutting,compensate_facets)):
        raise ValueError('Drill: opções precisam ser booleanas')
    discovery=detect_circular_holes(triangles,tolerance=tolerance)
    holes=[_compatibility(h,diameter=diameter,tool_length=tool_length,stock_top=stock_top,
        bottom=bottom,tolerance=tolerance,allow_helix=allow_helix,center_cutting=center_cutting,
        compensate_facets=compensate_facets) for h in discovery['holes']]
    return {**discovery,'holes':holes,'detected_count':len(holes),
        'eligible_count':sum(h['compatible'] for h in holes),
        'tool':{'diameter_mm':diameter,'cutting_length_mm':tool_length}}


def _build(triangles,p,initial_position):
    mesh=_mesh(triangles);mesh_top=float(mesh[:,:,2].max())
    if p['stock_top']<mesh_top-EPS:raise ValueError('Drill: topo do bruto abaixo do STL')
    discovery=detect_circular_holes(mesh,tolerance=p['tolerance']);holes=[];skipped=list(discovery['skipped'])
    radius=p['diameter']/2
    for hole in discovery['holes']:
        record=_compatibility(hole,**{k:p[k] for k in ('diameter','tool_length','stock_top','bottom',
            'tolerance','allow_helix','center_cutting','compensate_facets')});target=record['target_z'];reason=record['reason']
        if reason:
            skipped.append({'hole_id':hole['id'],'center':hole['center'],'diameter_mm':hole['diameter_mm'],
                'safe_diameter_mm':hole['safe_diameter_mm'],'reason':reason});continue
        for k in ('reason','method','compatible'):record.pop(k)
        holes.append(record)
    if not holes:
        reasons='; '.join(dict.fromkeys(s['reason'] for s in skipped)) or 'Nenhum furo circular vertical confirmado no STL'
        raise ValueError('Drill: nenhum furo compatível. '+reasons)
    safe_z=max(p['stock_top'],p['obstacle_top'],mesh_top)+p['clearance']
    first=holes[0]['center'];initial=[*first,safe_z] if initial_position is None else list(initial_position)
    if (len(initial)!=3 or not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in initial)
            or initial[2]<safe_z-EPS):raise ValueError('Drill: posição inicial precisa estar no plano de segurança')
    current=initial.copy();moves=[];entries=[];layers=[]
    from fixture_travel import FixtureTravel
    fixture_route=FixtureTravel(p.get('fixture_travel'))
    def emit(kind,end,hole,**proof):
        nonlocal current
        end=[float(v) for v in end]
        if math.dist(current,end)<=EPS:return
        if len(moves)>=p['max_moves']:raise ValueError('Drill: cálculo excedeu o limite de movimentos')
        destinations=fixture_route.route(current,end)[1:] if kind=='travel' else [end]
        for destination in destinations:
            moves.append({'id':len(moves),'kind':kind,'start':current.copy(),'end':list(destination),
                'layer':None,'polyline':None,'proof':{'hole_id':hole['id'],**proof,
                **({'fixture_detour':True} if len(destinations)>1 else {})}});current=list(destination)
    for hole in holes:
        center=hole['center'];target=hole['target_z'];points=[];start_index=len(moves)
        if current[2]>safe_z+EPS:emit('clearance_adjust',[*current[:2],safe_z],hole)
        emit('travel',[*center,safe_z],hole)
        emit('approach',[*center,p['stock_top']],hole)
        if hole['strategy']=='plunge':
            count=max(1,math.ceil((p['stock_top']-target)/p['peck']))
            if count*3>p['max_moves']:raise ValueError('Drill: número excessivo de pecks')
            prior=p['stock_top']
            for index in range(count):
                end_z=p['stock_top']+(target-p['stock_top'])*(index+1)/count
                emit('cut',[*center,end_z],hole,peck=index,maximum_new_depth_mm=prior-end_z)
                points.extend([moves[-1]['start'],moves[-1]['end']])
                last=index+1==count
                retract_z=(safe_z if last or p['retract_mode']=='full'
                           else min(safe_z,end_z+p['retract_mm']))
                emit('retract',[*center,retract_z],hole)
                if not last:
                    # Only this hole's completed peck proves the empty prism.
                    # Stop the rapid above its floor and feed the last gap;
                    # no rapid enters the next uncut depth. XY stays fixed.
                    if p['rapid_reentry']:
                        emit('travel',[*center,min(retract_z,end_z+p['reentry_gap'])],hole,
                             drill_phase='cleared_reentry',cleared_to_z=end_z,
                             reentry_gap_mm=p['reentry_gap'])
                    emit('approach',[*center,end_z],hole,cleared_to_z=end_z)
                prior=end_z
        else:
            # A tiny guard absorbs float/NC quantisation. The circle stays in
            # the inradius of every facet of the certified empty prism.
            max_r=hole['machining_diameter_mm']/2-radius-1e-5
            if max_r<=EPS:raise ValueError('Drill: hélice sem folga radial confirmada')
            inner=min(max_r,radius*.5)
            # Inner helix always overlaps the centre; following concentric
            # rings overlap by at least 75% of the cutter diameter.
            radial_count=max(1,math.ceil(max_r/(radius*.5)))
            radii=np.linspace(max_r/radial_count,max_r,radial_count).tolist();inner=radii[0]
            per_turn=max(32,min(4096,math.ceil(math.pi/math.acos(max(-1,min(1,1-p['tolerance']/max(max_r,EPS)))))))
            perimeter=2*per_turn*inner*math.sin(math.pi/per_turn)
            pitch=min(p['peck'],perimeter*math.tan(math.radians(p['entry_angle_deg'])))
            depth_count=max(1,math.ceil((p['stock_top']-target)/pitch))
            predicted=depth_count*(per_turn*(1+radial_count)+radial_count+2)
            if predicted>p['max_moves']:raise ValueError('Drill: hélice excede o limite de movimentos; reveja passo/tolerância')
            prior=p['stock_top']
            def circle(r,z0,z1):
                for vertex in range(1,per_turn+1):
                    angle=2*math.pi*vertex/per_turn
                    emit('cut',[center[0]+r*math.cos(angle),center[1]+r*math.sin(angle),
                        z0+(z1-z0)*vertex/per_turn],hole,strategy='helix')
            for index in range(depth_count):
                end_z=p['stock_top']+(target-p['stock_top'])*(index+1)/depth_count
                emit('cut',[center[0]+inner,center[1],prior],hole,strategy='cleared_disk_entry')
                circle(inner,prior,end_z)
                # One level circle removes the helical floor cusp.
                circle(inner,end_z,end_z)
                for r in radii[1:]:
                    emit('cut',[center[0]+r,center[1],end_z],hole,strategy='overlapping_radial_step')
                    circle(r,end_z,end_z)
                emit('cut',[*center,end_z],hole,strategy='cleared_disk_return')
                prior=end_z
            points=[m['start'] for m in moves[start_index:] if m['kind']=='cut']
            points.append(current.copy());emit('retract',[*center,safe_z],hole)
        entries.append({'hole':hole['id'],'strategy':hole['strategy'],'peak':[*center,p['stock_top']],
            'entry_start_z':p['stock_top'],'target_z':target,'move_start':start_index,'move_end':len(moves)})
        layers.append({'z':target,'hole_id':hole['id'],'polylines':[{'points':points}]})
    job={'schema_version':1,'units':'mm','scope':'circular_drill','tool':{
        'type':'flat_cylindrical','diameter':p['diameter'],'length':p['tool_length']},
        'parameters':{**p,'z_top':p['stock_top'],'z_bottom':min(h['target_z'] for h in holes),'stepdown':p['peck']},
        'holes':holes,'detected_holes':discovery['holes'],'skipped_holes':skipped,
        'layers':layers,'cutting_edges':sum(m['kind']=='cut' for m in moves),
        'discovery':{k:v for k,v in discovery.items() if k not in ('holes','skipped')}}
    plan={'schema_version':1,'units':'mm','scope':'circular_drill','tool':{
        'diameter':p['diameter'],'length':p['tool_length']},'stock_top':p['stock_top'],
        'obstacle_top':p['obstacle_top'],'safe_z':safe_z,'parameters':p.copy(),
        'initial_position':initial,'required_initial_position':initial_position is None,
        'final_position':current,'moves':moves,'entries':entries,
        'source_cutting_edges':job['cutting_edges'],'move_counts':dict(Counter(m['kind'] for m in moves)),
        'length_mm':{k:sum(math.dist(m['start'],m['end']) for m in moves if m['kind']==k) for k in {m['kind'] for m in moves}}}
    return job,plan


def generate_drill(triangles,*,diameter,tool_length,stock_top,bottom=None,peck=1.,tolerance=.03,
                   allow_helix=False,center_cutting=False,clearance=2.54,obstacle_top=None,
                   initial_position=None,entry_angle_deg=3.,max_moves=MAX_MOVES,progress=None,compensate_facets=False,
                   retract_mode='full',retract_mm=1.,rapid_reentry=True,reentry_gap=.25,fixture_travel=None):
    if progress:progress('Identificando furos circulares e pisos protegidos',0)
    p=_parameters(diameter=diameter,tool_length=tool_length,stock_top=stock_top,bottom=bottom,
        peck=peck,tolerance=tolerance,allow_helix=allow_helix,center_cutting=center_cutting,
        clearance=clearance,obstacle_top=obstacle_top,entry_angle_deg=entry_angle_deg,max_moves=max_moves,
        compensate_facets=compensate_facets,retract_mode=retract_mode,retract_mm=retract_mm,
        rapid_reentry=rapid_reentry,reentry_gap=reentry_gap,fixture_travel=fixture_travel)
    job,plan=_build(triangles,p,initial_position)
    if progress:progress('Conferindo diâmetros, profundidades e movimentos Drill',.8)
    plan['validation']=validate_drill_motion(plan,job,triangles)
    if progress:progress('Furação conferida',1)
    return job,plan


def validate_drill_motion(plan,job,triangles):
    """Rebuild from the original mesh and replay immutable geometry/provenance.

    This separate export-time guard re-detects floors and empty prisms; neither
    reported validation flags nor a caller-supplied hole list are trusted.
    """
    try:
        p=_parameters(**{k:job['parameters'][k] for k in (
            'diameter','tool_length','stock_top','bottom','peck','tolerance','allow_helix',
            'center_cutting','clearance','obstacle_top','entry_angle_deg','max_moves','compensate_facets',
            'retract_mode','retract_mm','rapid_reentry','reentry_gap')},fixture_travel=job['parameters'].get('fixture_travel'))
        expected_job,expected=_build(triangles,p,plan['initial_position'])
        if job!=expected_job:raise ValueError('Drill: geometria fonte, furos ou ferramenta mudaram')
        for key in ('tool','stock_top','obstacle_top','safe_z','parameters','initial_position','final_position','entries'):
            if plan.get(key)!=expected.get(key):raise ValueError('Drill: parâmetros/posição divergentes dos movimentos reconstruídos')
        actual=plan['moves']
        if len(actual)!=len(expected['moves']):raise ValueError('Drill: movimentos ausentes ou duplicados')
        for a,b in zip(actual,expected['moves']):
            for key in ('id','kind','start','end','layer','polyline','proof'):
                if a.get(key)!=b.get(key):raise ValueError('Drill: movimento alterado ou sem prova de cilindro/peck')
    except (KeyError,TypeError) as e:raise ValueError('Drill: resultado incompleto ou inválido') from e
    return {'status':'passed','moves_replayed':len(actual),'source_edges_preserved':expected_job['cutting_edges'],
        'holes_verified':len(expected_job['holes']),'safe_prisms_verified':len(expected_job['holes']),
        'scope':'Original STL empty-prism reconstruction, bounded optional circle fitting, cutter fit, bounded pecks/helix, exact move replay and safe-plane continuity'}
