"""Delegate profitable through openings to complete internal profiles.

A hole in the full XY projection is empty of final-part material at EVERY
height. Blind pockets have a projected floor and never qualify. Rough is
excluded from the delegated core; it does not receive fictitious clearance.
"""
import math
from types import SimpleNamespace
import numpy as np
from region_core import boolean,offset,pyclipr,signed_area
from stl_roughing import projected_shadow
from cutout import internal_profile_map
from mesh_geometry import topology_report


def plan_internal_cutouts(triangles,tool,settings,options):
    triangles=np.asarray(triangles,float)
    shadow=projected_shadow(triangles)
    holes,profiles=internal_profile_map(shadow,offset(shadow,tool.diameter_mm/2))
    closed=topology_report(SimpleNamespace(triangles=triangles))['closed_consistent_edges']
    guard=settings.sampling_mm/2+.005
    # Exclude centres whose ACTUAL cutter is wholly within the through void.
    # The sampling envelope belongs to the final-part contact protection, not
    # to this waste decision; including it leaves narrow pointless rasters
    # between the delegated core and the protected wall.
    distance=tool.diameter_mm/2+.005
    rough_depth=settings.stock_top_mm-float(triangles[:,:,2].min())
    cut_depth=settings.stock_top_mm-options.cutout_bottom_mm
    rough_levels=max(1,math.ceil(rough_depth/settings.stepdown_mm))
    cut_levels=max(1,math.ceil(cut_depth/options.cutout_stepdown_mm))
    rough_feed=options.roughing_feed_mm_min or tool.feed_mm_min
    cut_feed=options.cutout_feed_mm_min or tool.feed_mm_min
    # Missing feeds still permit a geometric comparison without inventing
    # machining parameters. Only measured feeds produce a time estimate.
    features=[]
    allowed=None
    if options.smart_part_released:
        from region_core import center_regions
        from smart_planner import _edge_in_domain
        outer=[p for p in shadow if signed_area(p)>0]
        guard_mm=settings.boundary_margin_mm+options.cutout_smoothing_mm
        allowed=center_regions(outer,settings.exclusions_mm or [],tool.diameter_mm,guard_mm)
        if settings.boundaries_mm:
            limits=center_regions(settings.boundaries_mm,[],tool.diameter_mm,guard_mm)
            allowed=boolean(allowed,limits,pyclipr.Intersection) if allowed and limits else []
    for index,(hole,paths) in enumerate(zip(holes,profiles)):
        excluded=offset([hole],-distance)
        core=offset([hole],-tool.diameter_mm-2*guard)
        core_area=sum(signed_area(p) for p in core)
        center_area=sum(signed_area(p) for p in excluded)
        perimeter=sum(float(np.linalg.norm(np.roll(p,-1,axis=0)-p,axis=1).sum()) for p in paths)
        rough_length=max(0,center_area)/settings.stepover_mm*rough_levels
        cut_length=perimeter*cut_levels
        ratio=(rough_length/rough_feed)/(cut_length/cut_feed) if rough_feed and cut_feed and cut_length else rough_length/cut_length if cut_length else 0
        reason=None
        if not closed:reason='mesh_not_closed'
        elif settings.radial_allowance_mm or settings.axial_allowance_mm:reason='machining_allowance_requested'
        elif len(paths)!=1:reason='tool_does_not_fit_one_complete_contour'
        elif allowed is not None and any(not _edge_in_domain(a,b,allowed)
                for path in paths for a,b in zip(path,np.roll(path,-1,axis=0))):reason='blocked_by_fixture_or_interior_limits'
        elif sum(signed_area(p) for p in boolean([hole],shadow,pyclipr.Intersection))>1e-6:reason='contains_part_island'
        elif len(core)!=1 or core_area<tool.diameter_mm**2:reason='core_too_small_or_split'
        elif not excluded or ratio<1.25:reason='pocket_is_more_efficient'
        feature={'hole_index':index,'decision':'rough' if reason else 'cutout',
            'reason':reason or 'through_opening_cheaper_as_internal_profile',
            'opening_area_mm2':signed_area(hole),'core_area_mm2':max(0,core_area),
            'profile_length_mm':perimeter,'estimated_roughing_length_mm':rough_length,
            'estimated_cutout_length_mm':cut_length,'estimated_length_or_feed_gain':ratio,
            'estimated_roughing_s':60*rough_length/rough_feed if rough_feed else None,
            'estimated_cutout_s':60*cut_length/cut_feed if cut_feed else None,
            'bounds_mm':[ *hole.min(axis=0).tolist(),*hole.max(axis=0).tolist()]}
        if reason is None:
            feature['excluded_center_polygons_mm']=[p.tolist() for p in excluded]
            feature['core_polygons_mm']=[p.tolist() for p in core]
        features.append(feature)
    selected=[f['hole_index'] for f in features if f['decision']=='cutout']
    return {'policy_version':1,'method':'full_projection_through_openings_and_cost_comparison',
        'selected_indices':selected,'selected_count':len(selected),
        'features':features,'order':'rough_features_then_internal_profiles' if options.smart_part_released else 'rough_features_then_internal_profiles_then_external',
        'cores_remain_as_waste':bool(selected),'requires_waste_support':bool(selected)}
