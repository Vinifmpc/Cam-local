"""2D silhouette cutout with radius compensation and internal contours first.

Uses the full XY envelope, not a waterline that changes with Z. No tabs or
undercut machining. This is an independent Clipper2 implementation.
"""
from dataclasses import asdict
import numpy as np
from camadas_desbaste import planejar_camadas
from region_core import offset, signed_area, center_regions, boolean, pyclipr, SCALE
from stl_roughing import projected_shadow


def internal_profile_map(shadow,tracks):
    """Match compensated hole loops by full polygon containment, not centres."""
    holes=[p[::-1] for p in shadow if signed_area(p)<0]
    result=[]
    for hole in holes:
        result.append([p for p in tracks if signed_area(p)<0
                       and not boolean([p[::-1]],[hole],pyclipr.Difference)])
    return holes,result


def generate_cutout(triangles, *, diameter, tool_length, top, bottom, stepdown,
                    direction='climb', boundaries=None, exclusions=None, margin=.01,
                    contours='all',internal_indices=None):
    if direction not in ('climb','conventional'):
        raise ValueError('Sentido de fresagem inválido')
    if contours not in ('external','all'):
        raise ValueError('Seleção de contornos do Cutout inválida')
    if top-bottom>tool_length+1e-8:
        raise ValueError('Cutout excede o comprimento de corte da ferramenta')
    levels=planejar_camadas(bottom,bottom,top,stepdown)
    shadow=projected_shadow(np.asarray(triangles,float))
    tracks=offset(shadow,diameter/2)
    if not tracks:raise ValueError('Silhueta sem contorno usinável com esta fresa')
    holes=sum(signed_area(p)<0 for p in shadow)
    if internal_indices is None and contours=='all' and sum(signed_area(p)<0 for p in tracks)!=holes:
        tool_diameter=format(diameter,'.6g').replace('.',',')
        raise ValueError('Cutout: há contorno interno estreito demais para a fresa de diâmetro '
            +tool_diameter+" mm. Para apenas soltar a peça, selecione somente contornos externos (Soltar a peça · somente externo). Para usinar os internos, use uma fresa menor.")
    if internal_indices is not None:
        if (not isinstance(internal_indices,list) or any(type(i) is not int or not 0<=i<holes for i in internal_indices)
                or len(set(internal_indices))!=len(internal_indices)):
            raise ValueError('Índices de recortes internos inválidos')
        _,profiles=internal_profile_map(shadow,tracks)
        if any(len(profiles[i])!=1 for i in internal_indices):
            raise ValueError('Recorte interno automático não corresponde a um contorno compensado completo')
        tracks=[p for p in tracks if signed_area(p)>0]+[profiles[i][0] for i in internal_indices]
    elif contours=='external':tracks=[p for p in tracks if signed_area(p)>0]
    if not tracks:raise ValueError('Silhueta sem contorno externo usinável com esta fresa')
    # Hole loops (negative winding) are completed to full depth before outer
    # loops, so the surrounding part is still attached while machining holes.
    tracks.sort(key=lambda p:(signed_area(p)>=0,abs(signed_area(p))))
    if sum(len(p) for p in tracks)*len(levels)>250000:
        raise ValueError('Cutout excede o limite de 250.000 arestas')
    if boundaries is not None or exclusions:
        xy=np.concatenate(tracks)
        lo=xy.min(axis=0)-diameter*2;hi=xy.max(axis=0)+diameter*2
        domain=boundaries if boundaries is not None else [[lo,[hi[0],lo[1]],hi,[lo[0],hi[1]]]]
        allowed=center_regions(domain,exclusions or [],diameter,margin)
        for p in tracks:
            engine=pyclipr.Clipper();engine.scaleFactor=SCALE
            engine.addPath(np.vstack([p,p[0]]),pyclipr.Subject,True)
            if allowed:engine.addPaths(allowed,pyclipr.Clip)
            _,outside=engine.execute(pyclipr.Difference,pyclipr.FillRule.NonZero,returnOpenPaths=True)
            if any(np.linalg.norm(np.diff(q[:,:2],axis=0),axis=1).sum()>1e-6 for q in outside):
                raise ValueError('Cutout bloqueado pelas regiões: o contorno completo não cabe na área permitida')
    selection='automatic' if internal_indices is not None else contours
    layers=[];contour_records=[]
    for ci,p in enumerate(tracks):
        kind='internal' if signed_area(p)<0 else 'external'
        # Positive outer / negative hole winding puts material on the left;
        # reverse for climb with a clockwise spindle.
        if direction=='climb':p=p[::-1]
        # Stable start vertex on every level preserves exact cleared tracks.
        first=min(range(len(p)),key=lambda i:(p[i,1],p[i,0]))
        p=np.roll(p,-first,axis=0);p=np.vstack([p,p[0]])
        contour_records.append({'kind':kind,'points_xy':p.tolist(),'index':ci})
        for di,level in enumerate(levels):
            points=[[float(x),float(y),level.z] for x,y in p]
            layers.append({'z':level.z,'depth_index':di,'contour':ci,'contour_kind':kind,
                           'polylines':[{'points':points}]})
    edges=sum(len(p['points'])-1 for layer in layers for p in layer['polylines'])
    if edges>250000:raise ValueError('Cutout excede o limite de 250.000 arestas')
    result={'schema_version':1,'units':'mm','scope':'silhouette_2d_cutout',
        'tool':{'type':'flat_cylindrical','diameter':diameter,'length':tool_length},
        'parameters':{'z_top':top,'z_bottom':bottom,'stepdown':stepdown,'direction':direction},
        'contours_selection':selection,'internal_contours_total':holes,
        'skipped_internal_contours':holes-len(internal_indices) if internal_indices is not None else holes if selection=='external' else 0,
        'depth_levels':[asdict(v) for v in levels],'contours':contour_records,
        'layers':layers,'cutting_edges':edges,'order':'internal_contours_full_depth_then_external',
        'limitations':['Full projected silhouette, not variable-Z walls','No holding tabs or holder simulation']}
    if internal_indices is not None:result['selected_internal_indices']=list(internal_indices)
    return result
