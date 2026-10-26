"""Through-core selection, blind floors, independent export and release order."""
import copy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np

from cam_operations import OperationSettings
from cam_project import RoughingSettings,create_project,calculate_project
from cam_tools import Tool
from cutout import generate_cutout
from grbl_post import export_grbl
from motion_planner import plan_ramps_and_links
from smart_planner import resolve_smart_plan,_edge_in_domain
from test_cam_setup import binary
from test_drill import plate
from test_stl_roughing import box,rect


def closed_plate(**kwargs):
    mesh=plate(**kwargs)
    # The drill fixture uses unoriented triangles. Give this solid's inner
    # wall the inward winding required by automatic through-core selection.
    for index in (4,5):mesh[index::8]=mesh[index::8,::-1]
    return mesh


class InternalCutoutTests(unittest.TestCase):
    def setUp(self):
        self.tool=Tool(id='flat',name='Topo 1',diameter_mm=1,cutting_length_mm=10,
            feed_mm_min=600,plunge_mm_min=120,spindle_rpm=8000)
        self.settings=RoughingSettings(stepdown_mm=1,stepover_mm=.5,stock_top_mm=0,
            bottom_mm=-3,sampling_mm=.2,region_mode='layer',compress_collinear=True)
        self.options=OperationSettings(machining_mode='smart',cutout_stepdown_mm=1)
        self.mesh=closed_plate(outer_radius=10,hole_radius=6,bottom=-3,vertices=48)

    def plan(self,mesh=None,settings=None,tool=None,options=None):
        return resolve_smart_plan(self.mesh if mesh is None else mesh,tool or self.tool,
            settings or self.settings,options or self.options)[2]

    def test_large_through_core_is_delegated_and_never_counted_as_cleared(self):
        plan=self.plan();spec=plan['internal_cutouts']
        self.assertEqual(spec['selected_count'],1)
        self.assertGreater(spec['features'][0]['estimated_length_or_feed_gain'],1.25)
        self.assertTrue(spec['cores_remain_as_waste']);self.assertTrue(spec['requires_waste_support'])
        auto=plan['automatic_regions']
        self.assertFalse(_edge_in_domain([0,0,-1],[.1,0,-1],auto['polygons_mm']))
        self.assertTrue(_edge_in_domain([8,0,-1],[8,.1,-1],auto['polygons_mm']))
        json.dumps(plan,allow_nan=False)

    def test_blind_pocket_and_even_a_floor_at_mesh_bottom_never_become_cutouts(self):
        for floor in (-2,-3):
            with self.subTest(floor=floor):
                mesh=closed_plate(outer_radius=10,hole_radius=6,bottom=-3,floor=floor,vertices=48)
                self.assertEqual(self.plan(mesh)['internal_cutouts']['selected_indices'],[])

    def test_small_or_expensive_holes_stay_in_rough_without_global_cutout_failure(self):
        small=closed_plate(outer_radius=3,hole_radius=.8,bottom=-3,vertices=32)
        self.assertEqual(self.plan(small)['internal_cutouts']['selected_count'],0)
        expensive=replace(self.options,roughing_feed_mm_min=1000,cutout_feed_mm_min=1)
        self.assertEqual(self.plan(options=expensive)['internal_cutouts']['selected_count'],0)

    def test_open_mesh_and_requested_allowances_preserve_roughing_policy(self):
        self.assertEqual(self.plan(self.mesh[:-1])['internal_cutouts']['selected_count'],0)
        for settings in (replace(self.settings,radial_allowance_mm=.1),replace(self.settings,axial_allowance_mm=.1)):
            self.assertEqual(self.plan(settings=settings)['internal_cutouts']['selected_count'],0)

    def test_island_of_final_part_material_cannot_be_discarded_with_the_core(self):
        island=box()*np.array([.1,.1,.75])
        plan=self.plan(np.concatenate([self.mesh,island]))
        self.assertEqual(plan['internal_cutouts']['selected_count'],0)
        self.assertEqual(plan['internal_cutouts']['features'][0]['reason'],'contains_part_island')

    def test_selected_big_hole_does_not_require_tool_to_fit_unselected_small_hole(self):
        large=self.mesh.copy();large[:,:,0]-=12
        small=closed_plate(outer_radius=5,hole_radius=.3,bottom=-3,vertices=32,center=(12,0))
        mesh=np.concatenate([large,small]);plan=self.plan(mesh)
        spec=plan['internal_cutouts'];self.assertEqual(spec['selected_count'],1)
        job=generate_cutout(mesh,diameter=1,tool_length=10,top=0,bottom=-3,stepdown=1,
            contours='external',internal_indices=spec['selected_indices'])
        self.assertEqual(job['internal_contours_total'],2);self.assertEqual(job['skipped_internal_contours'],1)
        self.assertEqual([c['kind'] for c in job['contours']],['internal','external','external'])

    def test_manual_limits_still_apply_only_to_rough_and_internal_policy_is_explicit(self):
        limits=replace(self.settings,boundaries_mm=[rect(-2,-2,2,2)],exclusions_mm=[rect(-1,-1,1,1)])
        plan=self.plan(settings=limits)
        self.assertEqual(plan['internal_cutouts']['selected_count'],1)
        self.assertTrue(plan['automatic_regions']['manual_limits_applied'])

    def test_tapered_hole_preserves_3d_rough_outside_delegated_core(self):
        mesh=self.mesh.copy();inner=np.isclose(np.linalg.norm(mesh[:,:,:2],axis=2),6)
        factor=1+(mesh[:,:,2]+3)/18
        mesh[:,:,:2]=np.where(inner[:,:,None],mesh[:,:,:2]*factor[:,:,None],mesh[:,:,:2])
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);stl=root/'taper.stl';project=root/'taper.json';binary(stl,mesh)
            create_project(stl,project,units='mm',tool=self.tool,settings=self.settings,operations=self.options)
            result=calculate_project(project,include_motion=True)
            self.assertEqual(result['smart_plan']['internal_cutouts']['selected_count'],1)
            self.assertGreater(result['roughing']['cutting_edges'],0)
            self.assertEqual(result['motion']['validation']['status'],'passed')
            self.assertEqual(export_grbl(result,project,root/'taper.nc')['status'],'passed')

    def test_full_pipeline_profiles_inner_before_outer_and_export_rejects_forgery(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);stl=root/'ring.stl';project=root/'project.json';binary(stl,self.mesh)
            create_project(stl,project,units='mm',tool=self.tool,settings=self.settings,operations=self.options)
            result=calculate_project(project,include_motion=True)
            self.assertEqual(result['roughing']['cutting_edges'],0)
            job=result['cutout'];self.assertEqual(job['contours_selection'],'automatic')
            self.assertEqual([c['kind'] for c in job['contours']],['internal','external'])
            moves=result['operations']['cutout']['moves']
            internal=[i for i,m in enumerate(moves) if m['kind']=='cut' and job['layers'][m['layer']]['contour_kind']=='internal']
            external=[i for i,m in enumerate(moves) if m['kind']=='cut' and job['layers'][m['layer']]['contour_kind']=='external']
            self.assertLess(max(internal),min(external))
            self.assertEqual(export_grbl(result,project,root/'valid.nc')['status'],'passed')
            for mutate in (
                lambda r:r['smart_plan']['internal_cutouts']['selected_indices'].clear(),
                lambda r:r['cutout']['selected_internal_indices'].clear()):
                altered=copy.deepcopy(result);mutate(altered)
                with self.assertRaises(ValueError):export_grbl(altered,project,root/'forged.nc')
            self.assertFalse((root/'forged.nc').exists())

    def test_independent_replay_rejects_external_release_before_internal_completion(self):
        job=generate_cutout(self.mesh,diameter=1,tool_length=10,top=0,bottom=-3,stepdown=1,
            contours='external',internal_indices=self.plan()['internal_cutouts']['selected_indices'])
        job['layers'].sort(key=lambda layer:layer['contour_kind']=='internal')
        with self.assertRaisesRegex(ValueError,'externo iniciado antes'):
            plan_ramps_and_links(job,self.mesh)


if __name__=='__main__':unittest.main()
