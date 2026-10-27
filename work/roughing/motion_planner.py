"""Experimental entry ramps and conservative links for the STL roughing core.

Assumes flat cylindrical cutting volume and a bounded stock top. Ramps stay
on the source cutting footprint; inter-region travel uses a clearance plane.
Previously completed cutting tracks prove only same-XY vertical reentry.
No general stock simulation, feed selection or G-code emission is provided.
"""
from collections import Counter
import hashlib
import math
import struct
import numpy as np
from cleared_area import ClearedArea
from track_index import CutTrackIndex,overlapping

EPS=1e-8
NC_COORD_DECIMALS=5


class MotionPlanningError(ValueError):
    pass


def _close(a,b):return math.dist(a,b)<=EPS
def _xy_key(p):return (p[0],p[1])


def _ramp_end_z(start,xy,target_z,angle_deg):
    """Bound slope both before and after the NC coordinate rounding.

    STL/Clipper edges may be only micrometres long, at a large absolute Z.
    Subtracting tan(angle)*length can round the real descent upward. A second
    failure is a small real descent crossing an NC Z rounding boundary while
    its XY rounds to a shorter (or zero-length) move. Choose a shallower real
    endpoint instead of relaxing either angle certificate.
    """
    post=lambda value:float(f'{value:.{NC_COORD_DECIMALS}f}')
    real_length=math.dist(start[:2],xy)
    post_length=math.dist([post(v) for v in start[:2]],[post(v) for v in xy])
    post_start=post(start[2]);tangent=math.tan(math.radians(angle_deg))
    def valid(z):
        return (math.degrees(math.atan2(max(0,start[2]-z),real_length))<=angle_deg
            and math.degrees(math.atan2(max(0,post_start-post(z)),post_length))<=angle_deg)
    if valid(target_z):return target_z
    z=max(target_z,start[2]-tangent*real_length)
    # Integer NC levels below this ceiling would exceed the angle at the
    # rounded XY. Staying strictly above its lower rounding boundary also
    # handles round-to-even ties without depending on their parity.
    scale=10**NC_COORD_DECIMALS
    lowest_post=math.ceil((post_start-tangent*post_length)*scale)/scale
    rounding_boundary=math.nextafter(lowest_post-.5/scale,math.inf)
    z=min(start[2],max(z,rounding_boundary))
    for _ in range(8):
        if valid(z):return z
        z=math.nextafter(z,math.inf)
        if z>=start[2]:return start[2]
    # No representable descending point met both limits; traverse this source
    # edge at the current height and use the next edge for the descent.
    return start[2]


def _height_on_track(point,a,b):
    dx=b[0]-a[0];dy=b[1]-a[1];squared=dx*dx+dy*dy
    if squared<=0:return None
    t=((point[0]-a[0])*dx+(point[1]-a[1])*dy)/squared
    if t<0 or t>1 or math.hypot(point[0]-a[0]-t*dx,point[1]-a[1]-t*dy)>EPS:
        return None
    return a[2]+t*(b[2]-a[2])


def _track_depth_supported(a,b,previous,top,step):
    """Cover a new straight XY span by previously cut collinear intervals.

    Linear tip heights are bounded at both ends of each accepted interval.
    Gaps and tracks at a different XY are never treated as cleared material.
    """
    if top-min(a[2],b[2])<=step+EPS:return True
    dx=b[0]-a[0];dy=b[1]-a[1];squared=dx*dx+dy*dy
    intervals=[]
    def add_interval(lo,hi,g0,g1):
        # g = old floor - new floor - maximum step; require g <= 0.
        if g0>EPS and g1>EPS:return
        if g0>EPS:lo=lo+(hi-lo)*(g0-EPS)/(g0-g1)
        elif g1>EPS:hi=lo+(hi-lo)*(EPS-g0)/(g1-g0)
        if hi>=lo:intervals.append((lo,hi))
    add_interval(0,1,top-a[2]-step,top-b[2]-step)
    for c,e in overlapping(previous,a,b,reverse=True):
        cx=c[0]-a[0];cy=c[1]-a[1];ex=e[0]-a[0];ey=e[1]-a[1]
        tc=(cx*dx+cy*dy)/squared;te=(ex*dx+ey*dy)/squared
        if abs(te-tc)<1e-15:continue
        if math.hypot(cx-tc*dx,cy-tc*dy)>EPS or math.hypot(ex-te*dx,ey-te*dy)>EPS:continue
        lo=max(0,min(tc,te));hi=min(1,max(tc,te))
        if hi<lo:continue
        def gap(t):
            old=c[2]+(t-tc)/(te-tc)*(e[2]-c[2])
            return old-(a[2]+t*(b[2]-a[2]))-step
        g0=gap(lo);g1=gap(hi)
        if lo==0 and hi==1 and max(g0,g1)<=EPS:return True
        add_interval(lo,hi,g0,g1)
    covered=0.0
    for lo,hi in sorted(intervals):
        if lo>covered+EPS/max(1,math.sqrt(squared)):return False
        covered=max(covered,hi)
        if covered>=1:return True
    return False


