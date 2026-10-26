"""Finish independent swept XY regions before visiting the next one.

Connected components use the union of buffered cutting polylines, including
all depths and preclear passes. Overlapping clearance dependencies therefore
stay together. A numerical guard can merge components, never justify a low
link. Original layer/path order is preserved within each component.
"""
import math
import numpy as np
from region_core import boolean,pyclipr,SCALE,signed_area


def contains(point,polygon):
    x,y=point;inside=False
    for a,b in zip(polygon,np.roll(polygon,-1,axis=0)):
        if (a[1]>y)!=(b[1]>y) and x<(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]:inside=not inside
    return inside


def peak(points):return max(points,key=lambda p:p[2])


def finish(points):
    i=max(range(len(points)),key=lambda n:points[n][2])
    if i==0:return points[-1]
    if i==len(points)-1:return points[0]
    left=sum(math.dist(a[:2],b[:2]) for a,b in zip(points[:i],points[1:i+1]))
    right=sum(math.dist(a[:2],b[:2]) for a,b in zip(points[i:-1],points[i+1:]))
    # The motion planner cuts the longer branch first. Equal branches retain
    # right-then-left order, so the path finishes at its original first vertex.
    return points[0] if right>=left else points[-1]


def region_first(paths,diameter,initial_xy=None):
    if not paths:return [],{}, {'region_count':0,'visit_order':[],'regions':[]}
    if len(paths)>20000:raise ValueError('Limite de 20.000 percursos para agrupar regiões')
    engine=pyclipr.ClipperOffset();engine.scaleFactor=SCALE;engine.arcTolerance=.001*SCALE
    seen_xy=set()
    for _,_,points in paths:
        xy=np.asarray(points,float)[:,:2]
        closed=np.linalg.norm(xy[0]-xy[-1])<1e-10
        route=xy[:-1] if closed else xy
        # Preclear and deeper layers commonly repeat the same XY route.
        # Their swept region is identical; retaining every depth creates
        # thousands of coincident arcs for Clipper without adding any area.
        vertices=tuple(map(tuple,route));key=(closed,min(vertices,vertices[::-1]))
        if key in seen_xy:continue
        seen_xy.add(key)
        engine.addPath(route,pyclipr.JoinType.Round,
                       pyclipr.EndType.Joined if closed else pyclipr.EndType.Round)
    buffered=engine.execute(diameter/2+.01)
    union=boolean(buffered,[],pyclipr.Union)
    # A disconnected island can lie inside the hole of another component.
    # Select the smallest containing outer ring; do not fill/cancel holes.
    outer=sorted((p for p in union if signed_area(p)>0),key=lambda p:abs(signed_area(p)))
    groups={};ids={};mapping={};point_components={}
    for item in paths:
        li,pi,points=item
        first_xy=tuple(points[0][:2])
        if first_xy in point_components:component=point_components[first_xy]
        else:
            component=next((i for i,p in enumerate(outer) if contains(first_xy,p)),None)
            point_components[first_xy]=component
        if component is None:raise ValueError('Não foi possível classificar uma região na precisão geométrica atual')
        if component not in ids:ids[component]=len(ids)
        region=ids[component];groups.setdefault(region,[]).append(item);mapping[li,pi]=region
    ordered=[];visits=[];remaining=set(groups)
    position=list(initial_xy) if initial_xy is not None else peak(paths[0][2])[:2]
    while remaining:
        region=min(remaining,key=lambda r:(math.dist(position,peak(groups[r][0][2])[:2]),r))
        visits.append(region);ordered.extend(groups[region]);remaining.remove(region)
        position=finish(groups[region][-1][2])[:2]
    metadata=[]
    for region in visits:
        points=np.concatenate([np.asarray(p,float) for _,_,p in groups[region]])
        metadata.append({'id':region,'path_count':len(groups[region]),
            'minimum_xy':points[:,:2].min(axis=0).tolist(),'maximum_xy':points[:,:2].max(axis=0).tolist(),
            'deepest_z':float(points[:,2].min())})
    return ordered,mapping,{'region_count':len(groups),'visit_order':visits,'regions':metadata,
        'method':'connected_union_of_tool_swept_XY_paths_all_depths',
        'grouping_guard_mm':.01,'in_region_order':'original_layer_then_path',
        'scope':'Independent XY components; pockets connected at any depth stay in one conservative group'}
