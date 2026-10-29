"""Already released stock: interior roughing, optional internal profiles, clamp."""
import copy
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
import numpy as np
from cam_operations import OperationSettings
from cam_project import RoughingSettings,create_project,calculate_project
from cam_tools import Tool
from cutout import generate_cutout
from grbl_post import export_grbl
from mesh_geometry import read_binary_stl
from smart_planner import resolve_smart_plan,_edge_in_domain,validate_smart_geometry,validate_released_auxiliary_motion
from test_cam_setup import binary
from test_internal_cutouts import closed_plate
from test_stl_roughing import box,rect


class ReleasedPartTests(unittest.TestCase):
    def setUp(self):
        self.tool=Tool(id='flat',name='Flat 1',diameter_mm=1,cutting_length_mm=10,
            feed_mm_min=600,plunge_mm_min=120,spindle_rpm=8000)
        self.settings=RoughingSettings(stock_top_mm=0,bottom_mm=-3,stepdown_mm=1,
            stepover_mm=.5,sampling_mm=.2,entry_angle_deg=10,strategy='hybrid',
            region_mode='layer',compress_collinear=True)
        self.options=OperationSettings(machining_mode='smart',smart_part_released=True,
            cutout_stepdown_mm=1,smart_breakthrough_mm=.1)
        self.ring=closed_plate(outer_radius=10,hole_radius=6,bottom=-3,vertices=48)

    def plan(self,mesh=None,settings=None,options=None):
        return resolve_smart_plan(self.ring if mesh is None else mesh,self.tool,
            settings or self.settings,options or self.options)

    def calculate(self,root,mesh=None,settings=None,options=None):
        stl=root/'part.stl';project=root/'project.json'
        binary(stl,self.ring if mesh is None else mesh)
        create_project(stl,project,units='mm',tool=self.tool,settings=settings or self.settings,
            operations=options or self.options,xy_origin='keep',z_origin='keep')
        return project,calculate_project(project,include_motion=True)

    def test_default_remains_stock_release_and_flag_is_strict(self):
        self.assertFalse(OperationSettings().smart_part_released)
        for value in (1,'true',None):
            with self.assertRaises(ValueError):OperationSettings(smart_part_released=value)
        s,o,p=self.plan(options=replace(self.options,smart_part_released=False))
        self.assertEqual(o.cutout_contours,'external');self.assertFalse(p.get('part_released',False))
        self.assertEqual(p['release_contours'],'automatic_internal_then_external')

    def test_internal_profile_only_and_automatic_rough_envelope_inside_outer(self):
        s,o,p=self.plan()
        self.assertTrue(p['part_released']);self.assertTrue(o.cutout_enabled)
        self.assertEqual(o.cutout_contours,'internal');self.assertEqual(p['release_contours'],'automatic_internal_only')
        self.assertEqual(p['skin_mm'],0);self.assertIsNone(p['retention_z_mm'])
        self.assertTrue(p['preparation_contours']['not_required'])
        self.assertLess(p['automatic_regions']['offset_mm'],0)
        xy=np.concatenate(p['automatic_regions']['polygons_mm'])
        self.assertLess(np.linalg.norm(xy,axis=1).max(),9.51)
        job=generate_cutout(self.ring,diameter=1,tool_length=10,top=0,bottom=-3.1,stepdown=1,
            contours=o.cutout_contours,internal_indices=p['internal_cutouts']['selected_indices'])
        self.assertEqual(job['contours_selection'],'automatic_internal')
        self.assertEqual([c['kind'] for c in job['contours']],['internal'])

    def test_no_through_holes_means_rough_only_without_external_fallback(self):
        for mesh in (box(),closed_plate(outer_radius=10,hole_radius=6,bottom=-3,floor=-2,vertices=48)):
            with self.subTest(kind=len(mesh)):
                s,o,p=self.plan(mesh)
                self.assertFalse(o.cutout_enabled);self.assertEqual(p['sequence'],['roughing'])
                self.assertEqual(p['release_contours'],'none');self.assertEqual(p['preparation_contours']['eligible'],0)
                self.assertEqual(p['internal_cutouts']['selected_count'],0)

    def test_internal_profile_blocked_by_clamp_or_keepin_stays_in_rough(self):
        for settings in (replace(self.settings,exclusions_mm=[rect(4,-1,7,1)]),
                         replace(self.settings,boundaries_mm=[rect(-4,-4,4,4)])):
            with self.subTest(settings=settings):
                s,o,p=self.plan(settings=settings)
                self.assertFalse(o.cutout_enabled)
                self.assertEqual(p['internal_cutouts']['features'][0]['reason'],'blocked_by_fixture_or_interior_limits')
                self.assertTrue(p['automatic_regions']['polygons_mm'])

    def test_interior_profile_exports_and_forged_external_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);project,result=self.calculate(root)
            self.assertEqual([c['kind'] for c in result['cutout']['contours']],['internal'])
            self.assertIsNone(result['roughing'].get('retention'))
            self.assertEqual(export_grbl(result,project,root/'inside.nc')['status'],'passed')
            bad=copy.deepcopy(result);bad['cutout']['contours_selection']='automatic'
            with self.assertRaisesRegex(ValueError,'Contornos do Cutout'):
                export_grbl(bad,project,root/'bad.nc')
            self.assertFalse((root/'bad.nc').exists())

    def test_blind_pocket_roughs_around_clamp_and_no_cutout_is_generated(self):
        mesh=closed_plate(outer_radius=10,hole_radius=6,bottom=-3,floor=-2,vertices=48)
        settings=replace(self.settings,exclusions_mm=[rect(-1,-1,1,1)],obstacle_top_mm=2)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);project,result=self.calculate(root,mesh=mesh,settings=settings)
            self.assertIsNone(result['cutout']);self.assertEqual(list(result['operations']),['roughing'])
            self.assertGreater(result['roughing']['cutting_edges'],0)
            self.assertEqual(result['roughing']['preparation_cutting_edges'],0)
            for layer in result['roughing']['layers']:
                for path in layer['polylines']:
                    for a,b in zip(path['points'],path['points'][1:]):
                        self.assertTrue(_edge_in_domain(a,b,result['smart_plan']['automatic_regions']['polygons_mm']))
            self.assertEqual(export_grbl(result,project,root/'pocket.nc')['status'],'passed')
            bad=copy.deepcopy(result['roughing']);bad['automatic_regions']['area_mm2']+=1
            placed=read_binary_stl(root/'part.stl');s,o,p=self.plan(placed,settings=settings)
            with self.assertRaisesRegex(ValueError,'Áreas automáticas'):
                validate_smart_geometry(bad,placed.triangles,self.tool,s,o,p)

    def test_drill_or_cutout_may_not_enter_fixture_even_during_approach(self):
        settings=replace(self.settings,exclusions_mm=[rect(-1,-1,1,1)],obstacle_top_mm=2)
        for name in ('Drill','Cutout'):
            with self.subTest(operation=name),self.assertRaisesRegex(ValueError,'bloqueado pela fixação'):
                validate_released_auxiliary_motion({'moves':[{'start':[0,0,4.54],'end':[0,0,0]}]},
                    self.ring,self.tool,settings,self.options,name)


if __name__=='__main__':unittest.main()
