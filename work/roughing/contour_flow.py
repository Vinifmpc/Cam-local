"""Conservative, one-sided simplification of compensated cutout contours.

Positive outer loops and negative holes bound protected material on the left.
Candidates may leave more material, within the supplied XY tolerance; they may
never remove protected material. All acceptance proofs use the existing local
Clipper geometry, with a small additional guard against its coordinate grid.
"""
import math
import numpy as np

from region_core import SCALE,boolean,offset,pyclipr,signed_area
from rough_quality import simplify_allowed_loop


# Covers the XY rounding bound of the five-decimal NC coordinates, plus
# Clipper's integer grid and the existing edge-domain boundary tolerance.
PROTECTED_GUARD_MM=.00002


def _solid(path):
    return path if signed_area(path)>0 else path[::-1]


def _match_loops(original,candidate):
    """Keep each winding/identity under material expansion, including islands."""
    if len(original)!=len(candidate):return None
    matches=[]
    for path in original:
        positive=signed_area(path)>0
        choices=[]
        for index,other in enumerate(candidate):
            if (signed_area(other)>0)!=positive:continue
            # Outer boundaries expand; the enclosed voids of holes shrink.
            subjects,clips=([path],[other]) if positive else ([_solid(other)],[_solid(path)])
            if not boolean(subjects,clips,pyclipr.Difference):
                choices.append((abs(signed_area(other)),index))
        if not choices:return None
        # Nested islands are matched to their smallest containing outer;
        # nested holes to the largest contained void, not a descendant hole.
        matches.append((min(choices) if positive else max(choices))[1])
    if len(set(matches))!=len(original):return None
    return [candidate[index] for index in matches]


def simplify_cutout_tracks(tracks,tolerance_mm):
    """Return np-array loops and a deterministic, JSON-serializable report.

    A failed geometric or topology proof returns copies of the original loops.
    An explicit repeated endpoint, input loop order, and winding are preserved.
    """
    tolerance=float(tolerance_mm)
    if not math.isfinite(tolerance) or tolerance<0:
        raise ValueError('Cutout smoothing tolerance must be finite and nonnegative')
    original=[np.asarray(path,dtype=float).copy() for path in tracks]
    if any(path.ndim!=2 or path.shape[1]!=2 or len(path)<3
           or not np.isfinite(path).all() for path in original):
        raise ValueError('Expected finite closed XY cutout polygons')
    closed=[bool(np.array_equal(path[0],path[-1])) for path in original]
    loops=[path[:-1] if repeated else path for path,repeated in zip(original,closed)]
    before=sum(len(path) for path in loops)
    report={'method':'one_sided_offset_simplification','tolerance_mm':tolerance,
            'effective_tolerance_mm':0.,'vertices_before':before,'vertices_after':before,
            'applied':False,'reason':'disabled','fallback_reason':None}

    def fallback(reason):
        report['reason']=reason
        report['fallback_reason']=reason if reason not in ('disabled','empty') else None
        return original,report

    if tolerance==0:return fallback('disabled')
    if not loops:return fallback('empty')
    if any(len(path)<3 for path in loops):return fallback('degenerate_input')
    # Work relative to the geometry, so a translated work datum does not
    # alter cancellation in area tests or Clipper's effective XY resolution.
    origin=np.concatenate(loops).min(axis=0)
    source=[path-origin for path in loops]
    if any(abs(signed_area(path))<1/SCALE**2 for path in source):
        return fallback('degenerate_input')
    if tolerance<=16/SCALE:return fallback('tolerance_below_geometry_resolution')
    try:
        canonical=boolean(source,[],pyclipr.Union)
        canonical=_match_loops(source,canonical)
        if canonical is None:return fallback('input_topology_changed')
        for path,other in zip(source,canonical):
            if boolean([_solid(other)],[_solid(path)],pyclipr.Difference):
                return fallback('input_topology_changed')
        shifted=_match_loops(source,offset(source,tolerance*.5))
        if shifted is None:return fallback('offset_topology_changed')
        bound=_match_loops(source,offset(source,tolerance))
        if bound is None:return fallback('tolerance_offset_topology_changed')
        # Keep extra clearance for the final five-decimal NC coordinates.
        # The .001 mm arc tolerance of region_core.offset is accounted for by
        # proving against its actual result, rather than assuming an ideal arc.
        protected=offset(source,PROTECTED_GUARD_MM)
        points=np.concatenate(source);low=points.min(axis=0);high=points.max(axis=0)
        margin=max(1.,tolerance*4)
        frame=np.array([[low[0]-margin,low[1]-margin],[high[0]+margin,low[1]-margin],
                        [high[0]+margin,high[1]+margin],[low[0]-margin,high[1]+margin]])
        domain=boolean([frame],protected,pyclipr.Difference)
        allowed=[np.asarray(path,float).tolist() for path in domain]
        candidate=[]
        for path in shifted:
            simple=np.asarray(simplify_allowed_loop(path,allowed,tolerance*.4),float)
            if len(simple)>1 and np.array_equal(simple[0],simple[-1]):simple=simple[:-1]
            if len(simple)<3 or not np.isfinite(simple).all():return fallback('degenerate_candidate')
            candidate.append(simple)
        # Test the exact coordinates returned to the caller after reapplying
        # the work datum, including the floating-point round trip.
        result=[path+origin for path in candidate]
        candidate=[path-origin for path in result]
        matched=_match_loops(source,candidate)
        if matched is None or any(not np.array_equal(a,b) for a,b in zip(candidate,matched)):
            return fallback('candidate_topology_changed')
        normalized=boolean(candidate,[],pyclipr.Union)
        normalized=_match_loops(candidate,normalized)
        if normalized is None:return fallback('candidate_topology_changed')
        for path,other in zip(candidate,normalized):
            if boolean([_solid(other)],[_solid(path)],pyclipr.Difference):
                return fallback('candidate_topology_changed')
        if boolean(source,candidate,pyclipr.Difference):return fallback('protected_region_changed')
        if boolean(protected,candidate,pyclipr.Difference):return fallback('quantization_guard_failed')
        if boolean(candidate,bound,pyclipr.Difference):return fallback('tolerance_bound_failed')
        from smart_planner import _edge_in_domain
        for path in candidate:
            if any(not _edge_in_domain(a,b,allowed) for a,b in zip(path,np.roll(path,-1,axis=0))):
                return fallback('edge_in_protected_region')
        after=sum(len(path) for path in candidate)
        if after>=before:return fallback('no_vertex_reduction')
        result=[np.vstack([path,path[0]]) if repeated else path
                for path,repeated in zip(result,closed)]
        report.update({'applied':True,'reason':'applied','effective_tolerance_mm':tolerance,
                       'vertices_after':after})
        return result,report
    except (ValueError,RuntimeError,OverflowError):
        return fallback('geometry_proof_failed')
