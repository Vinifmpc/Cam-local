"""Deterministic stock-aware Rough -> external release planning.

Only geometry/depth/order are inferred. Cutting feeds, spindle, fixtures and
stock below the STL are not recovered from the mesh. The exterior retaining
skin is a physical constraint on source paths and on the replayed motions.
"""
from dataclasses import replace
import copy
import hashlib
import json
import math
import numpy as np


def exterior_strategy(triangles):
    """Diagnose the mesh in 3D without making a prep channel a prerequisite.

    A nominal profile outside the full projection cannot shape a taper or an
    undercut. Those remain the responsibility/limitation of the top-down 3D
    contact envelope. In particular, an open-edge recess must not trigger an
    otherwise unnecessary series of external profiles in Rough.
    """
    from types import SimpleNamespace
    from mesh_geometry import topology_report
    from region_core import boolean,offset,pyclipr,signed_area
    triangles=np.asarray(triangles,float)
    cross=np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0])
    lengths=np.linalg.norm(cross,axis=1);normal=cross/lengths[:,None]
    low=float(triangles[:,:,2].min());high=float(triangles[:,:,2].max())
    tolerance=1e-8
    horizontal=np.linalg.norm(normal[:,:2],axis=1)<=tolerance
    vertical=np.abs(normal[:,2])<=tolerance
    cap_at_extreme=(np.all(np.abs(triangles[:,:,2]-low)<=tolerance,axis=1)
                    |np.all(np.abs(triangles[:,:,2]-high)<=tolerance,axis=1))
    prismatic=bool(np.all(vertical|(horizontal&cap_at_extreme)))
    topology=topology_report(SimpleNamespace(triangles=triangles))
    volume=float(np.sum(np.einsum('ij,ij->i',triangles[:,0],
                                 np.cross(triangles[:,1],triangles[:,2])))/6)
    oriented=normal if volume>=0 else -normal
    down=(oriented[:,2]<-tolerance)&(triangles[:,:,2].max(axis=1)>low+tolerance)
    projected=[]
    for triangle in triangles[down]:
        path=triangle[:,:2];area=signed_area(path)
        if abs(area)>1e-12:projected.append(path if area>0 else path[::-1])
    downward=boolean(projected,[],pyclipr.Union) if projected else []
    # A quantified tessellation diagnostic, never a collision tolerance or a
    # license to cut an underside. Tiny nearly-vertical facets are common in
    # triangulated cylinders; retain their measured projection in the report.
    resolution=.005
    substantial=bool(offset(downward,-resolution)) if downward else False
    possible_undercut=(substantial if topology['closed_consistent_edges'] else None)
    return {'mode':'features_then_cutout','external_prismatic':prismatic,
        'reason':'O Rough calcula os rebaixos e bolsões pela geometria 3D, inclusive os abertos à borda; '
                 'o perfil externo completo fica para o Cutout.',
        'proof':{'method':'3d_facets_diagnostic_and_independent_motion_replay',
            'nominal_profile_outside_full_mesh_projection':True,
            'rough_keeps_layer_shadows_and_ocl_contact':True,
            'preparation_required_by_exterior_variation':False,
            'constant_prismatic_facets':prismatic,
            'closed_consistent_edges':topology['closed_consistent_edges'],
            'nonvertical_nonhorizontal_faces':int(np.count_nonzero(~vertical&~horizontal)),
            'downward_nonbase_faces':int(np.count_nonzero(down)),
            'downward_projection_area_mm2':sum(signed_area(p) for p in downward),
            'possible_undercut':possible_undercut,'diagnostic_resolution_mm':resolution,
            'scope':'Acessibilidade diagnosticada em facetas 3D; contato e movimentos são conferidos separadamente'}}


