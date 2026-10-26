"""Top-down protected shadows and Clipper2 layer regions.

Design reference: GridSpace/grid-apps OpArea shadowAt/offset/subtract flow,
commit d138275bbe9d4e4030d8cb8b2dcf66607da9295a (MIT).
Independent implementation: clips 3D triangles above the tip plane, projects
their union, and dilates by the effective cutter radius. No JS source copied.
"""
import numpy as np
from region_core import boolean,offset,pyclipr,signed_area


def shadow_above(triangles,height,*,include_coplanar=False):
    paths=[]
    for triangle in triangles:
        maximum=float(triangle[:,2].max())
        if maximum<height or (maximum==height and not include_coplanar):
            continue  # Tangency to a horizontal floor is allowed.
        polygon=[]
        for a,b in zip(triangle,np.roll(triangle,-1,axis=0)):
            inside_a=a[2]>=height if include_coplanar else a[2]>height
            inside_b=b[2]>=height if include_coplanar else b[2]>height
            if inside_a:polygon.append(a)
            if inside_a!=inside_b:
                polygon.append(a+(b-a)*((height-a[2])/(b[2]-a[2])))
        if len(polygon)<3:continue
        xy=np.asarray(polygon)[:,:2]
        area=signed_area(xy)
        if abs(area)>1e-12:paths.append(xy if area>0 else xy[::-1])
    return boolean(paths,[],pyclipr.Union) if paths else []


def free_layer_regions(triangles,domain,height,radius,*,include_coplanar=False):
    if not domain:return []
    protected=shadow_above(triangles,height,include_coplanar=include_coplanar)
    forbidden=offset(protected,radius) if protected else []
    return boolean(domain,forbidden,pyclipr.Difference) if forbidden else domain


def region_area(regions):
    # Clipper output retains hole winding. Never normalize all loops to CCW.
    return sum(signed_area(p) for p in regions)
