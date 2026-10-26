"""Experimental 2D centerline region and raster construction using Clipper2.

Physical exclusions are expanded by the tool radius; the allowed physical
boundary is inset by the same radius. This is an explicit design decision,
not a claim that MeshCAM uses identical boundary semantics. No motion links,
surface processing or G-code are produced here.
"""
from pathlib import Path
import math
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'geometry-libs'))
import numpy as np
import pyclipr

SCALE = 1_000_000


def signed_area(path):
    p=np.asarray(path,dtype=float)[:,:2]
    return float(np.sum(p[:,0]*np.roll(p[:,1],-1)-np.roll(p[:,0],-1)*p[:,1])/2)


def normalize_solids(paths):
    result=[]
    for path in paths:
        p=np.asarray(path,dtype=float)[:,:2]
        if len(p)<3 or not np.isfinite(p).all() or abs(signed_area(p))<1e-12:
            raise ValueError('Expected finite nondegenerate closed polygons')
        result.append(p if signed_area(p)>0 else p[::-1])
    return result


def boolean(subjects,clips,operation):
    engine=pyclipr.Clipper();engine.scaleFactor=SCALE
    engine.addPaths(subjects,pyclipr.Subject)
    if clips: engine.addPaths(clips,pyclipr.Clip)
    return engine.execute(operation,pyclipr.FillRule.NonZero)


def offset(paths,distance):
    if not paths: return []
    engine=pyclipr.ClipperOffset();engine.scaleFactor=SCALE
    # ClipperOffset stores this tolerance in its scaled integer coordinates.
    engine.arcTolerance=0.001*SCALE
    engine.addPaths(paths,pyclipr.JoinType.Round,pyclipr.EndType.Polygon)
    return engine.execute(distance)


def center_regions(boundaries,exclusions,diameter,margin=0.01):
    """Return centerline space for a disk cutter inside the physical boundary.

    Inputs are solid polygons; exclusions are independent solids, not holes
    encoded by winding. Overlapping solids are unioned with NonZero fill.
    Caller owns the Z validity of every obstacle. Tool body/holder not modeled.
    """
    if not math.isfinite(diameter) or diameter<=0 or not math.isfinite(margin) or margin<0:
        raise ValueError('Invalid tool or margin')
    if not boundaries: return []
    radius=diameter/2+margin
    boundary=boolean(normalize_solids(boundaries),[],pyclipr.Union)
    inside=offset(boundary,-radius)
    if not inside or not exclusions: return inside
    excluded=boolean(normalize_solids(exclusions),[],pyclipr.Union)
    excluded=offset(excluded,radius)
    return boolean(inside,excluded,pyclipr.Difference)


def raster_segments(regions,stepover,origin_y=0.0):
    """Independent clipped horizontal cutting segments; no connecting moves."""
    if not math.isfinite(stepover) or stepover<=0 or not math.isfinite(origin_y):
        raise ValueError('Invalid raster spacing/origin')
    if not regions: return []
    points=np.concatenate(regions)
    low,high=points.min(axis=0),points.max(axis=0)
    start=math.ceil((low[1]-origin_y)/stepover)
    end=math.floor((high[1]-origin_y)/stepover)
    if end-start>100_000: raise ValueError('Too many rows for this prototype')
    result=[]
    for row in range(start,end+1):
        y=origin_y+row*stepover
        engine=pyclipr.Clipper();engine.scaleFactor=SCALE
        engine.addPath([[low[0]-1,y],[high[0]+1,y]],pyclipr.Subject,True)
        engine.addPaths(regions,pyclipr.Clip)
        _,open_paths=engine.execute(pyclipr.Intersection,pyclipr.FillRule.NonZero,returnOpenPaths=True)
        segments=[]
        for path in open_paths:
            a,b=sorted([path[0,:2],path[-1,:2]],key=lambda p:p[0])
            if np.linalg.norm(b-a)>1e-8: segments.append([a.tolist(),b.tolist()])
        segments.sort(key=lambda p:p[0][0],reverse=bool(row%2))
        if row%2: segments=[segment[::-1] for segment in segments]
        result.extend({'row':row,'start':a,'end':b} for a,b in segments)
    return result