def _branches(points):
    peak=max(range(len(points)),key=lambda i:points[i][2])
    branches=[]
    if peak<len(points)-1:
        branches.append((points[peak:],[i for i in range(peak,len(points)-1)]))
    if peak>0:
        branches.append((points[:peak+1][::-1],[i for i in range(peak-1,-1,-1)]))
    branches.sort(key=lambda branch:sum(math.dist(a[:2],b[:2])
                  for a,b in zip(branch[0],branch[0][1:])),reverse=True)
    return points[peak],branches


def _cleared_link_supported(a,b,completed,area):
    if abs(a[2]-b[2])>EPS:return False
    if math.dist(a[:2],b[:2])<=EPS:
        if any((height:=_height_on_track(a,c,e)) is not None and height<=a[2]+EPS for c,e in overlapping(completed,a,a)):return True
    # Infinite stock top disables the uniform-top shortcut. Even a link at
    # stock Z=0 must have a real XY footprint proof when fixtures stand above it.
    elif _track_depth_supported(a,b,completed,math.inf,0):return True
    return area.covers(a,b,a[2],require_cut=True)


class PriorCutState:
    """Only completed cutting moves of one independently validated operation.

    Exact same-tool tracks can prove identical swept paths without the
    polygon approximation guard. Other XY paths need the guarded full-area
    proof. Travel, ramps and unexecuted source paths are never credited.
    """
    def __init__(self,motion,tool,stock_top):
        if motion.get('validation',{}).get('status')!='passed':
            raise MotionPlanningError('O desbaste anterior precisa estar validado antes de reutilizar o material removido')
        previous=motion.get('tool',{})
        if any(not math.isfinite(previous.get(key,math.nan)) or
               abs(previous[key]-tool[key])>EPS for key in ('diameter','length')):
            raise MotionPlanningError('Reutilização do desbaste exige a mesma fresa; recalcule com a ferramenta atual')
        if abs(motion.get('stock_top',math.inf)-stock_top)>EPS:
            raise MotionPlanningError('Topo do bruto mudou desde o desbaste anterior')
        self.cuts=[];self.tracks=CutTrackIndex(tool['diameter'])
        self.area=ClearedArea(tool['diameter'],stock_top);self.visited={}
        digest=hashlib.sha256(struct.pack('<3d',tool['diameter'],tool['length'],stock_top))
        position=motion.get('initial_position')
        if not position or len(position)!=3 or not all(math.isfinite(v) for v in position):
            raise MotionPlanningError('Estado inicial do desbaste anterior inválido')
        for index,move in enumerate(motion.get('moves',[])):
            a,b=move.get('start',[]),move.get('end',[])
            if (move.get('id')!=index or len(a)!=3 or len(b)!=3
                    or not all(math.isfinite(v) for v in a+b) or not _close(a,position)):
                raise MotionPlanningError('Movimentos do desbaste anterior inválidos')
            position=b
            if move['kind']!='cut':continue
            if max(a[2],b[2])>stock_top+EPS or math.dist(a[:2],b[:2])<=EPS:
                raise MotionPlanningError('Corte anterior fora do bruto ou sem comprimento XY')
            digest.update(struct.pack('<q6d',index,*a,*b))
            self.cuts.append((a,b,index));self.tracks.append((a,b));self.area.add(a,b)
            for point in (a,b):
                old=self.visited.get(_xy_key(point))
                if old is None or point[2]<old['z']:
                    self.visited[_xy_key(point)]={'z':point[2],'move':-index-1}
        if not _close(position,motion.get('final_position',[math.inf]*3)):
            raise MotionPlanningError('Estado final do desbaste anterior incompatível')
        self.cut_count=len(self.cuts);self.fingerprint=digest.hexdigest()

    def covers_edge(self,a,b):
        if _track_depth_supported(a,b,self.tracks,math.inf,0):return True
        return self.area.covers(a,b,min(a[2],b[2]),require_cut=True)


