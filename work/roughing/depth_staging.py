"""Stage new footprints from above when prior stock clearance is absent.

The entire path must have a depth proof BEFORE it is cut (or ramped). When
needed, copy the same XY path at a shallower floor, recursively. Only raises Z;
does not invent low cross-region links or credit future cuts as clearance.
"""
import copy
import math
from cleared_area import ClearedArea
from motion_planner import _track_depth_supported,_height_on_track,_branches,EPS
from track_index import CutTrackIndex

MAX_STAGED_EDGES=250_000


def stage_paths(layers,*,diameter,stock_top,stepdown,progress=None,prune_redundant=False,
                trim_redundant=False,stats=None):
    total=sum(len(layer['polylines']) for layer in layers)
    completed=0;report_every=max(1,total//200)
    if progress:progress('Conferindo profundidade das passadas',0)
    area=ClearedArea(diameter,stock_top);previous=CutTrackIndex(diameter);tracks={};added=0;edge_count=0
    omitted=0;omitted_rasters=0;removed_edges=0;removed_length=0.;trimmed_paths=0;extra_fragments=0
    def key(a,b):return tuple(sorted((tuple(a[:2]),tuple(b[:2]))))
    def supported(points):
        peak=_branches(points)[0];floor=stock_top
        for a,b in previous.overlapping(peak,peak):
            if (height:=_height_on_track(peak,a,b)) is not None:floor=min(floor,height)
        if floor-peak[2]>stepdown+EPS and not area.covers(peak,peak,peak[2]+stepdown):
            return False
        for a,b in zip(points,points[1:]):
            if stock_top-min(a[2],b[2])<=stepdown+EPS:continue
            candidates=tracks.get(key(a,b),[])
            u,v=(a,b) if tuple(a[:2])<=tuple(b[:2]) else (b,a)
            # Recent traversals are normally the deepest. Eligibility is
            # unchanged; trying them first avoids scanning every old level.
            if any(max(c[2]-u[2],e[2]-v[2])<=stepdown+EPS for c,e in reversed(candidates)):continue
            if _track_depth_supported(a,b,previous,stock_top,stepdown):continue
            if not area.covers(a,b,min(a[2],b[2])+stepdown):return False
        return True
    def commit(poly,result):
        nonlocal edge_count,omitted,omitted_rasters,removed_edges,removed_length,trimmed_paths,extra_fragments
        points=poly['points'];prepared=[poly]
        if prune_redundant and poly.get('kind')!='preparation' and not poly.get('entry_bridge'):
            # Classify against COMPLETED paths before crediting any edge of
            # this path. Exact collinear profiles prove the identical swept
            # tool volume, including slopes and either travel direction.
            edges=list(zip(points,points[1:]))
            covered=[_track_depth_supported(a,b,previous,float('inf'),0) for a,b in edges]
            fully_removed=all(covered)
            if not fully_removed and poly.get('kind')=='raster':
                # Preserve the original guarded full-capsule raster proof.
                fully_removed=all(old or area.covers(a,b,min(a[2],b[2]),require_cut=True)
                                  for old,(a,b) in zip(covered,edges))
            if fully_removed:
                omitted+=1;omitted_rasters+=poly.get('kind')=='raster'
                removed_edges+=len(edges);removed_length+=sum(math.dist(a,b) for a,b in edges)
                return 0
            if trim_redundant and poly.get('kind')=='preclear' and any(covered):
                # Auxiliary copies of variable-Z contours often repeat old
                # plateaus. Remove only entire proved edges, retaining every
                # unproved edge unchanged. Callers enable splitting only when
                # center-cutting entry is confirmed for the new fragments.
                prepared=[];start=None
                for index,old in enumerate(covered+[True]):
                    if not old and start is None:start=index
                    elif old and start is not None:
                        retained=copy.deepcopy(points[start:index+1])
                        prepared.append({**poly,'points':retained,
                            'closed':math.dist(retained[0],retained[-1])<EPS})
                        start=None
                if (len(prepared)>1 and math.dist(points[0],points[-1])<EPS
                        and not covered[0] and not covered[-1]):
                    # The last/first retained spans of a closed loop touch.
                    # Join across that original vertex without inventing a
                    # shortcut or another entry into the same material run.
                    retained=prepared[-1]['points']+prepared[0]['points'][1:]
                    prepared=[{**poly,'points':retained,'closed':False}]+prepared[1:-1]
                if all(supported(path['points']) for path in prepared):
                    removed_edges+=sum(covered)
                    removed_length+=sum(math.dist(a,b) for old,(a,b) in zip(covered,edges) if old)
                    trimmed_paths+=1;extra_fragments+=len(prepared)-1
                else:
                    # A changed entry may need a stronger point-footprint
                    # proof than its old path. Keep the already-proved source
                    # intact instead of rejecting a valid machining job.
                    prepared=[poly]
        for path in prepared:
            # A changed entry peak needs the same depth proof as any primary
            # path. No omitted or future span is added as clearance here.
            if path is not poly and not supported(path['points']):raise ValueError('Trimmed path lacks a material depth proof')
            result.append(path)
            for a,b in zip(path['points'],path['points'][1:]):
                area.add(a,b);previous.append((a,b));edge_count+=1
                canonical=(a,b) if tuple(a[:2])<=tuple(b[:2]) else (b,a)
                tracks.setdefault(key(a,b),[]).append(canonical)
        if edge_count>MAX_STAGED_EDGES:
            raise ValueError(f'Preparação das profundidades excedeu {MAX_STAGED_EDGES:,} arestas. '
                             'Reduza a área ou profundidade, ou aumente a amostragem.')
        return len(prepared)
    def ensure(poly,result):
        nonlocal added
        # Use an explicit stack so the documented staging budget, rather
        # than Python's smaller call-stack limit, controls deep preparation.
        pending=[poly]
        while not supported(pending[-1]['points']):
            if len(pending)>1000:raise ValueError('Depth staging pass limit exceeded')
            parent=pending[-1];points=parent['points']
            level=min(p[2] for p in points)+stepdown
            auxiliary={**copy.deepcopy(parent),'kind':'preclear',
                'parent_kind':parent.get('parent_kind',parent.get('kind','raster')),
                'points':[[p[0],p[1],max(p[2],level)] for p in points],
                'preclear_floor_z':level}
            pending.append(auxiliary)
        for prepared_index,prepared in enumerate(reversed(pending)):
            # The while condition proved this first path, with no intervening
            # cuts. Parents must still be proved after each child is cut.
            if prepared_index and not supported(prepared['points']):raise ValueError('Staged path still lacks a material depth proof')
            emitted=commit(prepared,result)
            if prepared is not poly:added+=emitted
    for layer_index,layer in enumerate(layers):
        result=[]
        for poly in layer['polylines']:
            ensure(poly,result)
            completed+=1
            if progress and (completed%report_every==0 or completed==total):
                progress(f'Conferindo profundidade: camada {layer_index+1}/{len(layers)}, passada {completed}/{total}',
                         completed/total)
        layer['polylines']=result
    if progress:progress('Profundidades das passadas conferidas',1)
    if stats is not None:stats.update(redundant_raster_paths_removed=omitted_rasters,
        redundant_paths_removed=omitted,redundant_edges_removed=removed_edges,
        redundant_cutting_length_mm=removed_length,trimmed_preclear_paths=trimmed_paths,
        preclear_fragments_added=extra_fragments)
    return added
