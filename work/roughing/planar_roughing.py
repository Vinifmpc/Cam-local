"""Combine recovered layer planning with clipped 2D raster segments.

Scope: a constant XY section extruded over the full depth. Boundaries and
exclusions are physical polygons, not STL sections. Every returned segment is
independent. No connecting, approach, plunge, ramp or rapid moves are implied.
"""
from dataclasses import asdict
import math

from camadas_desbaste import planejar_camadas
from region_core import center_regions, raster_segments


def plan_planar_roughing(boundaries, exclusions, *, z_min_model, z_min_limit,
                        z_top, stepdown, stepover, diameter, tolerance=0.0,
                        boundary_margin=0.01, raster_origin_y=0.0):
    """Return independent XYZ cutting segments for a constant-section job.

    Units are millimeters. `tolerance` affects the recovered Z scheduler;
    `boundary_margin` affects XY tool clearance. Neither is stock allowance.
    The caller must not use this for a varying STL section or infer moves
    between adjacent segments in the returned collection.
    """
    layers = planejar_camadas(z_min_model, z_min_limit, z_top,
                             stepdown, tolerance)
    regions = center_regions(boundaries, exclusions, diameter, boundary_margin)
    raster = raster_segments(regions, stepover, raster_origin_y)
    segment_count = len(layers) * len(raster)
    if segment_count > 1_000_000:
        raise ValueError('Prototype output limit: 1,000,000 independent segments')
    xy_length = sum(math.dist(segment['start'], segment['end'])
                    for segment in raster)
    result_layers = []
    for index, layer in enumerate(layers):
        result_layers.append({
            'index': index,
            **asdict(layer),
            'segments': [{'row': segment['row'],
                          'start': [*segment['start'], layer.z],
                          'end': [*segment['end'], layer.z]}
                         for segment in raster],
        })
    return {
        'schema_version': 1,
        'scope': 'constant_xy_section_extruded_over_depth',
        'units': 'mm',
        'tool_diameter': diameter,
        'boundary_margin': boundary_margin,
        'requested_stepdown': stepdown,
        'stepover': stepover,
        'center_regions': [region.tolist() for region in regions],
        'layer_count': len(layers),
        'segment_count': segment_count,
        'cutting_length_mm': xy_length * len(layers),
        'layers': result_layers,
        'motion_links_included': False,
    }


def controlled_example():
    return plan_planar_roughing(
        boundaries=[[[0, 0], [30, 0], [30, 20], [0, 20]]],
        exclusions=[[[12, 7], [18, 7], [18, 13], [12, 13]]],
        z_min_model=-6, z_min_limit=-6, z_top=0,
        stepdown=2.5, stepover=1.27, diameter=3.175,
        raster_origin_y=0.37,
    )


if __name__ == '__main__':
    import json
    print(json.dumps(controlled_example(), indent=2))
