"""Experimental top-down raster roughing driven by a real STL contact envelope.

Recovered layer scheduling + Clipper2 regions + OpenCAMLib flat-cutter contact.
Returns independent cutting polylines, not a complete machine program.
"""
from dataclasses import asdict,replace
from concurrent.futures import ThreadPoolExecutor,as_completed
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import numpy as np

from camadas_desbaste import planejar_camadas
from parallel_workers import geometry_workers
from region_core import (boolean,center_regions,normalize_solids,offset,
                         raster_segments,pyclipr)


def projected_shadow(triangles):
    paths=[]
    for triangle in triangles:
        p=triangle[:,:2]
        a,b=p[1]-p[0],p[2]-p[0]
        twice_area=float(a[0]*b[1]-a[1]*b[0])
        if abs(twice_area)>1e-10:
            paths.append(p if twice_area>0 else p[::-1])
    return boolean(paths,[],pyclipr.Union) if paths else []


def contact_paths(triangles,segments,*,diameter,length,sampling,floor,progress=None):
    if not segments:
        return {'paths':[],'samples':0,'engine':'not called: empty raster'}
    # Each independent Node process executes native OCL without the Python
    # GIL. Small requests stay serial to avoid startup/serialization overhead.
    # Keep the existing GLOBAL limits when splitting a request among workers.
    if len(triangles)>1_000_000 or len(segments)>100_000:
        raise ValueError('Prototype request limit exceeded')
    counts=[math.floor(math.dist(segment['start'],segment['end'])/sampling+1)+1
            for segment in segments]
    samples=sum(counts)
    if samples>1_000_000:raise ValueError('Prototype sample limit exceeded')
    workers=geometry_workers(len(segments),samples,minimum_work=120_000,minimum_tasks=32)
    if workers==1:
        return _contact_batch(triangles,segments,diameter=diameter,length=length,
                              sampling=sampling,floor=floor)
    # Contiguous, probe-balanced batches retain the exact original line/point
    # order, including duplicated junction points used by the layer assembler.
    batches=[];start=0;subtotal=0;target=math.ceil(samples/workers)
    for index,count in enumerate(counts):
        subtotal+=count
        if subtotal>=target and len(batches)<workers-1:
            batches.append((start,index+1));start=index+1;subtotal=0
    if start<len(segments):batches.append((start,len(segments)))
    paths=[None]*len(segments);completed_samples=0;engines=set()
    if progress:progress(f'Contato da fresa: {len(batches)} processos OpenCAMLib',0)
    with ThreadPoolExecutor(max_workers=len(batches),thread_name_prefix='ocl-native') as pool:
        futures={pool.submit(_contact_batch,triangles,segments[start:end],diameter=diameter,
            length=length,sampling=sampling,floor=floor):(start,end) for start,end in batches}
        for future in as_completed(futures):
            start,end=futures[future];result=future.result()
            paths[start:end]=result['paths'];completed_samples+=result['samples'];engines.add(result['engine'])
            if progress:progress(f'Contato da fresa: {completed_samples}/{samples} amostras · {len(batches)} processos',completed_samples/samples)
    if len(engines)!=1 or completed_samples!=samples:
        raise RuntimeError('As respostas paralelas de contato da fresa são inconsistentes.')
    return {'paths':paths,'samples':completed_samples,'engine':engines.pop()}


