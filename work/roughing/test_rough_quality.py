import copy
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
import numpy as np
from camadas_desbaste import planejar_camadas
from cam_project import RoughingSettings,create_project,calculate_project
from cam_operations import OperationSettings
from cam_tools import Tool
from depth_staging import stage_paths
from grbl_post import export_grbl
from motion_planner import plan_ramps_and_links
from rough_quality import horizontal_levels,include_floor_levels,bounded_contact_heights,simplify_allowed_loop
from stl_roughing import generate_stl_roughing
from smart_planner import _edge_in_domain
from test_stl_roughing import plane,rect,all_edges
from test_layer_roughing import pocket
from test_grbl_post import STL


class RoughQualityTests(unittest.TestCase):
    def test_floor_candidates_group_faces_and_respect_axial_stock_and_range(self):
        mesh=np.concatenate([plane(lambda x,y:-1.35),plane(lambda x,y:-3),
                             plane(lambda x,y:-2+.1*x)])
        floors=horizontal_levels(mesh,top=0,bottom=-2.5,axial_allowance=.2)
        self.assertEqual(len(floors),1)
        self.assertAlmostEqual(floors[0]['z_mm'],-1.15)
        self.assertAlmostEqual(floors[0]['projected_area_mm2'],1600)

    def test_floor_schedule_redistributes_without_tiny_extra_pass_or_large_step(self):
        regular=planejar_camadas(-17,-17,0,.7)
        floors=[{'z_mm':z} for z in (-4,-6,-15.7,-17)]
        layers=include_floor_levels(regular,floors,0,.7,extra_levels=[-16.5])
        z=np.array([0]+[layer.z for layer in layers])
        self.assertLessEqual(np.max(-np.diff(z)),.7+1e-10)
        self.assertGreater(np.min(-np.diff(z)),.39)
        self.assertLess(len(layers),len(regular)+len(floors))
        for floor in floors:self.assertTrue(np.any(np.isclose(z,floor['z_mm'],atol=1e-10)))
        self.assertEqual(layers[-1].z,-17)

    def test_quantization_never_lowers_contact_and_bounds_extra_z_even_near_floors(self):
        h=np.concatenate([np.linspace(-17,0,10001),[-6-1e-10,-6,-6+1e-10]])
        floors=[{'z_mm':-6},{'z_mm':-15.7}]
        raised=bounded_contact_heights(h,top=0,max_extra=.15,floors=floors)
        self.assertTrue(np.all(raised>=h))
        self.assertLessEqual(np.max(raised-h),.15+1e-12)
        self.assertEqual(raised[-2],-6)

    def test_quantization_and_schedule_preserve_physical_geometry_after_z_datum_shift(self):
        h=np.linspace(-9,0,151);floors=[{'z_mm':-6}]
        a=bounded_contact_heights(h,top=0,max_extra=.15,floors=floors)
        b=bounded_contact_heights(h+12.3,top=12.3,max_extra=.15,floors=[{'z_mm':6.3}])
        np.testing.assert_allclose(a,b-12.3,atol=1e-10)

    def test_loop_simplification_cannot_shortcut_concavity_or_keepout(self):
        # Large tolerance is intentionally hostile: the original allowed
        # polygon, rather than a sampling preview, must reject each shortcut.
        loop=[[0,0],[6,0],[6,6],[4,6],[4,1],[2,1],[2,6],[0,6]]
        hole=rect(.3,.3,1,1)[::-1];regions=[loop,hole]
        simplified=simplify_allowed_loop(loop,regions,10)
        self.assertEqual(simplified[0],simplified[-1])
        self.assertGreaterEqual(len(simplified),4)
        self.assertTrue(all(_edge_in_domain([*a,0],[*b,0],regions) for a,b in zip(simplified,simplified[1:])))

    def test_loop_deviation_is_bounded_and_zero_keeps_original(self):
        theta=np.linspace(0,2*np.pi,160,endpoint=False)
        loop=np.column_stack([3*np.cos(theta),3*np.sin(theta)])
        simplified=np.array(simplify_allowed_loop(loop,[loop],.02))
        self.assertLess(len(simplified),len(loop))
        distances=[]
        for a,b in zip(simplified,simplified[1:]):
            d=b-a;t=np.clip((loop-a)@d/(d@d),0,1)
            distances.append(np.linalg.norm(loop-(a+t[:,None]*d),axis=1))
        self.assertLessEqual(np.min(distances,axis=0).max(),.02+1e-10)
        np.testing.assert_equal(simplify_allowed_loop(loop,[loop],0),np.vstack([loop,loop[0]]))

    def test_pruning_requires_completed_full_sweep_and_preserves_deeper_or_offset_pass(self):
        def p(y,z,kind='raster'):return {'kind':kind,'points':[[0,y,z],[4,y,z]]}
        layers=[{'polylines':[p(0,-1,'cleanup'),p(0,-1),p(.2,-1),p(0,-1.5),p(0,-1.5)]}]
        stats={};stage_paths(layers,diameter=1,stock_top=0,stepdown=1,prune_redundant=True,stats=stats)
        self.assertEqual(stats['redundant_raster_paths_removed'],2)
        self.assertEqual(len(layers[0]['polylines']),3)
        self.assertEqual(layers[0]['polylines'][0]['kind'],'cleanup')
        self.assertEqual(layers[0]['polylines'][-1]['points'][0][2],-1.5)

    def test_pruning_never_credits_future_paths_or_only_the_centerline(self):
        paths=[{'kind':'raster','points':[[0,y,-1],[4,y,-1]]} for y in (0,.4)]
        layers=[{'polylines':paths}];stats={}
        stage_paths(layers,diameter=1,stock_top=0,stepdown=1,prune_redundant=True,stats=stats)
        self.assertEqual(stats['redundant_raster_paths_removed'],0)
        self.assertEqual(len(layers[0]['polylines']),2)

    def test_hybrid_pocket_reaches_detected_terrace_and_replays_safe_depths(self):
        mesh=np.concatenate([pocket(True),plane(lambda x,y:-1.35,x0=-3,x1=0,y0=-3,y1=3)])
        job=generate_stl_roughing(mesh,diameter=1,tool_length=5,stepdown=1,stepover=.6,
            z_top=0,z_bottom=-3,boundaries=[rect(-4,-4,4,4)],exclusions=[rect(1,-5,1.4,5)],
            strategy='hybrid',region_mode='layer',cleanup_contours=True,compress_collinear=True,
            axial_allowance=.2,surface_error=.15,path_tolerance=.02)
        self.assertTrue(any(abs(layer['z']+1.15)<1e-10 for layer in job['layers']))
        interior=[]
        for _,a,b in all_edges(job):
            for t in np.linspace(0,1,9):
                p=np.asarray(a)*(1-t)+np.asarray(b)*t
                if -2.2<p[0]<-1.6 and -2<p[1]<2:interior.append(p[2])
                self.assertFalse(.5<p[0]<1.9) # Keep Out plus tool radius
        self.assertTrue(interior);self.assertAlmostEqual(min(interior),-1.15,places=8)
        self.assertEqual(plan_ramps_and_links(job,mesh)['validation']['status'],'passed')

    def test_export_rebuilds_floor_quality_from_saved_mesh_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);stl=root/'model.stl';stl.write_text(STL,encoding='ascii')
            s=RoughingSettings(1,.8,0,-2,strategy='hybrid',region_mode='layer',cleanup_contours=True,
                compress_collinear=True,boundaries_mm=[rect(-3,-2,3,2)])
            options=OperationSettings(roughing_feed_mm_min=800,plunge_mm_min=150,spindle_rpm=12000)
            project=root/'project.json';create_project(stl,project,units='mm',tool=Tool(id='t',name='t',diameter_mm=1,cutting_length_mm=5),settings=s,operations=options)
            result=calculate_project(project,include_motion=True)
            self.assertEqual(export_grbl(result,project,root/'valid.nc')['status'],'passed')
            for key,value in [('surface_extra_z_mm',.5),('horizontal_levels',[])]:
                bad=copy.deepcopy(result);bad['roughing']['quality'][key]=value
                with self.assertRaisesRegex(ValueError,'Precisão'):export_grbl(bad,project,root/'bad.nc')
            self.assertFalse((root/'bad.nc').exists())

    def test_invalid_hybrid_settings_fail_before_calculation(self):
        s=RoughingSettings(1,.5,0,-3,strategy='hybrid',region_mode='layer')
        for patch in ({'surface_error_mm':0},{'path_tolerance_mm':-1},{'region_mode':'projected'},{'optimize_entries':1}):
            with self.subTest(patch=patch),self.assertRaises(ValueError):replace(s,**patch)

    def test_auto_entry_preserves_source_geometry_and_uses_confirmed_plunge_only_when_faster(self):
        job={'tool':{'diameter':1,'length':5},'parameters':{'z_top':0,'stepdown':.7},
            'layers':[{'polylines':[{'points':[[0,0,-.5],[4,0,-.5]]}]}]}
        args={'entry_policy':'auto','cutting_feed':800,'plunge_feed':150,'allow_center_plunge':True}
        fast=plan_ramps_and_links(job,plane(),**args)
        self.assertEqual(fast['optimized_center_plunge_entries'],1)
        self.assertEqual(fast['validation']['status'],'passed')
        self.assertEqual(fast['source_cutting_edges'],1)
        plunge=next(m for m in fast['moves'] if m['kind']=='plunge')
        self.assertEqual(plunge['start'][:2],plunge['end'][:2])
        self.assertAlmostEqual(plunge['start'][2]-plunge['end'][2],.5)
        for change in ({'allow_center_plunge':False},{'plunge_feed':10},{'cutting_feed':None},{'entry_policy':'ramp'}):
            slow=plan_ramps_and_links(job,plane(),**{**args,**change})
            self.assertEqual(slow['optimized_center_plunge_entries'],0)
            self.assertGreater(slow['move_counts'].get('ramp',0),0)
            self.assertEqual([m['end'] for m in slow['moves'] if m['kind']=='cut'],[m['end'] for m in fast['moves'] if m['kind']=='cut'])


if __name__=='__main__':unittest.main()
