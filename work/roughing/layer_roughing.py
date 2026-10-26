"""Layer-specific parallel cuts and cleanup contours, with OCL contact guards."""
from dataclasses import asdict
from concurrent.futures import ProcessPoolExecutor,as_completed
import math
import multiprocessing
import numpy as np
from layer_regions import free_layer_regions,region_area
from parallel_workers import geometry_workers


def _initialize_layer_workers(triangles,centers):
    global _worker_triangles,_worker_centers
    _worker_triangles=triangles
    _worker_centers=centers


def _layer_sources(triangles,centers,task):
    from stl_roughing import oriented_raster
    index,height,radius,conformal,stepover,phase,angle,cleanup,retained=task
    if retained is not None:
        from region_core import boolean,pyclipr
        centers=boolean(centers,retained,pyclipr.Intersection) if centers and retained else []
    regions=free_layer_regions(triangles,centers,height,radius,include_coplanar=conformal)
    rasters=oriented_raster(regions,stepover,phase,angle)
    sources=[('raster',s['row'],[s['start'],s['end']]) for s in rasters]
    if cleanup:
        sources.extend(('cleanup',None,np.vstack([loop,loop[0]]).tolist())
                       for loop in regions if len(loop)>=3)
    return index,{'regions':len(regions),'center_area_mm2':region_area(regions),
                  'shadow_plane_z':height,'polylines':[]},sources


def _layer_sources_worker(task):
    return _layer_sources(_worker_triangles,_worker_centers,task)


def prepare_layer_sources(triangles,centers,layers,*,radius,top,axial_allowance,
        strategy,stepover,phase,angle,cleanup,progress=None,retention=None):
    """Calculate independent layer polygons on separate CPU processes.

    Completion callbacks are made only in the caller process. Return values
    are restored to source order before contact or depth proofs, so worker
    scheduling cannot alter paths or credit future cuts as cleared material.
    """
    tasks=[];upper=top
    for index,layer in enumerate(layers):
        height=(upper if strategy=='conformal' else layer.z)-axial_allowance
        retained=(retention['center_regions_mm'] if retention is not None
                  and layer.z<retention['plane_z']-1e-8 else None)
        tasks.append((index,height,radius,strategy=='conformal',stepover,phase,angle,cleanup,retained))
        upper=layer.z
    workers=geometry_workers(len(tasks),len(triangles)*len(tasks))
    output=[None]*len(tasks)
    if workers==1:
        for completed,task in enumerate(tasks,1):
            result=_layer_sources(triangles,centers,task);output[result[0]]=result
            if progress:progress(f'Regiões de desbaste: camada {completed}/{len(tasks)}',completed/len(tasks))
    else:
        if progress:progress(f'Regiões de desbaste: iniciando {workers} processos',0)
        with ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context('spawn'),
                initializer=_initialize_layer_workers,initargs=(triangles,centers)) as pool:
            futures=[pool.submit(_layer_sources_worker,task) for task in tasks]
            for completed,future in enumerate(as_completed(futures),1):
                result=future.result();output[result[0]]=result
                if progress:progress(f'Regiões de desbaste: camada {completed}/{len(tasks)} · {workers} processos',completed/len(tasks))
    return output