def _contact_batch(triangles,segments,*,diameter,length,sampling,floor):
    bundled=Path(sys._MEIPASS) if getattr(sys,'frozen',False) else None
    executable=str(bundled/'runtimes/node.exe') if bundled else shutil.which('node')
    if executable is None:
        raise RuntimeError('O motor de contato OpenCAMLib precisa do Node.js; reinstale o aplicativo completo.')
    request={'triangles':triangles.tolist(),'segments':segments,'diameter':diameter,
             'length':length,'sampling':sampling,'floor':floor}
    bridge=bundled/'work/roughing/ocl_contact_bridge.cjs' if bundled else Path(__file__).with_name('ocl_contact_bridge.cjs')
    try:
        response=subprocess.run([executable,str(bridge)],
            input=json.dumps(request).encode('utf8'),capture_output=True,timeout=60,check=False,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except subprocess.TimeoutExpired as error:
        raise RuntimeError('O cálculo de contato da fresa com o STL excedeu 60 segundos. '
            'Aumente a amostragem ou reduza a área/profundidade do desbaste e tente novamente.') from error
    if response.returncode:
        raise RuntimeError('OpenCAMLib adapter: '+response.stderr.decode('utf8',errors='replace')[-2000:])
    try:
        result=json.loads(response.stdout)
        if (not isinstance(result,dict) or not isinstance(result.get('paths'),list)
                or len(result['paths'])!=len(segments) or not isinstance(result.get('samples'),int)):
            raise ValueError('Formato de contato inválido')
        return result
    except (json.JSONDecodeError,UnicodeDecodeError,ValueError) as error:
        raise RuntimeError('O motor OpenCAMLib retornou uma resposta de contato inválida; '
                           'nenhum percurso foi exportado.') from error


def oriented_raster(regions,stepover,origin_y,angle_deg):
    """Rotate XY clipping space; all contact queries remain in model space."""
    angle=math.radians(angle_deg)
    matrix=np.array([[math.cos(angle),-math.sin(angle)],
                     [math.sin(angle), math.cos(angle)]])
    # Row-vector world -> raster = world @ matrix.
    local=[np.asarray(p)@matrix for p in regions]
    segments=raster_segments(local,stepover,origin_y)
    for segment in segments:
        for key in ('start','end'):
            segment[key]=(np.asarray(segment[key])@matrix.T).tolist()
    return segments


def simplify_collinear(points,epsilon=1e-10):
    """Merge straight forward runs, verifying every original vertex.

    The maximum deviation from each retained segment is <= epsilon mm.
    Reversals are preserved; this is not a surface-tolerance simplifier.
    """
    if len(points)<3:return points
    p=np.asarray(points,float);keep={0,len(p)-1};pending=[(0,len(p)-1)]
    # Check each proposed retained segment once. Long straight sampled raster
    # runs now take linear time instead of rescanning every growing prefix.
    # Every skipped original point must still be within epsilon, inside the
    # segment, and ordered along it; reversals cannot disappear.
    while pending:
        start,end=pending.pop()
        if end-start<2:continue
        vector=p[end]-p[start];squared=float(vector@vector)
        part=p[start:end+1]-p[start]
        if squared==0:
            split=start+int(np.argmax(np.linalg.norm(part,axis=1)))
            if split in (start,end):split=(start+end)//2
        else:
            fraction=part@vector/squared
            deviation=np.linalg.norm(part-fraction[:,None]*vector,axis=1)
            if (np.all(np.diff(fraction)>=0) and np.all(fraction>=0)
                    and np.all(fraction<=1) and float(deviation.max())<=epsilon):
                continue
            split=start+int(np.argmax(deviation))
            if float(deviation.max())<=epsilon:
                # A geometric line with reverse travel still needs its turn.
                reversal=np.flatnonzero(np.diff(fraction)<0)
                outside=np.flatnonzero((fraction<0)|(fraction>1))
                split=start+int(outside[0] if len(outside) else reversal[0])
            if split in (start,end):split=(start+end)//2
        keep.add(split);pending.extend(((start,split),(split,end)))
    return p[sorted(keep)].tolist()


def generate_stl_roughing(triangles,*,diameter,tool_length,stepdown,stepover,
                         sampling=0.2,z_top=None,z_bottom=None,tolerance=0.0,
                         radial_allowance=0.0,axial_allowance=0.0,
                         boundaries=None,exclusions=None,boundary_margin=0.01,
                         raster_origin_y=0.0,strategy='conformal',
                         raster_angle_deg=0.0,compress_collinear=False,
                         region_mode='projected',cleanup_contours=False,domain_mode='expanded',progress=None,
                         retention=None,center_domain=None,protected_overlap_mm=0.0,defer_depth_staging=False,annular_pockets=False,
                         surface_error=.15,path_tolerance=.02):
    """Generate top-down cutting polylines for a flat cylindrical cutter.

    In expanded mode an explicit physical `boundaries` region defines the
    stock-removal domain, eroded once for the actual cutter. Without a boundary
    the legacy domain is the projected mesh footprint expanded by the cutter
    radius. Silhouette mode clips to the projected footprint. `exclusions`
    are protected physical XY solids valid over the full depth.
    Radial/axial allowances are explicit conservative design parameters, not
    a recovered MeshCAM stockToLeave model. No travel/ramp links are returned.
    """
    if progress:progress('Preparando regiões de desbaste',0)
    triangles=np.asarray(triangles,dtype=float)
    if region_mode not in ('projected','layer') or domain_mode not in ('expanded','silhouette'):
        raise ValueError('Invalid region or domain mode')
    if type(cleanup_contours) is not bool or (cleanup_contours and region_mode!='layer'):
        raise ValueError('Cleanup contours require region_mode=layer')
    if strategy not in ('conformal','planar','hybrid'):
        raise ValueError('Strategy must be conformal, planar or hybrid')
    if not math.isfinite(surface_error) or surface_error<=0 or not math.isfinite(path_tolerance) or path_tolerance<0:
        raise ValueError('Invalid roughing approximation tolerance')
    if strategy=='hybrid' and region_mode!='layer':raise ValueError('Desbaste 3D eficiente exige regiões por camada')
    if isinstance(raster_angle_deg,bool) or not isinstance(raster_angle_deg,(int,float)) or not math.isfinite(raster_angle_deg) or not 0<=raster_angle_deg<180:
        raise ValueError('Raster angle must be finite and in [0,180) degrees')
    if type(compress_collinear) is not bool:
        raise ValueError('compress_collinear must be boolean')
    if triangles.ndim!=3 or triangles.shape[1:]!=(3,3) or not len(triangles) or not np.isfinite(triangles).all():
        raise ValueError('Expected a finite nonempty triangle array (n,3,3)')
    for name,value in [('diameter',diameter),('tool_length',tool_length),('sampling',sampling)]:
        if not math.isfinite(value) or value<=0:raise ValueError('Invalid '+name)
    for name,value in [('radial_allowance',radial_allowance),('axial_allowance',axial_allowance),('boundary_margin',boundary_margin),
                       ('protected_overlap_mm',protected_overlap_mm)]:
        if not math.isfinite(value) or value<0:raise ValueError('Invalid '+name)
    low=triangles.reshape(-1,3).min(axis=0);high=triangles.reshape(-1,3).max(axis=0)
    top=float(high[2]) if z_top is None else z_top
    bottom=float(low[2]) if z_bottom is None else z_bottom
    layers=planejar_camadas(float(low[2]),bottom,top,stepdown,tolerance)
    floors=[]
    if strategy=='hybrid':
        from rough_quality import horizontal_levels,include_floor_levels
        floors=horizontal_levels(triangles,top=top,bottom=layers[-1].z,axial_allowance=axial_allowance)
        layers=include_floor_levels(layers,floors,top,stepdown,
            extra_levels=[retention['plane_z']] if retention is not None else [])
    if retention is not None:
        if region_mode!='layer':raise ValueError('Retenção exterior exige regiões por camada')
        plane=retention['plane_z']
        if layers[-1].z<plane<top and not any(abs(layer.z-plane)<1e-8 for layer in layers):
            depths=sorted([layer.z for layer in layers]+[plane],reverse=True)
            upper=top;scheduled=[]
            for depth in depths:
                scheduled.append(replace(layers[0],z=depth,passo=upper-depth))
                upper=depth
            layers=scheduled
    shadow=projected_shadow(triangles)
    centers=offset(shadow,diameter/2+radial_allowance)
    if center_domain is not None:centers=[np.asarray(p,float) for p in center_domain]
    if domain_mode=='silhouette':centers=shadow
    if boundaries is not None:
        physical_centers=center_regions(boundaries,[],diameter,boundary_margin)
        centers=(physical_centers if domain_mode=='expanded' and center_domain is None else
                 boolean(centers,physical_centers,pyclipr.Intersection) if centers and physical_centers else [])
    if centers and exclusions:
        solids=boolean(normalize_solids(exclusions),[],pyclipr.Union)
        forbidden=offset(solids,diameter/2+boundary_margin)
        centers=boolean(centers,forbidden,pyclipr.Difference)
    if progress:progress('Regiões de desbaste preparadas',.06)
    if region_mode=='layer':
        from layer_roughing import generate_layer_paths
        result=generate_layer_paths(triangles,centers,layers,diameter=diameter,tool_length=tool_length,
            stepover=stepover,sampling=sampling,top=top,axial_allowance=axial_allowance,
            radial_allowance=radial_allowance,strategy=strategy,angle=raster_angle_deg,
            phase=raster_origin_y,cleanup=cleanup_contours,compress=compress_collinear,
            retention=retention,
            protected_overlap_mm=protected_overlap_mm,
            surface_error=surface_error,path_tolerance=path_tolerance,floors=floors,
            defer_depth_staging=defer_depth_staging,
            annular_pockets=annular_pockets,
            progress=(lambda phase,fraction:progress(phase,.06+.94*fraction)) if progress else None)
        result.update({'schema_version':1,'units':'mm','scope':'experimental_layer_shadow_roughing',
            'tool':{'type':'flat_cylindrical','diameter':diameter,'length':tool_length},
            'parameters':{'stepdown':stepdown,'stepover':stepover,'sampling':sampling,
                'z_top':top,'z_bottom':bottom,'tolerance':tolerance,'radial_allowance':radial_allowance,
                'axial_allowance':axial_allowance,'boundary_margin':boundary_margin,
                'raster_origin_y':raster_origin_y,'strategy':strategy,'raster_angle_deg':raster_angle_deg,
                'compress_collinear':compress_collinear,'region_mode':region_mode,
                'cleanup_contours':cleanup_contours,'domain_mode':domain_mode},
            'motion_links_included':False,'limitations':[
                'Conservative projected shadow and sampled contact; narrow regions may be omitted',
                'Only flat cylindrical cutter; no holder/body collision certificate',
                'No MeshCAM equivalence; stock envelope must match the declared setup']})
        if retention is not None:result['retention']=retention
        if annular_pockets:result['parameters']['annular_pockets']=True
        if strategy=='hybrid':
            from rough_quality import quality_spec
            result['parameters'].update(surface_error=surface_error,path_tolerance=path_tolerance)
            result['quality']=quality_spec(triangles,top=top,bottom=layers[-1].z,
                axial_allowance=axial_allowance,surface_error=surface_error,path_tolerance=path_tolerance)
        return result
    raster=oriented_raster(centers,stepover,raster_origin_y,raster_angle_deg)
    if progress:progress('Calculando contato da fresa com o STL',.12)
    # Nearest-probe disks cover a horizontal edge when the extra probe radius
    # is >= half its length. This guards against thin features between samples.
    guard=sampling/2
    contact_diameter=diameter+2*radial_allowance+2*guard
    contact=contact_paths(triangles,raster,diameter=contact_diameter,length=tool_length,
                          sampling=sampling,floor=min(float(low[2]),layers[-1].z)-diameter-1,
                          progress=(lambda phase,fraction:progress(phase,.12+.28*fraction)) if progress else None)
    if progress:progress('Montando passadas por camada',.45)
    prepared=[]
    for raster_segment,points in zip(raster,contact['paths'],strict=True):
        points=np.asarray(points,float)
        gaps=np.linalg.norm(np.diff(points[:,:2],axis=0),axis=1)
        if np.any(gaps>sampling+1e-8):raise RuntimeError('Contact sampling gap exceeds guard')
        h=points[:,2]+axial_allowance
        edge_bound=np.maximum(h[:-1],h[1:])
        vertex_bound=h.copy()
        vertex_bound[:-1]=np.maximum(vertex_bound[:-1],edge_bound)
        vertex_bound[1:]=np.maximum(vertex_bound[1:],edge_bound)
        prepared.append((raster_segment['row'],points[:,:2],vertex_bound))
    output_layers=[];upper=top;total_edges=0;cut_length=0.0
    for index,layer in enumerate(layers):
        polylines=[]
        for row,xy,bound in prepared:
            if strategy=='conformal':
                heights=np.maximum(bound,layer.z)
                active=np.maximum(heights[:-1],heights[1:])<upper-1e-8
            else:
                heights=np.full_like(bound,layer.z)
                # Whole-edge envelope is bounded by BOTH endpoint bounds.
                # Omit a cell rather than cut into a slope at constant Z.
                active=np.maximum(bound[:-1],bound[1:])<=layer.z+1e-10
            run=[]
            for edge,enabled in enumerate(active):
                if enabled:
                    if not run:run.append([*xy[edge].tolist(),float(heights[edge])])
                    run.append([*xy[edge+1].tolist(),float(heights[edge+1])])
                    total_edges+=1
                    if total_edges>1_000_000:raise ValueError('Prototype limit: 1,000,000 cutting edges')
                    cut_length+=math.dist(run[-2],run[-1])
                elif run:
                    polylines.append({'row':row,'points':run});run=[]
            if run:polylines.append({'row':row,'points':run})
        output_layers.append({'index':index,**asdict(layer),'upper_z':upper,'polylines':polylines})
        upper=layer.z
        if progress:progress(f'Montando passadas: camada {index+1}/{len(layers)}',.45+.45*(index+1)/len(layers))
    raw_edges=total_edges
    if compress_collinear:
        if progress:progress('Compactando segmentos colineares',.92)
        total_edges=0;cut_length=0.0
        for layer in output_layers:
            for poly in layer['polylines']:
                poly['points']=simplify_collinear(poly['points'])
                total_edges+=len(poly['points'])-1
                cut_length+=sum(math.dist(a,b) for a,b in zip(poly['points'],poly['points'][1:]))
    if progress:progress('Passadas de desbaste concluídas',1)
    return {'schema_version':1,'scope':'experimental_stl_height_envelope_raster',
        'units':'mm','tool':{'type':'flat_cylindrical','diameter':diameter,'length':tool_length},
        'parameters':{'stepdown':stepdown,'stepover':stepover,'sampling':sampling,
          'z_top':top,'z_bottom':bottom,'tolerance':tolerance,'radial_allowance':radial_allowance,
          'axial_allowance':axial_allowance,'boundary_margin':boundary_margin,'raster_origin_y':raster_origin_y,
          'strategy':strategy,'raster_angle_deg':raster_angle_deg,'compress_collinear':compress_collinear,
          'region_mode':region_mode,'cleanup_contours':cleanup_contours,'domain_mode':domain_mode},
        'uncompressed_cutting_edges':raw_edges,
        'collinear_maximum_deviation_mm':1e-10 if compress_collinear else 0,
        'sampling_guard_radius':guard,'contact_diameter':contact_diameter,
        'contact_engine':contact['engine'],'contact_samples':contact['samples'],
        'candidate_raster_segments':len(raster),'layer_count':len(layers),
        'active_layer_count':sum(bool(l['polylines']) for l in output_layers),
        'polyline_count':sum(len(l['polylines']) for l in output_layers),
        'cutting_edges':total_edges,'cutting_length_mm':cut_length,'layers':output_layers,
        'motion_links_included':False,
        'limitations':['No stock-removal simulation, entry/exit or travel/ramp planning',
          'Flat tip contact only; no holder/body collision certificate',
          'Conservative sampling envelope can omit narrow/deep reachable areas',
          'MeshCAM path/order/stock allowance equivalence not established']}
