"""Closed roughing loops for a planar annular pocket, with area proofs.

Only replaces the raster when guarded tool sweeps cover the requested physical
region within the existing path tolerance. Failed proofs keep the raster.
"""
from functools import lru_cache
import math
import numpy as np
from region_core import boolean,offset,pyclipr,signed_area
from rough_quality import simplify_allowed_loop


@lru_cache(maxsize=16)
def _candidate(encoded,stepover,tool_radius,tolerance):
    regions=[np.asarray(p,float) for p in encoded]
    if len(regions)!=2 or sum(signed_area(p)>0 for p in regions)!=1:return None
    # The proof uses under-sized old sweeps and a physical target contracted
    # only by the user-selected path tolerance. Zero tolerance falls back.
    budget=min(tolerance,tool_radius*.02)
    if budget<=.008 or tool_radius<=.01:return None
    paths=[];current=regions
    for iteration in range(16):
        if not current:break
        if len(current)!=2 or sum(signed_area(p)>0 for p in current)!=1:return None
        paths.extend(simplify_allowed_loop(p,regions,tolerance) for p in current)
        current=offset(regions,-stepover*(iteration+1))
    else:return None
    if len(paths)>32 or sum(len(p) for p in paths)>12000:return None
    from smart_planner import _edge_in_domain
    allowed=[p.tolist() for p in regions]
    if any(not _edge_in_domain(a,b,allowed) for p in paths for a,b in zip(p,p[1:])):return None
    sweeps=[]
    for p in paths:
        solid=np.asarray(p[:-1],float)
        if signed_area(solid)<0:solid=solid[::-1]
        expanded=offset([solid],tool_radius-.005)
        eroded=offset([solid],-(tool_radius-.005))
        sweeps.extend(boolean(expanded,eroded,pyclipr.Difference) if eroded else expanded)
    covered=boolean(sweeps,[],pyclipr.Union)
    target=offset(regions,tool_radius-budget)
    if boolean(target,covered,pyclipr.Difference):return None
    length=sum(math.dist(a,b) for p in paths for a,b in zip(p,p[1:]))
    return paths,{'method':'guarded_annular_contour_coverage','physical_boundary_tolerance_mm':budget,
                  'loops':len(paths),'length_mm':length,'target_area_mm2':sum(signed_area(p) for p in target)}


def annular_contours(regions,*,stepover,tool_radius,tolerance,raster_length,cleanup_length,raster_count):
    if not regions or stepover<=0 or sum(len(p) for p in regions)>2048:return None
    encoded=tuple(tuple(tuple(float(v) for v in p) for p in path) for path in regions)
    result=_candidate(encoded,float(stepover),float(tool_radius),float(tolerance))
    if result is None:return None
    paths,proof=result
    # Do not add loops on a marginal tradeoff. Both cutting length and the
    # number of disconnected entries must decrease substantially.
    if proof['length_mm']>=(raster_length+cleanup_length)*.95 or len(paths)>=max(1,raster_count/2):return None
    return [('cleanup',None,[p[:] for p in path]) for path in paths],dict(proof)