def generate_layer_paths(triangles,centers,layers,*,diameter,tool_length,stepover,
        sampling,top,axial_allowance,radial_allowance,strategy,angle,phase,
        cleanup,compress,progress=None,retention=None,protected_overlap_mm=0.0,defer_depth_staging=False):
    # Import at call time: shared primitives live in the backwards-compatible
    # legacy engine, which dispatches here only for region_mode='layer'.
    from stl_roughing import contact_paths,simplify_collinear
    guard=sampling/2
    # Extra 0.005 mm exceeds Clipper round-arc chord error (0.001 mm) and
    # integer quantization. Contact is still independently evaluated below.
    radius=diameter/2+radial_allowance+guard+.005+protected_overlap_mm
    descriptors=[];queries=[];layer_metadata=[];upper=top
    if progress:progress('Calculando regiões por camada',0)
    prepared_layers=prepare_layer_sources(triangles,centers,layers,radius=radius,top=top,
        axial_allowance=axial_allowance,strategy=strategy,stepover=stepover,phase=phase,
        angle=angle,cleanup=cleanup,
        retention=retention,
        progress=(lambda phase,fraction:progress(phase,.2*fraction)) if progress else None)
    for index,metadata,sources in prepared_layers:
        layer=layers[index]
        layer_metadata.append(metadata)
        for kind,row,points in sources:
            start=len(queries)
            queries.extend({'start':a,'end':b} for a,b in zip(points,points[1:])
                           if math.dist(a,b)>1e-8)
            if len(queries)>100_000:raise ValueError('Layer path segment limit exceeded')
            if start<len(queries):descriptors.append((index,kind,row,start,len(queries),upper))
        upper=layer.z
    if progress:progress('Calculando contato da fresa com o STL',.22)
    contact=contact_paths(triangles,queries,diameter=diameter+2*radial_allowance+sampling,
        length=tool_length,sampling=sampling,
        floor=min(float(triangles[:,:,2].min()),layers[-1].z)-diameter-1,
        progress=(lambda phase,fraction:progress(phase,.22+.14*fraction)) if progress else None)
    if progress:progress('Montando passadas pelo contato da fresa',.38)
    raw_edges=0;report_every=max(1,len(descriptors)//200)
    for descriptor_index,(li,kind,row,start,end,upper) in enumerate(descriptors):
        chunks=contact['paths'][start:end]
        points=np.asarray(chunks[0]+[p for chunk in chunks[1:] for p in chunk[1:]],float)
        gaps=np.linalg.norm(np.diff(points[:,:2],axis=0),axis=1)
        if np.any(gaps>sampling+1e-7):raise RuntimeError('Layer contact gap exceeds sampling guard')
        h=points[:,2]+axial_allowance
        bounds=h.copy();edge=np.maximum(h[:-1],h[1:])
        bounds[:-1]=np.maximum(bounds[:-1],edge);bounds[1:]=np.maximum(bounds[1:],edge)
        closed=math.dist(points[0,:2],points[-1,:2])<1e-8
        if closed:bounds[0]=bounds[-1]=max(bounds[0],bounds[-1])
        if strategy=='conformal':
            z=np.maximum(bounds,layers[li].z)
            active=np.maximum(z[:-1],z[1:])<upper-1e-8
        else:
            z=np.full_like(bounds,layers[li].z)
            active=np.maximum(bounds[:-1],bounds[1:])<=layers[li].z+1e-10
        run=[]
        def flush():
            nonlocal run
            if not run:return
            result=simplify_collinear(run) if compress else run
            layer_metadata[li]['polylines'].append({'kind':kind,'row':row,'points':result,
                'closed':math.dist(result[0],result[-1])<1e-8})
            run=[]
        for i,enabled in enumerate(active):
            if enabled:
                if not run:run.append([*points[i,:2].tolist(),float(z[i])])
                run.append([*points[i+1,:2].tolist(),float(z[i+1])]);raw_edges+=1
                if raw_edges>1_000_000:raise ValueError('Layer cutting edge limit exceeded')
            else:flush()
        flush()
        if progress and ((descriptor_index+1)%report_every==0 or descriptor_index+1==len(descriptors)):
            progress(f'Montando passadas: {descriptor_index+1}/{len(descriptors)}',
                     .38+.12*(descriptor_index+1)/len(descriptors))
    output=[];upper=top
    for index,(layer,metadata) in enumerate(zip(layers,layer_metadata,strict=True)):
        output.append({'index':index,**asdict(layer),'upper_z':upper,**metadata})
        upper=layer.z
    from depth_staging import stage_paths
    preclear=(0 if defer_depth_staging else stage_paths(output,diameter=diameter,stock_top=top,
        stepdown=max(layer.passo for layer in layers),
        progress=(lambda phase,fraction:progress(phase,.5+.48*fraction)) if progress else None))
    paths=[p for layer in output for p in layer['polylines']]
    if progress:progress('Passadas de desbaste concluídas',1)
    return {'layers':output,'sampled_primary_cutting_edges':raw_edges,
        'preclear_cutting_edges':sum(len(p['points'])-1 for p in paths if p['kind']=='preclear'),
        'cutting_edges':sum(len(p['points'])-1 for p in paths),'preclear_polyline_count':preclear,
        'cutting_length_mm':sum(math.dist(a,b) for p in paths for a,b in zip(p['points'],p['points'][1:])),
        'polyline_count':len(paths),'cleanup_polyline_count':sum(p['kind']=='cleanup' for p in paths),
        'raster_polyline_count':sum(p['kind']=='raster' for p in paths),
        'layer_count':len(layers),'active_layer_count':sum(bool(l['polylines']) for l in output),
        'contact_samples':contact['samples'],'contact_engine':contact['engine'],
        'candidate_raster_segments':sum(d[1]=='raster' for d in descriptors),
        'sampling_guard_radius':guard,'contact_diameter':diameter+2*radial_allowance+sampling,
        'layer_region_guard_mm':.005,'collinear_maximum_deviation_mm':1e-10 if compress else 0}