def build_prior_cut_state(prior_motion,tool,stock_top):
    return PriorCutState(prior_motion,tool,stock_top)


def _entry_cut_proof(saved):
    move=saved['move'] if saved else None
    if move is not None and move<0:return {'source_cut_move':None,'source_prior_cut_move':-move-1}
    return {'source_cut_move':move}


def plan_ramps_and_links(job,triangles,*,entry_angle_deg=3.0,clearance=2.54,
                        approach_gap=.25,stock_top=None,obstacle_top=None,
                        initial_position=None,max_ramp_passes=500,path_order='layer',progress=None,
                        prior_motion=None,allow_center_plunge=False):
    """Connect source cuts without inventing unproven low traverses.

    Stock is assumed bounded above by stock_top. obstacle_top bounds any
    protected fixtures/material crossed in air; defaults to the stock top.
    If initial_position is omitted, the result declares its required initial
    position above the first entry. It does not position a real machine.
    """
    if progress:progress('Conferindo passadas para rampas e ligações',0)
    mesh=np.asarray(triangles,float)
    if path_order not in ('layer','region_first'):raise MotionPlanningError('Invalid roughing path order')
    if type(allow_center_plunge) is not bool:raise MotionPlanningError('Invalid center-cutting capability')
    if mesh.ndim!=3 or mesh.shape[1:]!=(3,3) or not len(mesh) or not np.isfinite(mesh).all():
        raise MotionPlanningError('Invalid mesh')
    top=job['parameters']['z_top'] if stock_top is None else stock_top
    fixture_top=top if obstacle_top is None else obstacle_top
    stepdown=job['parameters']['stepdown']
    if not all(math.isfinite(x) for x in (top,fixture_top,entry_angle_deg,clearance,approach_gap,stepdown)):
        raise MotionPlanningError('Non-finite motion parameter')
    if not 0<entry_angle_deg<90 or clearance<=0 or not 0<=approach_gap<=clearance or stepdown<=0:
        raise MotionPlanningError('Invalid angle, clearance, gap or stepdown')
    if not isinstance(max_ramp_passes,int) or max_ramp_passes<1:
        raise MotionPlanningError('Invalid ramp pass limit')
    mesh_top=float(mesh[:,:,2].max())
    if top<mesh_top-EPS:
        raise MotionPlanningError('stock_top must bound the final mesh top')
    safe_z=max(top,fixture_top,mesh_top)+clearance
    source_paths=[]
    for li,layer in enumerate(job['layers']):
        for pi,poly in enumerate(layer['polylines']):
            pts=np.asarray(poly['points'],float)
            if pts.ndim!=2 or pts.shape[1]!=3 or len(pts)<2 or not np.isfinite(pts).all():
                raise MotionPlanningError('Invalid source polyline')
            if np.any(np.linalg.norm(np.diff(pts[:,:2],axis=0),axis=1)<=1e-12):
                raise MotionPlanningError('Source cutting edges require nonzero XY length')
            if np.any(np.linalg.norm(np.diff(pts,axis=0),axis=1)<=EPS):
                raise MotionPlanningError('Source cutting edges require length above motion resolution')
            if np.any(pts[:,2]>top+EPS):
                raise MotionPlanningError('Source cut above declared stock top')
            source_paths.append((li,pi,pts.tolist()))
    if progress:progress('Ordenando regiões e passadas',.05)
    region_map={};schedule={'region_count':0,'visit_order':[],'regions':[]}
    if path_order=='region_first':
        from region_order import region_first
        source_paths,region_map,schedule=region_first(source_paths,job['tool']['diameter'],
            None if initial_position is None else initial_position[:2])
    tool_length=job['tool']['length']
    if not math.isfinite(tool_length) or tool_length<=0:
        raise MotionPlanningError('Invalid cylindrical cutting length')
    if any(top-min(p[2] for p in pts)>tool_length+EPS for _,_,pts in source_paths):
        raise MotionPlanningError('Stock column exceeds the declared cutting length')
    if initial_position is None:
        first=_branches(source_paths[0][2])[0] if source_paths else [0,0,0]
        initial=[first[0],first[1],safe_z]
    else:
        initial=list(initial_position)
    if len(initial)!=3 or not all(math.isfinite(x) for x in initial) or initial[2]<safe_z-EPS:
        raise MotionPlanningError('Initial position must already be at or above the clearance plane')
    current=initial.copy();moves=[];entries=[];visited={};previous_region=None
    completed=CutTrackIndex(job['tool']['diameter'])
    cleared_tracks=CutTrackIndex(job['tool']['diameter'])
    cleared_area=ClearedArea(job['tool']['diameter'],top)
    prior_state=None
    if prior_motion is not None:
        if not _close(initial,prior_motion.get('final_position',[math.inf]*3)):
            raise MotionPlanningError('Cutout precisa começar na posição final do desbaste anterior')
        prior_state=build_prior_cut_state(prior_motion,job['tool'],top)
        visited=prior_state.visited.copy();cleared_tracks=prior_state.tracks;cleared_area=prior_state.area
        for a,b,move_id in prior_state.cuts:completed.append((a,b,-move_id-1))
    tangent=math.tan(math.radians(entry_angle_deg))

    def emit(kind,end,context=None,**proof):
        nonlocal current
        end=list(end)
        # A sub-resolution move must not silently change the planner position:
        # that would leave an unrepresented displacement between emitted moves.
        if current==end:return None
        record={'id':len(moves),'kind':kind,'start':current.copy(),'end':end,
                **(context or {}),'proof':proof}
        moves.append(record);current=end
        if len(moves)>1_000_000:raise MotionPlanningError('Motion count limit exceeded')
        return record['id']

    def ramp(arm,edge_ids,start_z,target_z,context):
        if start_z<=target_z+EPS:return 0
        length=sum(math.dist(a[:2],b[:2]) for a,b in zip(arm,arm[1:]))
        needed=math.ceil((start_z-target_z)/(tangent*length))
        if needed>max_ramp_passes:
            if allow_center_plunge:
                emit('plunge',[*arm[0][:2],target_z],context,source_edge=edge_ids[0],
                     target_z=target_z,center_cutting_required=True)
                return 0
            if job.get('automatic_regions') is not None:
                raise MotionPlanningError('Região sem espaço para rampa: confirme o corte pelo centro '
                    'da ferramenta para permitir entrada vertical ou utilize uma fresa menor.')
            raise MotionPlanningError(f'Ramp exceeds {max_ramp_passes} passes at {context}')
        z=start_z;forward=True
        for pass_index in range(max_ramp_passes):
            indices=range(len(arm)-1) if forward else range(len(arm)-2,-1,-1)
            for k in indices:
                a,b=(arm[k],arm[k+1]) if forward else (arm[k+1],arm[k])
                length=math.dist(a[:2],b[:2])
                z=_ramp_end_z(current,b[:2],target_z,entry_angle_deg)
                emit('ramp',[*b[:2],z],context,source_edge=edge_ids[k],target_z=target_z)
                if z==target_z:
                    # Feed back at the entry level along the same source arm.
                    emit('ramp_return',[*arm[k][:2],target_z],context,source_edge=edge_ids[k],target_z=target_z)
                    for j in range(k-1,-1,-1):
                        emit('ramp_return',[*arm[j][:2],target_z],context,source_edge=edge_ids[j],target_z=target_z)
                    return pass_index+1
            forward=not forward
        raise MotionPlanningError('Ramp did not reach its target within the angle and NC coordinate resolution')

    if source_paths and current[2]>safe_z+EPS:
        emit('clearance_adjust',[*current[:2],safe_z],above_bound=max(top,fixture_top,mesh_top))
    if progress:progress('Planejando rampas e ligações',.10)
    report_every=max(1,len(source_paths)//200)
    for path_index,(li,pi,points) in enumerate(source_paths):
        region=region_map.get((li,pi))
        context={'layer':li,'polyline':pi,**({'region':region} if region is not None else {})}
        peak,branches=_branches(points)
        saved=visited.get(_xy_key(peak))
        # An old endpoint cache can also become stale: a later/deeper cut
        # may cross that XY in its interior without adding a vertex there.
        # If the cache cannot justify this entry's depth, find the deepest
        # actual completed track, just as independent replay does below.
        # Only prior cuts are inspected; future/source paths prove nothing.
        if prior_state is not None or saved is None or min(top,saved['z'])-peak[2]>stepdown+EPS:
            for old_a,old_b,move_id in completed.overlapping(peak,peak):
                height=_height_on_track(peak,old_a,old_b)
                if height is not None and (saved is None or height<saved['z']):
                    saved={'z':height,'move':move_id}
        cleared=min(top,saved['z']) if saved else top
        if cleared-peak[2]>stepdown+EPS and cleared_area.covers(peak,peak,peak[2]+stepdown):
            cleared=peak[2]+stepdown
        # A clipped raster can be shorter than a viable ramp although an
        # earlier cleanup already swept its entry. Prove the complete tool
        # footprint at the target depth before asking for a cutting entry.
        # This uses completed cuts only, with the same guarded area proof
        # independently replayed for approach/cleared_feed below.
        ramp_length=sum(math.dist(a[:2],b[:2]) for a,b in zip(branches[0][0],branches[0][0][1:]))
        if (cleared>peak[2]+EPS and (cleared-peak[2])/(tangent*ramp_length)>max_ramp_passes
                and cleared_area.covers(peak,peak,peak[2],require_cut=True)):
            cleared=peak[2]
        entry_floor=max(cleared,peak[2])
        if entry_floor-peak[2]>stepdown+EPS:
            raise MotionPlanningError(f'Entry needs more than one stepdown without prior clearance at {context}')
        height=max(current[2],entry_floor)
        start=[*current[:2],height];end=[*peak[:2],height]
        stay_down=(((path_order=='region_first' and previous_region==region) or prior_state is not None) and height<safe_z-EPS
            and _cleared_link_supported(start,end,cleared_tracks,cleared_area))
        if stay_down and job.get('automatic_regions') is not None:
            from smart_planner import edge_in_automatic_domain
            stay_down=edge_in_automatic_domain(start,end,job['automatic_regions'],top)
        if stay_down:
            emit('approach',start,context,cleared_floor=current[2])
            emit('link_cleared',end,context,clearance='completed_cut_footprints_only')
        else:
            if current[2]<safe_z-EPS:
                emit('retract',[*current[:2],safe_z],context,above_bound=max(top,fixture_top,mesh_top))
            emit('travel',[peak[0],peak[1],safe_z],context,clearance_plane=safe_z)
            emit('approach',[peak[0],peak[1],entry_floor+approach_gap],context,
                 cleared_floor=cleared,**_entry_cut_proof(saved))
        emit('cleared_feed',[peak[0],peak[1],entry_floor],context,
             cleared_floor=cleared,**_entry_cut_proof(saved))
        passes=ramp(*branches[0],entry_floor,peak[2],context)
        entries.append({**context,'peak':peak,'cleared_floor':cleared,
                        **({'uses_prior_roughing':bool(saved and saved['move']<0)} if prior_state is not None else {}),
                        'entry_start_z':entry_floor,'ramp_passes':passes,'stay_down':stay_down,
                        **({'center_plunge':True} if moves and moves[-1]['kind']=='plunge' else {})})
        for bi,(arm,edge_ids) in enumerate(branches):
            cut_ids=[]
            for end,edge_id in zip(arm[1:],edge_ids,strict=True):
                move_id=emit('cut',end,context,source_edge=edge_id)
                cut_ids.append(move_id)
                move=moves[move_id]
                completed.append((move['start'],move['end'],move_id))
                cleared_tracks.append((move['start'],move['end']))
                cleared_area.add(move['start'],move['end'])
                for vertex in (move['start'],move['end']):
                    old=visited.get(_xy_key(vertex))
                    if old is None or vertex[2]<old['z']:
                        visited[_xy_key(vertex)]={'z':vertex[2],'move':move_id}
            if bi<len(branches)-1:
                for move_id in reversed(cut_ids):
                    emit('link_backtrack',moves[move_id]['start'],context,source_cut_move=move_id)
        previous_region=region
        if progress and ((path_index+1)%report_every==0 or path_index+1==len(source_paths)):
            progress(f'Rampas e ligações: passada {path_index+1}/{len(source_paths)}',
                     .10+.62*(path_index+1)/len(source_paths))
    if source_paths and current[2]<safe_z-EPS:
        emit('retract',[*current[:2],safe_z],above_bound=max(top,fixture_top,mesh_top))
    result={'schema_version':1,'scope':'experimental_ramps_and_provenance_links',
        'tool':{'diameter':job['tool']['diameter'],'length':tool_length},
        'units':'mm','initial_position':initial,'required_initial_position':initial_position is None,
        'final_position':current,'stock_top':top,'obstacle_top':fixture_top,'safe_z':safe_z,
        'parameters':{'entry_angle_deg':entry_angle_deg,'clearance':clearance,
          'approach_gap':approach_gap,'max_ramp_passes':max_ramp_passes},
        'path_order':path_order,'region_schedule':schedule,
        'stay_down_entries':sum(e['stay_down'] for e in entries),
        'source_cutting_edges':sum(len(p)-1 for _,_,p in source_paths),
        'move_counts':dict(Counter(m['kind'] for m in moves)),
        'length_mm':dict((kind,sum(math.dist(m['start'],m['end']) for m in moves if m['kind']==kind))
                         for kind in sorted({m['kind'] for m in moves})),
        'entries':entries,'moves':moves,
        'limitations':['Bounded stock top and flat cylindrical cutting volume assumed',
          'Completed tracks or guarded cleared XY areas prove reentry; no general stock-volume simulator',
          'Inter-region travel is above bounded obstacles; low links only retrace actual cuts',
          'No holder/machine collision, feed/spindle selection or G-code certification',
          'Not a reconstruction of MeshCAM helix or exact linking algorithm']}
    result['parameters']['allow_center_plunge']=allow_center_plunge
    result['center_plunge_entries']=sum(e.get('center_plunge',False) for e in entries)
    if prior_state is not None:
        result['prior_roughing']={'cut_moves':prior_state.cut_count,'sha256':prior_state.fingerprint}
        result['prior_reused_entries']=sum(e['uses_prior_roughing'] for e in entries)
    if progress:progress('Revisando os movimentos calculados',.75)
    result['validation']=validate_motion(result,job,
        progress=(lambda phase,fraction:progress(phase,.75+.25*fraction)) if progress else None,
        prior_motion=prior_motion)
    if progress:progress('Rampas, ligações e movimentos conferidos',1)
    return result


def validate_motion(plan,source,*,progress=None,prior_motion=None):
    """Replay independently: continuity, cut preservation and every link proof."""
    if progress:progress('Revisando os movimentos calculados',0)
    if plan.get('tool') is not None and any(plan['tool'].get(key)!=source['tool'][key]
                                           for key in ('diameter','length')):
        raise MotionPlanningError('Ferramenta dos movimentos difere da ferramenta dos percursos fonte')
    minimum_plane=max(plan['stock_top'],plan['obstacle_top'])+plan['parameters']['clearance']
    if plan['safe_z']<minimum_plane-EPS or plan['initial_position'][2]<plan['safe_z']-EPS:
        raise MotionPlanningError('Passage plane does not clear the declared stock/obstacles')
    source_edges={}
    internal_pending=set()
    for li,layer in enumerate(source['layers']):
        for pi,poly in enumerate(layer['polylines']):
            for ei,(a,b) in enumerate(zip(poly['points'],poly['points'][1:])):
                source_edges[(li,pi,ei)]=(a,b)
                if (source.get('order')=='internal_contours_full_depth_then_external'
                        and layer.get('contour_kind')=='internal'):
                    internal_pending.add((li,pi,ei))
    current=plan['initial_position'];visited={};tracks={};seen=Counter();angles=[]
    completed=CutTrackIndex(source['tool']['diameter'])
    cleared_area=ClearedArea(source['tool']['diameter'],plan['stock_top'])
    if prior_motion is not None:
        if not _close(plan['initial_position'],prior_motion.get('final_position',[math.inf]*3)):
            raise MotionPlanningError('Estado inicial não corresponde ao desbaste anterior')
        prior_state=build_prior_cut_state(prior_motion,source['tool'],plan['stock_top'])
        if plan.get('prior_roughing')!={'cut_moves':prior_state.cut_count,'sha256':prior_state.fingerprint}:
            raise MotionPlanningError('O material removido pelo desbaste anterior mudou; recalcule o cutout')
        completed=prior_state.tracks;cleared_area=prior_state.area
        for a,b,_ in prior_state.cuts:
            xy_pair=tuple(sorted([_xy_key(a),_xy_key(b)]))
            heights=[a[2],b[2]] if _xy_key(a)==xy_pair[0] else [b[2],a[2]]
            tracks.setdefault(xy_pair,[]).append(heights)
            for point in (a,b):visited[_xy_key(point)]=min(visited.get(_xy_key(point),math.inf),point[2])
    elif plan.get('prior_roughing'):
        raise MotionPlanningError('Cutout depende de desbaste anterior que não foi executado/validado')
    moves=plan['moves'];step=source['parameters']['stepdown'];report_every=max(1,len(moves)//200)
    for index,move in enumerate(moves):
        a,b=move['start'],move['end'];kind=move['kind'];proof=move['proof']
        if move['id']!=index or not _close(a,current) or not all(math.isfinite(x) for x in a+b):
            raise MotionPlanningError('Invalid move continuity or coordinates')
        if kind in ('cut','ramp','ramp_return'):
            if (internal_pending and source['layers'][move['layer']].get('contour_kind')=='external'):
                raise MotionPlanningError('Cutout externo iniciado antes de concluir os recortes internos')
            key=(move['layer'],move['polyline'],proof['source_edge'])
            u,v=source_edges[key];direction=np.array(v[:2])-u[:2]
            denominator=float(direction@direction)
            for point in (a,b):
                fraction=float((np.array(point[:2])-u[:2])@direction/denominator)
                expected=np.array(u[:2])+fraction*direction
                if fraction< -EPS or fraction>1+EPS or math.dist(point[:2],expected)>EPS:
                    raise MotionPlanningError('Entry leaves the source cutting footprint')
                if point[2]<u[2]+fraction*(v[2]-u[2])-EPS:
                    raise MotionPlanningError('Entry goes below the source surface envelope')
            if kind=='cut':
                if not ((_close(a,u) and _close(b,v)) or (_close(a,v) and _close(b,u))):
                    raise MotionPlanningError('Cut geometry changed')
                xy_pair=tuple(sorted([_xy_key(a),_xy_key(b)]))
                heights=[a[2],b[2]] if _xy_key(a)==xy_pair[0] else [b[2],a[2]]
                candidates=reversed(tracks.get(xy_pair,[]))
                # An identical previously cut XY edge bounds remaining stock
                # by its linear tip-height profile. Both endpoint differences
                # bound the whole new linear edge's material depth.
                supported=(plan['stock_top']-min(heights)<=step+EPS or
                    any(max(old[0]-heights[0],old[1]-heights[1])<=step+EPS for old in candidates))
                if not supported:
                    supported=_track_depth_supported(a,b,completed,plan['stock_top'],step)
                if not supported:
                    supported=cleared_area.covers(a,b,min(a[2],b[2])+step)
                if not supported:
                    raise MotionPlanningError('Cut exceeds one stepdown without a matching cleared track')
                tracks.setdefault(xy_pair,[]).append(heights)
                completed.append((a,b))
                cleared_area.add(a,b)
                seen[key]+=1
                internal_pending.discard(key)
                for p in (a,b):visited[_xy_key(p)]=min(visited.get(_xy_key(p),math.inf),p[2])
            elif kind=='ramp':
                if not _track_depth_supported(a,b,completed,plan['stock_top'],step):
                    if not cleared_area.covers(a,b,min(a[2],b[2])+step):
                        raise MotionPlanningError('Ramp exceeds stepdown in unproven material')
                length=math.dist(a[:2],b[:2])
                angle=math.degrees(math.atan2(max(0,a[2]-b[2]),length))
                if angle>plan['parameters']['entry_angle_deg']+1e-7:
                    raise MotionPlanningError('Entry angle exceeded')
                angles.append(angle)
            elif abs(a[2]-b[2])>EPS:
                raise MotionPlanningError('Ramp return must remain at the entry level')
        elif kind=='plunge':
            if plan['parameters'].get('allow_center_plunge') is not True or proof.get('center_cutting_required') is not True:
                raise MotionPlanningError('Vertical cutting entry requires a confirmed center-cutting tool')
            points=source['layers'][move['layer']]['polylines'][move['polyline']]['points']
            peak=max(points,key=lambda p:p[2])
            edge_index=proof.get('source_edge')
            if (type(edge_index) is not int or not 0<=edge_index<len(points)-1
                    or not any(_close(peak,point) for point in points[edge_index:edge_index+2])):
                raise MotionPlanningError('Vertical cutting entry lacks its source contact vertex')
            if (math.dist(a[:2],peak[:2])>EPS or math.dist(b[:2],peak[:2])>EPS
                    or abs(b[2]-peak[2])>EPS or a[2]<b[2]-EPS):
                raise MotionPlanningError('Vertical cutting entry leaves its source contact envelope')
            known=min(plan['stock_top'],visited.get(_xy_key(b),math.inf))
            for c,e in completed.overlapping(b,b):
                height=_height_on_track(b,c,e)
                if height is not None:known=min(known,height)
            if a[2]<known-EPS and cleared_area.covers(b,b,a[2]):known=a[2]
            if a[2]<known-EPS or known-b[2]>step+EPS:
                raise MotionPlanningError('Vertical cutting entry exceeds one proved stepdown')
        elif kind in ('approach','cleared_feed'):
            known=min(plan['stock_top'],visited.get(_xy_key(b),math.inf))
            if min(a[2],b[2])<known-EPS:
                for c,e in completed.overlapping(b,b):
                    height=_height_on_track(b,c,e)
                    if height is not None:known=min(known,height)
            if min(a[2],b[2])<known-EPS and cleared_area.covers(b,b,min(a[2],b[2])):
                known=min(a[2],b[2])
            if math.dist(a[:2],b[:2])>EPS or min(a[2],b[2])<known-EPS:
                raise MotionPlanningError('Vertical feed lacks same-XY clearance proof')
        elif kind=='retract':
            if math.dist(a[:2],b[:2])>EPS or b[2]<a[2]-EPS or abs(b[2]-plan['safe_z'])>EPS:
                raise MotionPlanningError('Invalid retract')
        elif kind=='travel':
            if abs(a[2]-plan['safe_z'])>EPS or abs(b[2]-plan['safe_z'])>EPS:
                raise MotionPlanningError('Low traverse without proof')
        elif kind=='clearance_adjust':
            if math.dist(a[:2],b[:2])>EPS or min(a[2],b[2])<plan['safe_z']-EPS:
                raise MotionPlanningError('Clearance adjustment below the passage plane')
        elif kind=='link_backtrack':
            ref=proof['source_cut_move']
            if not 0<=ref<index or moves[ref]['kind']!='cut' or not _close(a,moves[ref]['end']) or not _close(b,moves[ref]['start']):
                raise MotionPlanningError('Backtrack does not retrace a completed cut')
        elif kind=='link_cleared':
            if not _cleared_link_supported(a,b,completed,cleared_area):
                raise MotionPlanningError('Low link lacks completed-cut clearance proof')
        else:raise MotionPlanningError('Unknown move kind')
        current=b
        if progress and ((index+1)%report_every==0 or index+1==len(moves)):
            progress(f'Revisando movimentos: {index+1}/{len(moves)}',.98*(index+1)/len(moves))
    if seen!=Counter({key:1 for key in source_edges}):
        raise MotionPlanningError('Missing or duplicate source cut edges')
    for entry in plan['entries']:
        if entry['entry_start_z']-entry['peak'][2]>step+EPS:
            raise MotionPlanningError('Entry material-depth budget exceeded')
    if plan.get('path_order')=='region_first':
        visits=[]
        for entry in plan['entries']:
            region=entry['region']
            if not visits or visits[-1]!=region:visits.append(region)
        if len(visits)!=len(set(visits)) or visits!=plan['region_schedule']['visit_order']:
            raise MotionPlanningError('A completed region was revisited')
    if not _close(current,plan['final_position']) or (moves and current[2]<plan['safe_z']-EPS):
        raise MotionPlanningError('Invalid final position')
    if progress:progress('Movimentos conferidos',1)
    return {'status':'passed','moves_replayed':len(moves),'source_edges_preserved':len(source_edges),
            'cut_edges_with_material_depth_proof':sum(seen.values()),
            'cleared_area_proofs':cleared_area.proofs,
            'low_links_with_completed_cut_proof':sum(m['kind']=='link_cleared' for m in moves),
            'maximum_entry_descent_angle_deg':max(angles,default=0),
            'scope':'Continuity, source-footprint/height domination, bounded material depth, cut multiplicity and link provenance; not general stock/holder collision simulation'}
