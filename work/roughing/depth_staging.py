"""Stage new footprints from above when prior stock clearance is absent.

The entire path must have a depth proof BEFORE it is cut (or ramped). When
needed, copy the same XY path at a shallower floor, recursively. Only raises Z;
does not invent low cross-region links or credit future cuts as clearance.
"""
import copy
from cleared_area import ClearedArea
from motion_planner import _track_depth_supported,_height_on_track,_branches,EPS
from track_index import CutTrackIndex

MAX_STAGED_EDGES=250_000


def stage_paths(layers,*,diameter,stock_top,stepdown,progress=None):
    total=sum(len(layer['polylines']) for layer in layers)
    completed=0;report_every=max(1,total//200)
    if progress:progress('Conferindo profundidade das passadas',0)
    area=ClearedArea(diameter,stock_top);previous=CutTrackIndex(diameter);tracks={};added=0;edge_count=0
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
        nonlocal edge_count
        points=poly['points'];result.append(poly)
        for a,b in zip(points,points[1:]):
            area.add(a,b);previous.append((a,b));edge_count+=1
            canonical=(a,b) if tuple(a[:2])<=tuple(b[:2]) else (b,a)
            tracks.setdefault(key(a,b),[]).append(canonical)
        if edge_count>MAX_STAGED_EDGES:
            raise ValueError(f'Preparação das profundidades excedeu {MAX_STAGED_EDGES:,} arestas. '
                             'Reduza a área ou profundidade, ou aumente a amostragem.')
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
            commit(prepared,result)
        added+=len(pending)-1
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
    return added