def resolve_smart_plan(mesh,tool,settings,options):
    if options.machining_mode!='smart':return settings,options,None
    triangles=np.asarray(mesh.triangles if hasattr(mesh,'triangles') else mesh,float)
    model_bottom=float(triangles[:,:,2].min())
    stock_bottom=model_bottom if options.smart_stock_bottom_mm is None else options.smart_stock_bottom_mm
    if stock_bottom>model_bottom+1e-8:
        raise ValueError('Modo inteligente: fundo do bruto deve ficar no fundo do STL ou abaixo dele')
    stock_bottom=min(float(stock_bottom),model_bottom)
    skin=(min(.5,settings.stepdown_mm,.2*tool.diameter_mm,
              (settings.stock_top_mm-stock_bottom)/4)
          if options.smart_skin_mm is None else float(options.smart_skin_mm))
    if skin>=settings.stock_top_mm-stock_bottom:
        raise ValueError('Modo inteligente: pele de retenção deve ser menor que a espessura do bruto')
    cutout_bottom=stock_bottom-options.smart_breakthrough_mm
    effective=replace(settings,bottom_mm=model_bottom,region_mode='layer',domain_mode='expanded',cleanup_contours=True,
        boundaries_mm=settings.boundaries_mm or None)
    # Keep the resolved stock depth explicit: the existing reach and export
    # contracts then validate exactly the depth used for the release.
    resolved=replace(options,smart_stock_bottom_mm=stock_bottom,
        cutout_bottom_mm=cutout_bottom,
        cutout_stepdown_mm=min(options.cutout_stepdown_mm,settings.stepdown_mm))
    from cam_operations import validate_operations
    validate_operations(resolved,effective,tool)
    assumptions=[]
    if options.smart_stock_bottom_mm is None:
        assumptions.append('Fundo do bruto assumido igual ao fundo do STL; ajuste se o bruto for mais espesso.')
    if stock_bottom<model_bottom-1e-8:
        assumptions.append(f'Bruto {model_bottom-stock_bottom:g} mm abaixo do STL: esse material sob a peça '
            'e os furos permanece; o Cutout externo libera o conjunto e não usina a face inferior.')
    assumptions.extend([
        'Keep In e Keep Out continuam limitando somente o Rough; o Cutout usa todos os contornos externos.',
        'A pele exterior permanece até o Cutout; furos e bolsões internos continuam até o fundo do Rough.',
        'O recorte final libera a peça do bruto; a geometria não informa fixação, grampos ou mesa de sacrifício.',
        'Avanços e RPM usam exclusivamente os valores cadastrados.'])
    report={'enabled':True,'sequence':resolved.sequence(),
        'allow_center_plunge':options.drill_center_cutting,
        'stock_bottom_mm':stock_bottom,'model_bottom_mm':model_bottom,
        'roughing_bottom_mm':model_bottom,'cutout_bottom_mm':cutout_bottom,
        'retention_z_mm':stock_bottom+skin,'skin_mm':skin,
        'skin_source':'automatic' if options.smart_skin_mm is None else 'configured',
        'stock_bottom_source':'model' if options.smart_stock_bottom_mm is None else 'configured',
        'cutout_stepdown_mm':resolved.cutout_stepdown_mm,
        'roughing_stepdown_mm':effective.stepdown_mm,
        'breakthrough_mm':options.smart_breakthrough_mm,
        'respect_roughing_regions':True,'release_contours':'external',
        'assumptions':assumptions}
    report['exterior_strategy']=exterior_strategy(triangles)
    if report['exterior_strategy']['proof']['possible_undercut']:
        assumptions.append('A malha contém superfícies inferiores acima do fundo que podem ficar '
            'inacessíveis por cima. O Rough conserva o envelope de contato; o Cutout nominal '
            'não faz acabamento dessas superfícies.')
    if options.drill_center_cutting:
        assumptions.append('Entradas curtas podem usar descida vertical controlada porque '
                           'o corte pelo centro da ferramenta está confirmado.')
    report['automatic_regions']=automatic_regions(triangles,tool,effective)
    report['preparation_contours']=preparation_spec(triangles,tool,effective,resolved,report)
    unreachable=report['automatic_regions']['rough_unreachable_projected_openings']
    if unreachable:
        assumptions.append(f'O Rough não alcança {unreachable} abertura(s) interna(s) com seu envelope '
            'conservador; confira a compatibilidade do Drill ou utilize uma ferramenta menor.')
    if settings.radial_allowance_mm or settings.axial_allowance_mm:
        assumptions.append('O perfil externo de preparação segue a dimensão nominal; '
            'as sobras lateral e de fundo cadastradas continuam nas demais superfícies do Rough.')
    from layer_regions import shadow_above
    from stl_roughing import projected_shadow
    from region_core import boolean,pyclipr,signed_area
    filled=lambda paths:boolean([p for p in paths if signed_area(p)>0],[],pyclipr.Union) if paths else []
    full=filled(projected_shadow(triangles))
    upper=filled(shadow_above(triangles,report['retention_z_mm']))
    difference=boolean(full,upper,pyclipr.Difference) if full and upper else full
    variation=sum(signed_area(p) for p in difference)
    report['retention_band_outer_variation_mm2']=variation
    if variation>1e-5:
        assumptions.append('Paredes inclinadas na faixa de retenção podem conservar sobremetal; '
                           'o Cutout externo não faz acabamento 3D nessa faixa.')
    if report['preparation_contours']['blocked']:
        assumptions.append('Uma região Keep In ou Keep Out bloqueia a preparação de contorno externo; '
                           'o Cutout manterá as passadas necessárias nesses contornos.')
    return effective,resolved,report


