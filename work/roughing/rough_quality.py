"""Floor-aware roughing levels and bounded upward contact approximation.

Only this application's geometry primitives are used. Horizontal candidates
still pass layer-shadow, cutter-contact and chronological depth validation;
detecting an underside never makes it accessible from above.
"""
from dataclasses import replace
import math
import numpy as np


def horizontal_levels(triangles,*,top,bottom,axial_allowance=0):
    triangles=np.asarray(triangles,float)
    projected=np.abs(np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0])[:,2])/2
    mask=(np.ptp(triangles[:,:,2],axis=1)<=1e-8)&(projected>1e-8)
    groups={}
    for z,area in zip(triangles[mask,:,2].max(axis=1)+axial_allowance,projected[mask]):
        if not bottom-1e-8<=z<top-1e-8:continue
        key=round(float(z),6);group=groups.setdefault(key,{'z_mm':float(z),'projected_area_mm2':0.})
        group['z_mm']=max(group['z_mm'],float(z));group['projected_area_mm2']+=float(area)
    if len(groups)>512:raise ValueError('Mais de 512 alturas de pisos; reduza a complexidade da malha.')
    return sorted(groups.values(),key=lambda g:g['z_mm'],reverse=True)


def include_floor_levels(layers,floors,top,stepdown,extra_levels=()):
    # Redistribute each interval between mandatory floors instead of adding
    # an almost coincident floor pass to an unrelated uniform schedule.
    bottom=layers[-1].z
    depths=sorted([bottom]+[f['z_mm'] for f in floors]+[
        z for z in extra_levels if bottom<z<top],reverse=True)
    unique=[]
    for z in depths:
        if not unique or abs(z-unique[-1])>1e-9:unique.append(z)
    upper=top;result=[]
    for floor in unique:
        n=math.ceil((upper-floor)/stepdown);delta=(upper-floor)/n
        if len(result)+n>100_000:raise ValueError('Limite de 100.000 camadas de desbaste excedido.')
        for i in range(n):
            z=max(floor,upper-(i+1)*delta)
            result.append(replace(layers[0],z=z,passo=delta,
                margem_amostragem=delta+layers[0].tolerancia*10))
        upper=floor
    return result


def quality_spec(triangles,*,top,bottom,axial_allowance,surface_error,path_tolerance):
    return {'method':'floor_aware_upward_contact_bands',
        'horizontal_levels':horizontal_levels(triangles,top=top,bottom=bottom,axial_allowance=axial_allowance),
        'surface_extra_z_mm':surface_error,'source_path_tolerance_mm':path_tolerance,
        'scope':'Additional tip Z above the guarded contact envelope; inaccessible corners/undersides are not a residual guarantee'}


def bounded_contact_heights(heights,*,top,max_extra,floors):
    """Never lower the protected contact envelope; extra Z is <= max_extra.

    Quantization is relative to stock top, so changing the datum preserves
    the physical result. Real floor candidates avoid quantization leftovers.
    """
    h=np.asarray(heights,float)
    if not math.isfinite(max_extra) or max_extra<=0:raise ValueError('Sobra adicional deve ser positiva.')
    # Avoid a whole-band jump from floating-point noise when shifting the
    # datum. The final max(h,raised) still prevents lowering the envelope.
    raised=top+np.ceil((h-top)/max_extra-1e-10)*max_extra
    levels=np.array(sorted(f['z_mm'] for f in floors),float)
    if len(levels):
        indices=np.searchsorted(levels,h-1e-9)
        candidates=levels[np.minimum(indices,len(levels)-1)]
        raised=np.minimum(raised,np.where(indices<len(levels),candidates,np.inf))
    # Floating-point ceiling/snap can be infinitesimally below the input.
    return np.maximum(h,raised)


def simplify_allowed_loop(loop,regions,tolerance):
    """Simplify XY before OCL samples the resulting segments again.

    Every shortcut remains inside the exact allowed center region and within
    the deviation budget. Chords through islands or Keep Out are rejected.
    """
    p=np.asarray(loop,float)
    if tolerance<=0 or len(p)<4:return np.vstack([p,p[0]]).tolist()
    from smart_planner import _edge_in_domain
    far=int(np.argmax(np.linalg.norm(p-p[0],axis=1)))
    closed=np.vstack([p,p[0]]);keep={0,far,len(p)};pending=[(0,far),(far,len(p))]
    allowed=[np.asarray(region,float).tolist() for region in regions]
    while pending:
        start,end=pending.pop()
        if end-start<=1:continue
        a,b=closed[start],closed[end];d=b-a;squared=float(d@d)
        if squared==0:split=(start+end)//2
        else:
            part=closed[start+1:end];t=np.clip((part-a)@d/squared,0,1)
            errors=np.linalg.norm(part-(a+t[:,None]*d),axis=1)
            index=int(np.argmax(errors));split=start+1+index
            if errors[index]<=tolerance and _edge_in_domain([*a,0],[*b,0],allowed):continue
            if errors[index]<=tolerance:split=(start+end)//2
        keep.add(split);pending.extend(((start,split),(split,end)))
    return closed[sorted(keep)].tolist()
