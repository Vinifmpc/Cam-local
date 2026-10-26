"""Editable approximate limits from observed feed-run envelopes.

This DOES NOT recover a MeshCAM keepout. It derives rectangular authorized
windows from the reference NC, then protects their complement in a declared
workspace. Never use this mask as an independent validation of that same NC.
"""
import math


def rectangle(x0,y0,x1,y1):return [[x0,y0],[x1,y0],[x1,y1],[x0,y1]]


def approximate_reference_keepout(moves,*,diameter,workspace,padding=.05):
    if diameter<=0 or padding<0 or not all(math.isfinite(v) for v in (diameter,padding,*workspace)):
        raise ValueError('Invalid mask parameters')
    runs=[];points=[]
    def flush():
        nonlocal points
        if points:
            r=diameter/2+padding
            runs.append([min(p[0] for p in points)-r,min(p[1] for p in points)-r,
                         max(p[0] for p in points)+r,max(p[1] for p in points)+r]);points=[]
    for move in moves:
        if move['mode']!=1:flush();continue
        a,b=move['start'],move['end']
        if any(v is None for v in a+b):continue
        if max(a[2],b[2])<=0 and math.dist(a[:2],b[:2])>1e-8:points.extend([a,b])
    flush()
    if not runs:raise ValueError('No reference cutting runs for a mask estimate')
    windows=[]
    for box in runs:
        changed=True
        while changed:
            changed=False
            for i,old in enumerate(windows):
                if max(box[0],old[0])<=min(box[2],old[2]) and max(box[1],old[1])<=min(box[3],old[3]):
                    box=[min(box[0],old[0]),min(box[1],old[1]),max(box[2],old[2]),max(box[3],old[3])]
                    windows.pop(i);changed=True;break
        windows.append(box)
    windows.sort(key=lambda b:(b[1],b[0]))
    x0,y0,x1,y1=workspace
    if x0>=x1 or y0>=y1 or any(b[0]<x0 or b[1]<y0 or b[2]>x1 or b[3]>y1 for b in windows):
        raise ValueError('Workspace must contain every estimated window')
    xs=sorted({x0,x1,*[v for b in windows for v in (b[0],b[2])]})
    ys=sorted({y0,y1,*[v for b in windows for v in (b[1],b[3])]})
    forbidden=[]
    for left,right in zip(xs,xs[1:]):
        for bottom,top in zip(ys,ys[1:]):
            x=(left+right)/2;y=(bottom+top)/2
            if not any(b[0]<x<b[2] and b[1]<y<b[3] for b in windows):
                forbidden.append(rectangle(left,bottom,right,top))
    return {'exact_original_keepout':False,'derived_from_reference_nc':True,
        'status':'approximate_editable_not_independent_validation',
        'units':'mm','assumed_tool_diameter_mm':diameter,'padding_mm':padding,
        'method':'Merged bounding boxes of nonrapid feed runs at/below Z=0; expanded by radius+padding',
        'authorized_physical_windows_xyxy_mm':windows,'boundaries_mm':[rectangle(*workspace)],
        'exclusions_mm':forbidden,
        'caveat':'Window size is inferred from the same NC used for comparison. Original MeshCAM keepout remains unknown.'}