def automatic_regions(triangles,tool,settings):
    """Effective center domain follows the part, including its concavities.

    The offset exactly matches the conservative layer-protection radius. A
    vertical external face therefore creates no exterior raster strip. The
    layer shadows and OCL retain the 3D feature logic. The nominal external
    channel belongs to Cutout unless a later strategy explicitly requires it.
    """
    from stl_roughing import projected_shadow
    from region_core import boolean,offset,pyclipr,signed_area,center_regions
    shadow=projected_shadow(np.asarray(triangles,float))
    outer=[p for p in shadow if signed_area(p)>0]
    filled=boolean(outer,[],pyclipr.Union) if outer else []
    distance=tool.diameter_mm/2+settings.radial_allowance_mm+settings.sampling_mm/2+.005
    overlap=.005
    domain=offset(filled,distance) if filled else []
    if settings.boundaries_mm:
        allowed=center_regions(settings.boundaries_mm,[],tool.diameter_mm,settings.boundary_margin_mm)
        domain=boolean(domain,allowed,pyclipr.Intersection) if domain and allowed else []
    if domain and settings.exclusions_mm:
        forbidden=offset(boolean(settings.exclusions_mm,[],pyclipr.Union),
                         tool.diameter_mm/2+settings.boundary_margin_mm)
        domain=boolean(domain,forbidden,pyclipr.Difference)
    area=sum(signed_area(p) for p in domain)
    points=np.concatenate(domain) if domain else None
    holes=[p for p in shadow if signed_area(p)<0]
    unreachable=[index for index,path in enumerate(holes) if not offset([path[::-1]],-distance-overlap)]
    return {'source':'filled_external_silhouette','policy_version':1,
        'polygons_mm':[np.asarray(p,float).tolist() for p in domain],
        'area_mm2':area,'offset_mm':distance,
        'bounds_mm':([*points.min(axis=0).tolist(),*points.max(axis=0).tolist()] if domain else None),
        'manual_limits_applied':bool(settings.boundaries_mm or settings.exclusions_mm),
        'exterior_components':sum(signed_area(p)>0 for p in domain),
        'projected_internal_openings':len(holes),
        'rough_unreachable_projected_openings':len(unreachable),
        'rough_unreachable_opening_indices':unreachable,
        'quantized_boundary_overlap_mm':overlap,
        'protected_center_offset_mm':distance+overlap,
        'access_policy':'cleanup_then_raster',
        'exterior_raster_collar_mm':0.0}


def _nominal_cutout(triangles,tool,settings,options):
    from cutout import generate_cutout
    return generate_cutout(triangles,diameter=tool.diameter_mm,tool_length=tool.cutting_length_mm,
        top=settings.stock_top_mm,bottom=options.cutout_bottom_mm,
        stepdown=options.cutout_stepdown_mm,direction=options.cutout_direction,contours='external')


