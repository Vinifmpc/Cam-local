"""Geometry-selected Rough areas and an exact pre-release profile channel."""
import copy
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
import numpy as np

from cam_operations import OperationSettings
from cam_project import RoughingSettings,create_project,calculate_project
from cam_tools import Tool
from grbl_post import export_grbl
from smart_planner import resolve_smart_plan,_edge_in_domain
from test_cam_setup import binary
from test_drill import plate
from test_stl_roughing import box,plane,rect


def extruded_profile(profile,caps,y0=-2,y1=2):
    """Closed mesh with explicit conforming caps, extruded from an XZ outline."""
    points=lambda index,y:[profile[index][0],y,profile[index][1]]
    triangles=[]
    for indices in caps:
        triangles.append([points(i,y0) for i in indices])
        triangles.append([points(i,y1) for i in indices[::-1]])
    for i in range(len(profile)):
        j=(i+1)%len(profile)
        triangles.extend([[points(i,y0),points(i,y1),points(j,y1)],
                          [points(i,y0),points(j,y1),points(j,y0)]])
    return np.asarray(triangles,float)


class SmartAutoRegionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.tool=Tool(id='flat',name='Topo 1',diameter_mm=1,cutting_length_mm=8,
            feed_mm_min=600,plunge_mm_min=120,spindle_rpm=8000)
        self.s=RoughingSettings(stepdown_mm=1,stepover_mm=.8,stock_top_mm=0,bottom_mm=-4,
            boundaries_mm=[],region_mode='layer',cleanup_contours=True,compress_collinear=True)
        self.options=OperationSettings(machining_mode='smart',cutout_stepdown_mm=1)

    def tearDown(self):self.temp.cleanup()

    def calculate(self,mesh,settings=None,label='project'):
        stl=self.root/(label+'.stl');project=self.root/(label+'.json')
        binary(stl,mesh)
        create_project(stl,project,units='mm',tool=self.tool,settings=settings or self.s,operations=self.options)
        return calculate_project(project,include_motion=True),project

    def test_vertical_cube_rough_is_empty_and_cutout_cuts_complete_external_profile(self):
        result,project=self.calculate(box())
        rough=result['roughing'];report=result['smart_plan']
        self.assertEqual(rough['raster_polyline_count'],0)
        self.assertEqual(rough['cleanup_polyline_count'],0)
        self.assertEqual(rough['preparation_polyline_count'],0)
        self.assertEqual(rough['preclear_polyline_count'],0)
        self.assertEqual(result['operations']['roughing']['moves'],[])
        self.assertEqual(report['preparation_contours']['eligible'],0)
        self.assertEqual(report['preparation_contours']['blocked'],0)
        self.assertTrue(report['preparation_contours']['not_required'])
        self.assertEqual(report['exterior_strategy']['mode'],'features_then_cutout')
        self.assertTrue(report['exterior_strategy']['external_prismatic'])
        self.assertEqual(report['automatic_regions']['exterior_raster_collar_mm'],0)
        rest=result['cutout']['rest_material']
        self.assertEqual(rest['remaining_depth_passes'],rest['input_depth_passes'])
        self.assertEqual(rest['skipped_depth_passes'],0)
        self.assertEqual(export_grbl(result,project,self.root/'cube.nc')['status'],'passed')

    def test_empty_and_absent_keepin_use_same_automatic_geometry(self):
        a,pa=self.calculate(box(),label='empty')
        b,pb=self.calculate(box(),replace(self.s,boundaries_mm=None),label='absent')
        self.assertEqual(a['smart_plan'],b['smart_plan'])
        self.assertEqual(a['motion']['moves'],b['motion']['moves'])
        self.assertFalse(a['smart_plan']['automatic_regions']['manual_limits_applied'])

    def test_concavity_is_preserved_instead_of_becoming_a_box_or_convex_hull(self):
        mesh=np.concatenate([plane(lambda x,y:0,x0=0,x1=8,y0=0,y1=2),
            plane(lambda x,y:0,x0=0,x1=2,y0=2,y1=8),
            plane(lambda x,y:-2,x0=0,x1=8,y0=0,y1=2),
            plane(lambda x,y:-2,x0=0,x1=2,y0=2,y1=8)])
        _,_,report=resolve_smart_plan(mesh,self.tool,self.s,self.options)
        auto=report['automatic_regions']
        self.assertAlmostEqual(auto['offset_mm'],.605)
        self.assertFalse(_edge_in_domain([5,5,-1],[5.1,5,-1],auto['polygons_mm']))
        self.assertTrue(_edge_in_domain([1,5,-1],[1,6,-1],auto['polygons_mm']))
        self.assertLess(auto['area_mm2'],60)

    def test_exact_half_grid_boundary_contact_is_proved_without_accepting_outside_edge(self):
        a=[-27.035566,-34.323640,-1];b=[-26.868123,-34.454873,-1]
        midpoint=[(a[0]+b[0])/2,(a[1]+b[1])/2,-1]
        region=[[a[:2],b[:2],[b[0]+1,b[1]+2],[a[0]+1,a[1]+2]]]
        self.assertTrue(_edge_in_domain(a,midpoint,region))
        self.assertTrue(_edge_in_domain(midpoint,b,region))
        self.assertFalse(_edge_in_domain([a[0]-1e-4,a[1]-1e-4,-1],
                                         [b[0]-1e-4,b[1]-1e-4,-1],region))

    def test_internal_through_hole_keeps_3d_rough_to_bottom_below_exterior_skin(self):
        result,project=self.calculate(plate(outer_radius=4,hole_radius=1.8,bottom=-2,vertices=24))
        plane_z=result['smart_plan']['retention_z_mm']
        internal=[p for layer in result['roughing']['layers'] for p in layer['polylines']
            if p['kind']=='raster' and any(v[2]<plane_z-1e-8 for v in p['points'])]
        self.assertTrue(internal)
        self.assertTrue(any(abs(v[2]+2)<1e-8 for p in internal for v in p['points']))
        self.assertTrue(all(np.linalg.norm(v[:2])<1.8 for p in internal for v in p['points']))
        self.assertEqual(result['cutout']['rest_material']['remaining_depth_passes'],
                         result['cutout']['rest_material']['input_depth_passes'])
        self.assertEqual(export_grbl(result,project,self.root/'hole.nc')['status'],'passed')

    def test_manual_limits_restrict_features_without_creating_preparation_profiles(self):
        mesh=plate(outer_radius=4,hole_radius=1.8,bottom=-2,vertices=24)
        for label,settings in (
            ('keepin',replace(self.s,boundaries_mm=[rect(-2,-2,2,2)])),
            ('keepout',replace(self.s,exclusions_mm=[rect(-.1,-8,.1,-3.7)]))):
            with self.subTest(label=label):
                result,project=self.calculate(mesh,settings,label=label)
                spec=result['smart_plan']['preparation_contours']
                self.assertEqual(spec['eligible'],0);self.assertEqual(spec['blocked'],0)
                self.assertTrue(spec['not_required'])
                self.assertEqual(result['roughing']['preparation_polyline_count'],0)
                self.assertTrue(result['smart_plan']['automatic_regions']['manual_limits_applied'])
                rest=result['cutout']['rest_material']
                self.assertEqual(rest['remaining_depth_passes'],rest['input_depth_passes'])
                self.assertEqual(export_grbl(result,project,self.root/(label+'.nc'))['status'],'passed')

    def test_export_rebuilds_auto_domain_and_nominal_preparation_geometry(self):
        result,project=self.calculate(box())
        altered=copy.deepcopy(result)
        altered['roughing']['automatic_regions']=copy.deepcopy(altered['roughing']['automatic_regions'])
        altered['roughing']['automatic_regions']['polygons_mm']=[rect(-100,-100,100,100)]
        with self.assertRaisesRegex(ValueError,'Áreas automáticas'):
            export_grbl(altered,project,self.root/'bad-domain.nc')
        altered=copy.deepcopy(result)
        altered['roughing']['layers'][0]['polylines'].append({'kind':'preparation',
            'smart_profile_index':0,'smart_profile_z':-1,'closed':True,
            'points':[[0,0,-1],[1,0,-1],[0,0,-1]]})
        with self.assertRaisesRegex(ValueError,'Perfil de preparação'):
            export_grbl(altered,project,self.root/'bad-profile.nc')
        altered=copy.deepcopy(result)
        altered['operations']['roughing']['parameters']['allow_center_plunge']=True
        with self.assertRaisesRegex(ValueError,'Confirmação de corte pelo centro'):
            export_grbl(altered,project,self.root/'bad-capability.nc')

    def test_taper_that_widens_inside_retaining_skin_has_honest_warning(self):
        top=rect(-1,-1,1,1);bottom=rect(-2,-2,2,2)
        triangles=[plane(lambda x,y:0,x0=-1,x1=1,y0=-1,y1=1),
                   plane(lambda x,y:-2,x0=-2,x1=2,y0=-2,y1=2)]
        for i in range(4):
            j=(i+1)%4
            triangles.append(np.asarray([[[*bottom[i],-2],[*bottom[j],-2],[*top[j],0]],
                                         [[*bottom[i],-2],[*top[j],0],[*top[i],0]]]))
        _,_,report=resolve_smart_plan(np.concatenate(triangles),self.tool,self.s,self.options)
        self.assertGreater(report['retention_band_outer_variation_mm2'],0)
        self.assertTrue(any('acabamento 3D' in text for text in report['assumptions']))
        _,_,cube=resolve_smart_plan(box(),self.tool,self.s,self.options)
        self.assertEqual(cube['retention_band_outer_variation_mm2'],0)

    def test_guarded_hole_fit_and_center_capability_are_reported_without_enabling_drill(self):
        mesh=plate(outer_radius=4,hole_radius=.6,bottom=-2,vertices=24)
        _,options,report=resolve_smart_plan(mesh,self.tool,self.s,self.options)
        self.assertEqual(report['automatic_regions']['rough_unreachable_projected_openings'],1)
        self.assertFalse(options.drill_enabled);self.assertFalse(report['allow_center_plunge'])
        self.assertTrue(any('O Rough não alcança' in text for text in report['assumptions']))
        _,options,report=resolve_smart_plan(mesh,self.tool,self.s,
            replace(self.options,drill_center_cutting=True))
        self.assertTrue(report['allow_center_plunge']);self.assertFalse(options.drill_enabled)
        self.assertTrue(any('descida vertical' in text for text in report['assumptions']))

    def test_open_edge_recess_uses_3d_rough_without_nominal_external_profiles(self):
        profile=[[0,-2],[4,-2],[4,-1],[4,0],[2,0],[2,-1],[0,-1]]
        caps=[[0,1,5],[1,2,5],[0,5,6],[5,2,3],[5,3,4]]
        mesh=extruded_profile(profile,caps)
        result,project=self.calculate(mesh,replace(self.s,boundaries_mm=None),label='open-edge')
        report=result['smart_plan']
        self.assertTrue(report['exterior_strategy']['proof']['closed_consistent_edges'])
        self.assertFalse(report['exterior_strategy']['external_prismatic'])
        self.assertEqual(report['exterior_strategy']['mode'],'features_then_cutout')
        self.assertEqual(result['roughing']['preparation_polyline_count'],0)
        self.assertGreater(result['roughing']['raster_polyline_count'],0)
        self.assertTrue(any(p[0]<2 and p[2]<-.5 for layer in result['roughing']['layers']
                            for path in layer['polylines'] for p in path['points']))
        self.assertEqual(result['cutout']['rest_material']['skipped_depth_passes'],0)
        self.assertEqual(export_grbl(result,project,self.root/'open-edge.nc')['status'],'passed')

    def test_flange_overhang_is_detected_in_3d_even_when_upper_shadow_hides_it(self):
        profile=[[-1,-2],[1,-2],[1,-1],[2,-1],[2,0],[-2,0],[-2,-1],[-1,-1]]
        caps=[[0,1,2],[0,2,7],[5,6,7],[5,7,2],[5,2,3],[5,3,4]]
        mesh=extruded_profile(profile,caps)
        _,_,report=resolve_smart_plan(mesh,self.tool,self.s,self.options)
        proof=report['exterior_strategy']['proof']
        self.assertTrue(proof['closed_consistent_edges'])
        self.assertTrue(proof['possible_undercut'])
        self.assertGreater(proof['downward_projection_area_mm2'],1)
        self.assertFalse(report['exterior_strategy']['external_prismatic'])
        # A nominal external channel cannot machine this lower-facing surface.
        self.assertEqual(report['preparation_contours']['depth_count'],0)
        self.assertTrue(any('superfícies inferiores' in text for text in report['assumptions']))


if __name__=='__main__':unittest.main()
