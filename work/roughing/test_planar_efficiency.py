"""Constant-Z roughing shares safe entry/XY optimizations, not 3D finishing."""
import copy
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
import numpy as np

from cam_project import RoughingSettings,create_project,calculate_project
from cam_operations import OperationSettings
from cam_tools import Tool
from camadas_desbaste import planejar_camadas
from grbl_post import export_grbl
from layer_roughing import prepare_layer_sources
from smart_planner import _edge_in_domain
from test_cam_setup import binary
from test_drill import plate
from test_stl_roughing import plane,rect


class PlanarEfficiencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)
        cls.stl=cls.root/'blind-pocket.stl'
        binary(cls.stl,plate(outer_radius=4,hole_radius=2.4,bottom=-3,
                            floor=-1.35,vertices=24))
        cls.tool=Tool(id='flat',name='Flat 1',diameter_mm=1,cutting_length_mm=5,
            feed_mm_min=800,plunge_mm_min=150,spindle_rpm=8000)
        settings=RoughingSettings(.7,.6,0,-3,sampling_mm=.3,strategy='planar',
            region_mode='layer',cleanup_contours=True,compress_collinear=True,
            boundaries_mm=[rect(-5,-5,5,5)],path_tolerance_mm=.02)
        options=OperationSettings(machining_mode='smart',drill_center_cutting=True,
            roughing_feed_mm_min=800,plunge_mm_min=150,spindle_rpm=8000,
            cutout_stepdown_mm=.7,machine_acceleration_mm_s2=[80,80,100])
        cls.projects={};cls.results={}
        for name,s,o in (('optimized',settings,options),
                ('ramps',replace(settings,optimize_entries=False),options),
                ('unconfirmed',settings,replace(options,drill_center_cutting=False)),
                ('detailed',replace(settings,strategy='conformal'),options)):
            path=cls.root/(name+'.json')
            create_project(cls.stl,path,units='mm',tool=cls.tool,settings=s,operations=o)
            cls.projects[name]=path;cls.results[name]=calculate_project(path,include_motion=True)

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_planar_entries_use_confirmed_faster_plunge_without_changing_constant_z_cuts(self):
        optimized=self.results['optimized'];ramps=self.results['ramps']
        plan=optimized['operations']['roughing']
        self.assertEqual(plan['parameters']['entry_policy'],'auto')
        self.assertGreater(plan['optimized_center_plunge_entries'],0)
        self.assertEqual(optimized['roughing']['layers'],ramps['roughing']['layers'])
        cuts=[m for m in plan['moves'] if m['kind']=='cut']
        self.assertTrue(cuts)
        self.assertTrue(all(abs(m['start'][2]-m['end'][2])<1e-10 for m in cuts))
        self.assertLess(optimized['motion']['timing']['by_operation_s']['roughing'],
                        ramps['motion']['timing']['by_operation_s']['roughing'])
        self.assertEqual(plan['validation']['status'],'passed')

    def test_disabled_optimization_and_unconfirmed_center_cutting_keep_ramps(self):
        for name,policy in (('ramps','ramp'),('unconfirmed','auto')):
            with self.subTest(name=name):
                plan=self.results[name]['operations']['roughing']
                self.assertEqual(plan['parameters']['entry_policy'],policy)
                self.assertEqual(plan['optimized_center_plunge_entries'],0)
                self.assertGreater(plan['move_counts'].get('ramp',0),0)
                self.assertEqual(plan['validation']['status'],'passed')

    def test_detailed_mode_keeps_existing_ramp_policy(self):
        plan=self.results['detailed']['operations']['roughing']
        self.assertEqual(plan['parameters']['entry_policy'],'ramp')
        self.assertEqual(plan['optimized_center_plunge_entries'],0)

    def test_planar_export_replays_optimized_entry_and_rejects_policy_tampering(self):
        result=self.results['optimized'];destination=self.root/'valid.nc'
        report=export_grbl(result,self.projects['optimized'],destination)
        self.assertEqual(report['status'],'passed')
        self.assertGreater(report['center_plunge_moves_replayed'],0)
        bad=copy.deepcopy(result)
        bad['operations']['roughing']['parameters']['entry_policy']='ramp'
        with self.assertRaisesRegex(ValueError,'Escolha de entrada'):
            export_grbl(bad,self.projects['optimized'],self.root/'bad.nc')
        self.assertFalse((self.root/'bad.nc').exists())

    def test_planar_cleanup_simplifies_only_inside_allowed_keepin_keepout_region(self):
        angle=np.linspace(0,2*np.pi,180,endpoint=False)
        outer=np.column_stack((4*np.cos(angle),4*np.sin(angle)))
        hole=np.asarray(rect(-.7,-.7,.7,.7))[::-1]
        centers=[outer,hole];mesh=plane(lambda x,y:-3)
        layers=planejar_camadas(-3,-3,0,1)
        args=dict(radius=.605,top=0,axial_allowance=0,strategy='planar',
                  stepover=.7,phase=0,angle=0,cleanup=True)
        exact=prepare_layer_sources(mesh,centers,layers,path_tolerance=0,**args)
        reduced=prepare_layer_sources(mesh,centers,layers,path_tolerance=.04,**args)
        count=lambda prepared:sum(len(points)-1 for _,_,sources in prepared
                                 for kind,row,points in sources if kind=='cleanup')
        self.assertLess(count(reduced),count(exact))
        for _,_,sources in reduced:
            for kind,row,points in sources:
                if kind!='cleanup':continue
                for a,b in zip(points,points[1:]):
                    self.assertTrue(_edge_in_domain([*a,0],[*b,0],[p.tolist() for p in centers]))
                    self.assertFalse(-.7<(a[0]+b[0])/2<.7 and -.7<(a[1]+b[1])/2<.7)


if __name__=='__main__':unittest.main()
