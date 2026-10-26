"""Stock-aware combined planning, retention geometry and independent export."""
import copy
from dataclasses import asdict,replace
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np

from cam_operations import OperationSettings
from cam_project import RoughingSettings,create_project,load_project,calculate_project
from cam_tools import Tool
from grbl_post import export_grbl,validate_calculation
from smart_planner import resolve_smart_plan,retention_parameters,validate_smart_retention,_edge_retained
from stl_roughing import generate_stl_roughing
from test_cam_setup import binary
from test_drill import plate
from test_stl_roughing import rect


class SmartPlannerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mesh=plate(outer_radius=4,hole_radius=1.8,bottom=-2,vertices=24)
        cls.tool=Tool(id='flat',name='Topo 1',diameter_mm=1,cutting_length_mm=6,
            feed_mm_min=600,plunge_mm_min=120,spindle_rpm=8000)
        cls.settings=RoughingSettings(stepdown_mm=1,stepover_mm=.8,stock_top_mm=0,
            bottom_mm=-1,sampling_mm=.3,boundaries_mm=[rect(-6,-6,6,6)],
            region_mode='projected',compress_collinear=True)

    def test_resolve_combines_order_bottom_and_existing_feeds_without_mutating_inputs(self):
        options=OperationSettings(machining_mode='smart',roughing_enabled=False,
            cutout_enabled=False,cutout_contours='all',cutout_bottom_mm=-100,
            order='cutout_then_roughing',operation_sequence=['cutout','roughing','drill'],
            cutout_stepdown_mm=2,cutout_feed_mm_min=370)
        s,o,report=resolve_smart_plan(self.mesh,self.tool,self.settings,options)
        self.assertEqual(self.settings.bottom_mm,-1);self.assertEqual(s.bottom_mm,-2)
        self.assertEqual(s.region_mode,'layer');self.assertEqual(s.boundaries_mm,self.settings.boundaries_mm)
        self.assertEqual(o.sequence(),['roughing','cutout']);self.assertEqual(o.cutout_contours,'external')
        self.assertTrue(o.cutout_use_prior_roughing);self.assertEqual(o.cutout_bottom_mm,-2)
        self.assertEqual(o.cutout_stepdown_mm,1);self.assertEqual(o.cutout_feed_mm_min,370)
        self.assertIsNone(o.roughing_feed_mm_min);self.assertIsNone(o.spindle_rpm)
        self.assertAlmostEqual(report['skin_mm'],.2);self.assertAlmostEqual(report['retention_z_mm'],-1.8)
        self.assertEqual(report['stock_bottom_source'],'model')
        self.assertEqual(report['sequence'],o.sequence());json.dumps(report,allow_nan=False)
        drilled=replace(options,drill_enabled=True)
        self.assertEqual(drilled.sequence(),['drill','roughing','cutout'])

    def test_explicit_thicker_stock_and_breakthrough_are_separate_from_stl_rough_depth(self):
        s,o,r=resolve_smart_plan(self.mesh,self.tool,self.settings,
            OperationSettings(machining_mode='smart',smart_stock_bottom_mm=-3,
                smart_breakthrough_mm=.1,smart_skin_mm=.3))
        self.assertEqual(s.bottom_mm,-2);self.assertEqual(o.cutout_bottom_mm,-3.1)
        self.assertEqual(r['stock_bottom_mm'],-3);self.assertEqual(r['retention_z_mm'],-2.7)
        self.assertEqual(r['stock_bottom_source'],'configured')
        self.assertTrue(any('1 mm abaixo do STL' in assumption for assumption in r['assumptions']))

    def test_invalid_stock_skin_and_release_reach_fail_early(self):
        for fields in ({'smart_stock_bottom_mm':-1.9},{'smart_stock_bottom_mm':-8},
                       {'smart_skin_mm':2},{'smart_breakthrough_mm':8}):
            with self.subTest(fields=fields),self.assertRaises(ValueError):
                resolve_smart_plan(self.mesh,self.tool,self.settings,OperationSettings(machining_mode='smart',**fields))
        for fields in ({'smart_breakthrough_mm':-.1},{'smart_skin_mm':0},
                       {'smart_stock_bottom_mm':True},{'machining_mode':'auto'}):
            with self.subTest(fields=fields),self.assertRaises(ValueError):OperationSettings(**fields)

    def test_auto_skin_scales_to_thin_stock_and_unknown_smart_depth_defers_reach(self):
        mesh=self.mesh.copy();mesh[:,:,2]*=.05
        settings=replace(self.settings,bottom_mm=-100)
        from cam_operations import validate_operations
        options=OperationSettings(machining_mode='smart',cutout_bottom_mm=-100)
        validate_operations(options,settings,self.tool)
        s,o,r=resolve_smart_plan(mesh,self.tool,settings,options)
        self.assertAlmostEqual(r['skin_mm'],.025)
        self.assertAlmostEqual(r['roughing_bottom_mm'],-.1)
        self.assertAlmostEqual(r['cutout_bottom_mm'],-.1)

    def test_manual_resolver_returns_original_objects_and_does_not_apply_smart_depths(self):
        options=OperationSettings(smart_stock_bottom_mm=-100,smart_breakthrough_mm=10)
        s,o,r=resolve_smart_plan(self.mesh,self.tool,self.settings,options)
        self.assertIs(s,self.settings);self.assertIs(o,options);self.assertIsNone(r)

    def test_sources_complete_internal_hole_below_skin_but_stop_exterior_at_exact_skin(self):
        s,o,r=resolve_smart_plan(self.mesh,self.tool,self.settings,OperationSettings(machining_mode='smart'))
        retention=retention_parameters(self.mesh,self.tool,s,r)
        job=generate_stl_roughing(self.mesh,diameter=1,tool_length=6,stepdown=s.stepdown_mm,
            stepover=s.stepover_mm,sampling=s.sampling_mm,z_top=s.stock_top_mm,z_bottom=s.bottom_mm,
            boundaries=s.boundaries_mm,region_mode=s.region_mode,compress_collinear=True,
            retention=retention)
        self.assertTrue(any(abs(layer['z']-r['retention_z_mm'])<1e-9 for layer in job['layers']))
        low=[(a,b) for layer in job['layers'] for path in layer['polylines']
             for a,b in zip(path['points'],path['points'][1:]) if min(a[2],b[2])<-1.8-1e-8]
        self.assertTrue(low)
        self.assertTrue(all(np.linalg.norm(p[:2])<1.8 for a,b in low for p in (a,b)))
        self.assertTrue(any(abs(p[2]+2)<1e-8 for a,b in low for p in (a,b)))
        self.assertTrue(any(np.linalg.norm(p[:2])>4.5 and abs(p[2]+1.8)<1e-8
            for layer in job['layers'] for path in layer['polylines'] for p in path['points']))
        validate_smart_retention(job,self.mesh,self.tool,s,r)

    def test_edge_validator_checks_whole_concave_segment_and_only_below_plane(self):
        retention={'plane_z':-1,'center_regions_mm':[rect(-3,-3,3,-1),rect(-3,-1,-1,3)]}
        self.assertTrue(_edge_retained([-2,2,-2],[-2,-2,-2],retention))
        self.assertFalse(_edge_retained([-2,2,-2],[2,-2,-2],retention))
        self.assertTrue(_edge_retained([-10,0,-.5],[10,0,-.5],retention))
        self.assertTrue(_edge_retained([-2,-2,-2],[-4,-2,0],retention))
        self.assertFalse(_edge_retained([-2,-2,-2],[10,-2,0],retention))

    def test_keepin_and_keepout_remain_in_force_on_both_sides_of_skin(self):
        settings=replace(self.settings,boundaries_mm=[rect(-6,-1.5,6,1.5)],
            exclusions_mm=[rect(-.3,-6,.3,6)])
        s,o,r=resolve_smart_plan(self.mesh,self.tool,settings,OperationSettings(machining_mode='smart'))
        job=generate_stl_roughing(self.mesh,diameter=1,tool_length=6,stepdown=1,stepover=.4,
            sampling=s.sampling_mm,z_top=0,z_bottom=-2,boundaries=s.boundaries_mm,
            exclusions=s.exclusions_mm,region_mode='layer',compress_collinear=True,
            retention=retention_parameters(self.mesh,self.tool,s,r))
        points=[p for layer in job['layers'] for path in layer['polylines'] for p in path['points']]
        self.assertTrue(any(p[2]<r['retention_z_mm']-1e-8 for p in points))
        self.assertTrue(any(p[2]>=r['retention_z_mm']-1e-8 for p in points))
        self.assertTrue(all(abs(p[0])>=.81-1e-6 and abs(p[1])<=.99+1e-6 for p in points))


class SmartPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)
        cls.stl=cls.root/'annulus.stl';cls.project=cls.root/'smart.json'
        SmartPlannerTests.setUpClass()
        binary(cls.stl,SmartPlannerTests.mesh)
        cls.tool=SmartPlannerTests.tool;cls.settings=SmartPlannerTests.settings
        create_project(cls.stl,cls.project,units='mm',tool=cls.tool,settings=cls.settings,
            operations=OperationSettings(machining_mode='smart',cutout_stepdown_mm=1))
        cls.result=calculate_project(cls.project,include_motion=True)

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_saved_inputs_and_live_effective_setup_remain_distinct_and_plan_replays(self):
        record,mesh,tool,s,inspection=load_project(self.project)
        self.assertEqual(record['roughing']['bottom_mm'],-1)
        self.assertEqual(s.bottom_mm,-1)
        self.assertEqual(inspection['settings']['bottom_mm'],-2)
        self.assertEqual(inspection['smart_plan'],self.result['smart_plan'])
        self.assertEqual(list(self.result['operations']),['roughing','cutout'])
        self.assertEqual(self.result['motion']['validation']['status'],'passed')
        self.assertTrue(self.result['cutout']['rest_material']['applied'])
        self.assertEqual(self.result['cutout']['contours_selection'],'external')
        report=export_grbl(self.result,self.project,self.root/'smart.nc')
        self.assertEqual(report['status'],'passed');self.assertEqual(report['order'],['roughing','cutout'])

    def test_export_rebuilds_plan_and_retaining_domain_and_checks_real_motion(self):
        for mutation,pattern in (
            (lambda r:r['smart_plan'].__setitem__('skin_mm',0),'Plano inteligente'),
            (lambda r:r['roughing']['retention'].__setitem__('center_regions_mm',[rect(-100,-100,100,100)]),'Retenção inteligente'),
            (lambda r:r['roughing']['layers'][-1]['polylines'].append({'points':[[5,0,-2],[5,1,-2]]}),'Rough atravessa'),
            (lambda r:r['operations']['roughing']['moves'].append({'start':[5,0,-2],'end':[5,1,-2]}),'Movimento do Rough')):
            altered=copy.deepcopy(self.result);mutation(altered)
            with self.subTest(pattern=pattern),self.assertRaisesRegex(ValueError,pattern):
                export_grbl(altered,self.project,self.root/'rejected.nc')
        self.assertFalse((self.root/'rejected.nc').exists())

    def test_manual_legacy_and_explicit_manual_have_identical_nc(self):
        outputs=[]
        for label,options in (('legacy',None),('manual',OperationSettings())):
            project=self.root/(label+'.json')
            create_project(self.stl,project,units='mm',tool=self.tool,settings=self.settings,operations=options)
            result=calculate_project(project,include_motion=True)
            output=self.root/(label+'.nc');export_grbl(result,project,output)
            outputs.append(output.read_bytes())
            self.assertIsNone(result['smart_plan']);self.assertNotIn('retention',result['roughing'])
        self.assertEqual(*outputs)


if __name__=='__main__':unittest.main()