def preparation_spec(triangles,tool,settings,options,report):
    if report['exterior_strategy']['mode']=='features_then_cutout':
        return {'eligible':0,'blocked':0,'eligible_contour_indices':[],
            'blocked_contour_indices':[],'levels_mm':[],'depth_count':0,'depth_min_mm':None,
            'retention_depth_added':False,'source_sha256':hashlib.sha256(b'[]').hexdigest(),
            'method':'not_required_for_features_then_cutout','not_required':True}
    job=_nominal_cutout(triangles,tool,settings,options)
    plane=report['retention_z_mm']
    levels=sorted({float(level['z']) for level in job['depth_levels'] if level['z']>=plane-1e-8},reverse=True)
    added=not any(abs(z-plane)<1e-8 for z in levels)
    if added:levels=sorted(levels+[plane],reverse=True)
    domain=report['automatic_regions']['polygons_mm'];eligible=[];blocked=[]
    for contour in job['contours']:
        points=[[x,y,settings.stock_top_mm-1] for x,y in contour['points_xy']]
        permitted=all(_edge_in_domain(a,b,domain) for a,b in zip(points,points[1:]))
        (eligible if permitted else blocked).append(contour['index'])
    fingerprint=hashlib.sha256(json.dumps({'contours':job['contours'],'levels_mm':levels},
        sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return {'eligible':len(eligible),'blocked':len(blocked),'eligible_contour_indices':eligible,
        'blocked_contour_indices':blocked,'levels_mm':levels,'depth_count':len(levels),
        'depth_min_mm':min(levels) if eligible else None,
        'retention_depth_added':added,'source_sha256':fingerprint,
        'method':'nominal_external_cutout_profiles_above_retention_plane'}


def _preparation_paths(triangles,tool,settings,options,report):
    spec=report['preparation_contours']
    if not spec['eligible_contour_indices']:return []
    job=_nominal_cutout(triangles,tool,settings,options)
    paths=[]
    for z in spec['levels_mm']:
        for contour in job['contours']:
            if contour['index'] not in spec['eligible_contour_indices']:continue
            paths.append({'kind':'preparation','smart_profile_index':contour['index'],
                'smart_profile_z':z,'closed':True,
                'points':[[float(x),float(y),z] for x,y in contour['points_xy']]})
    return paths


def add_preparation_contours(job,triangles,tool,settings,options,report,progress=None):
    """Order primary geometry; append profiles only when the strategy asks."""
    if report is None:return job
    paths=_preparation_paths(triangles,tool,settings,options,report)
    layers=copy.deepcopy(job['layers'])
    for layer in layers:
        # Restage the new schedule from primary geometry. Auxiliary passes
        # from a former raster-first schedule must not survive as wasted cuts.
        layer['polylines']=[p for p in layer['polylines'] if p['kind'] not in ('preclear','preparation')]
    for path in paths:
        z=path['smart_profile_z']
        layer=next((layer for layer in layers if abs(layer['z']-z)<1e-8),None)
        if layer is None:
            layer={'z':z,'polylines':[],'regions':0,'center_area_mm2':0,'shadow_plane_z':z}
            layers.append(layer)
        layer['polylines'].append(path)
    layers.sort(key=lambda layer:layer['z'],reverse=True)
    upper=settings.stock_top_mm
    for index,layer in enumerate(layers):
        layer.update(index=index,upper_z=upper,passo=upper-layer['z'])
        layer['polylines'].sort(key=lambda p:0 if p['kind']=='preparation' else 1 if p['kind']=='cleanup' else 2)
        upper=layer['z']
    from depth_staging import stage_paths
    stage_paths(layers,diameter=tool.diameter_mm,stock_top=settings.stock_top_mm,
                stepdown=settings.stepdown_mm,progress=progress)
    job['layers']=layers
    all_paths=[p for layer in layers for p in layer['polylines']]
    job.update({'automatic_regions':report['automatic_regions'],
        'preparation_contours':report['preparation_contours'],
        'layer_count':len(layers),'active_layer_count':sum(bool(layer['polylines']) for layer in layers),
        'polyline_count':len(all_paths),'cutting_edges':sum(len(p['points'])-1 for p in all_paths),
        'cutting_length_mm':sum(math.dist(a,b) for p in all_paths for a,b in zip(p['points'],p['points'][1:])),
        'preparation_polyline_count':len(paths),
        'preparation_cutting_edges':sum(len(p['points'])-1 for p in paths),
        'preclear_polyline_count':sum(p['kind']=='preclear' for p in all_paths),
        'preclear_cutting_edges':sum(len(p['points'])-1 for p in all_paths if p['kind']=='preclear')})
    return job


def retention_parameters(triangles,tool,settings,report):
    if report is None:return None
    from stl_roughing import projected_shadow
    from region_core import boolean,offset,pyclipr,signed_area
    # Drop negative hole loops deliberately: retaining an outside skin must
    # not prohibit completing the internal holes. Positive exterior loops also
    # include separate components; union keeps their filled physical domains.
    outer=[p for p in projected_shadow(np.asarray(triangles,float)) if signed_area(p)>0]
    filled=boolean(outer,[],pyclipr.Union) if outer else []
    guard=settings.sampling_mm/2+settings.boundary_margin_mm+.005
    centers=offset(filled,-tool.diameter_mm/2-guard) if filled else []
    return {'plane_z':report['retention_z_mm'],'skin_mm':report['skin_mm'],
        'stock_bottom_mm':report['stock_bottom_mm'],
        'center_guard_mm':guard,'scope':'exterior_only_filled_silhouette',
        'center_regions_mm':[np.asarray(p,float).tolist() for p in centers]}


def _point_inside(point,regions):
    # Winding test, accepting the quantized boundary. Holes in the eroded
    # domain retain their winding, including any offset-created components.
    winding=0;x,y=point
    for path in regions:
        for a,b in zip(path,path[1:]+path[:1]):
            dx=b[0]-a[0];dy=b[1]-a[1]
            cross=dx*(y-a[1])-dy*(x-a[0])
            if (abs(cross)<=2e-6*max(1,math.hypot(dx,dy))
                    and min(a[0],b[0])-2e-6<=x<=max(a[0],b[0])+2e-6
                    and min(a[1],b[1])-2e-6<=y<=max(a[1],b[1])+2e-6):return True
            if a[1]<=y<b[1] and cross>0:winding+=1
            elif b[1]<=y<a[1] and cross<0:winding-=1
    return winding!=0


def _edge_retained(a,b,retention):
    plane=retention['plane_z'];regions=retention['center_regions_mm']
    if min(a[2],b[2])>=plane-1e-8:return True
    a=np.asarray(a,float);b=np.asarray(b,float)
    # Only the portion physically below the retaining plane is constrained.
    if a[2]>=plane:a=a+(b-a)*((plane-a[2])/(b[2]-a[2]))
    elif b[2]>=plane:b=a+(b-a)*((plane-a[2])/(b[2]-a[2]))
    return _edge_in_domain(a,b,regions)


def _edge_in_domain(a,b,regions):
    if not regions or not _point_inside(a[:2],regions) or not _point_inside(b[:2],regions):return False
    if math.dist(a[:2],b[:2])<1e-8:return True
    from region_core import pyclipr,SCALE
    clip=pyclipr.Clipper();clip.scaleFactor=SCALE
    clip.addPath([a[:2],b[:2]],pyclipr.Subject,True)
    clip.addPaths(regions,pyclipr.Clip)
    _,outside=clip.execute(pyclipr.Difference,pyclipr.FillRule.NonZero,returnOpenPaths=True)
    if sum(sum(math.dist(u,v) for u,v in zip(p,p[1:])) for p in outside)<=2e-6:return True
    # Contact sampling can split an exact polygon edge at a half-grid XY.
    # Clipper rounds that midpoint to its integer grid and may classify the
    # whole open edge outside. Prove the ORIGINAL float segment is covered by
    # polygon-boundary intervals at the existing two-grid-unit point tolerance;
    # never accept a concavity shortcut or expand the allowed physical region.
    direction=np.asarray(b[:2])-a[:2];squared=float(direction@direction)
    intervals=[];quantization=2/SCALE
    for path in regions:
        for u,v in zip(path,path[1:]+path[:1]):
            du=np.asarray(u)-a[:2];dv=np.asarray(v)-a[:2]
            tu=float(du@direction/squared);tv=float(dv@direction/squared)
            lo=max(0,min(tu,tv));hi=min(1,max(tu,tv))
            if hi<lo:continue
            edge=np.asarray(v)-u;edge_squared=float(edge@edge)
            if edge_squared==0:continue
            def boundary_distance(t):
                point=np.asarray(a[:2])+t*direction
                fraction=float((point-u)@edge/edge_squared)
                return float(np.linalg.norm(point-(np.asarray(u)+fraction*edge)))
            if max(boundary_distance(lo),boundary_distance(hi))<=quantization:
                intervals.append((lo,hi))
    covered=0.0
    for lo,hi in sorted(intervals):
        if lo>covered+quantization/max(1,math.sqrt(squared)):return False
        covered=max(covered,hi)
        if covered>=1:return True
    return False


def edge_in_automatic_domain(a,b,automatic,stock_top):
    return _edge_retained(a,b,{'plane_z':stock_top,'center_regions_mm':automatic['polygons_mm']})


def validate_smart_geometry(job,triangles,tool,settings,options,report,motion=None):
    if report is None:return
    automatic=automatic_regions(triangles,tool,settings)
    spec=preparation_spec(triangles,tool,settings,options,report)
    if job.get('automatic_regions')!=automatic or job.get('preparation_contours')!=spec:
        raise ValueError('Áreas automáticas ou preparação do perfil mudaram; recalcule')
    expected=_preparation_paths(triangles,tool,settings,options,report)
    actual=[p for layer in job['layers'] for p in layer['polylines'] if p.get('kind')=='preparation']
    order=lambda p:(-p['smart_profile_z'],p['smart_profile_index'])
    if sorted(actual,key=order)!=sorted(expected,key=order):
        raise ValueError('Perfil de preparação do Rough não corresponde ao STL')
    cache={}
    def contained(a,b):
        key=tuple(sorted((tuple(a[:2]),tuple(b[:2]))))
        if key not in cache:cache[key]=_edge_in_domain(a,b,automatic['polygons_mm'])
        return cache[key]
    for layer in job['layers']:
        for path in layer['polylines']:
            for a,b in zip(path['points'],path['points'][1:]):
                if not contained(a,b):
                    raise ValueError('Rough fora das áreas automáticas da peça')
    if motion is not None:
        for move in motion['moves']:
            a,b=move['start'],move['end'];plane=settings.stock_top_mm
            if min(a[2],b[2])>=plane-1e-8:continue
            if a[2]>=plane:
                a=np.asarray(a)+(np.asarray(b)-a)*((plane-a[2])/(b[2]-a[2]))
            elif b[2]>=plane:
                b=np.asarray(a)+(np.asarray(b)-a)*((plane-a[2])/(b[2]-a[2]))
            if not contained(a,b):
                raise ValueError('Movimento do Rough fora das áreas automáticas da peça')


def validate_smart_retention(job,triangles,tool,settings,report,motion=None):
    expected=retention_parameters(triangles,tool,settings,report)
    if job.get('retention')!=expected:
        raise ValueError('Retenção inteligente mudou; recalcule antes de exportar')
    if expected is None:return
    for layer in job['layers']:
        for path in layer['polylines']:
            for a,b in zip(path['points'],path['points'][1:]):
                if not _edge_retained(a,b,expected):
                    raise ValueError('Rough atravessa a pele exterior de retenção')
    if motion is not None:
        for move in motion['moves']:
            if not _edge_retained(move['start'],move['end'],expected):
                raise ValueError('Movimento do Rough atravessa a pele exterior de retenção')
