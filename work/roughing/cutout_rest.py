"""Skip complete cutout depth passes only with prior completed-cut proofs.

The original contours remain available for independent replay before export.
No keep-in/keep-out boundary, future cut or bounding box proves removal.
"""
import copy
import hashlib
import json


def _source_hash(layers,levels):
    encoded=json.dumps({'layers':layers,'depth_levels':levels},sort_keys=True,
                       separators=(',',':'),allow_nan=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _edge_count(layers):
    return sum(max(0,len(poly['points'])-1) for layer in layers for poly in layer['polylines'])


def adapt_cutout_to_prior(job,prior_motion):
    """Return a separate effective job; retain every partly uncleared contour.

    Material state is constructed once from the independently validated prior
    operation. Only whole depth passes can be omitted. This deliberately does
    not treat a thin remaining finishing allowance as already removed stock.
    """
    if prior_motion is None:raise ValueError('Cutout restante exige uma operação anterior validada')
    from motion_planner import build_prior_cut_state
    effective=copy.deepcopy(job)
    source=copy.deepcopy(job.get('rest_source_layers',job['layers']))
    levels=copy.deepcopy(job.get('rest_source_depth_levels',job['depth_levels']))
    state=build_prior_cut_state(prior_motion,job['tool'],job['parameters']['z_top'])
    cache={};remaining=[]
    for layer in source:
        cleared=bool(layer['polylines'])
        for poly in layer['polylines']:
            points=poly['points'];key=tuple(tuple(point) for point in points)
            if key not in cache:
                cache[key]=len(points)>=2 and all(state.covers_edge(a,b)
                                                 for a,b in zip(points,points[1:]))
            if not cache[key]:cleared=False;break
        if not cleared:remaining.append(layer)
    remaining_z={layer['z'] for layer in remaining}
    effective['layers']=remaining
    effective['depth_levels']=[level for level in levels if level['z'] in remaining_z]
    effective['cutting_edges']=_edge_count(remaining)
    effective['rest_source_layers']=source
    effective['rest_source_depth_levels']=levels
    effective['rest_material']={'applied':True,'input_depth_passes':len(source),
        'skipped_depth_passes':len(source)-len(remaining),'remaining_depth_passes':len(remaining),
        'prior_sha256':state.fingerprint,'source_geometry_sha256':_source_hash(source,levels)}
    return effective


def validate_cutout_rest(job,prior_motion):
    """Independently reconstruct the omitted passes from the original job."""
    if not isinstance(job.get('rest_material'),dict) or job['rest_material'].get('applied') is not True:
        raise ValueError('Cutout não contém uma adaptação de material anterior para conferir')
    if not isinstance(job.get('rest_source_layers'),list) or not isinstance(job.get('rest_source_depth_levels'),list):
        raise ValueError('Cutout restante perdeu as passadas originais para conferência')
    source=copy.deepcopy(job)
    source['layers']=copy.deepcopy(job['rest_source_layers'])
    source['depth_levels']=copy.deepcopy(job['rest_source_depth_levels'])
    for name in ('rest_material','rest_source_layers','rest_source_depth_levels'):source.pop(name,None)
    source['cutting_edges']=_edge_count(source['layers'])
    expected=adapt_cutout_to_prior(source,prior_motion)
    for name in ('layers','depth_levels','cutting_edges','rest_material'):
        if job.get(name)!=expected[name]:
            raise ValueError('Cutout restante foi alterado ou omite material sem prova de remoção anterior: '+name)
    return {'status':'passed','skipped_depth_passes':expected['rest_material']['skipped_depth_passes'],
        'prior_sha256':expected['rest_material']['prior_sha256'],
        'source_cutting_edges':source['cutting_edges']}
