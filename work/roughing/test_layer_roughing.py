import copy
import unittest
import numpy as np
from layer_regions import shadow_above,free_layer_regions,region_area
from cleared_area import ClearedArea
from depth_staging import stage_paths
from stl_roughing import generate_stl_roughing
from motion_planner import plan_ramps_and_links,validate_motion,MotionPlanningError
from test_stl_roughing import plane,rect,all_edges,box
from reference_keepout import approximate_reference_keepout


def pocket(island=False):
    triangles=[plane(lambda x,y:-3,x0=-5,x1=5,y0=-5,y1=5)]
    for x0,y0,x1,y1 in ((-5,-5,-3,5),(3,-5,5,5),(-3,-5,3,-3),(-3,3,3,5)):
        triangles.append(plane(lambda x,y:0,x0=x0,x1=x1,y0=y0,y1=y1))
    if island:triangles.append(plane(lambda x,y:0,x0=-.7,x1=.7,y0=-.7,y1=.7))
    return np.concatenate(triangles)


class LayerRoughingTests(unittest.TestCase):
    def job(self,mesh=None,**extra):
        args=dict(diameter=1,tool_length=10,stepdown=1,stepover=.8,sampling=.2,z_top=0,z_bottom=-3,
            boundaries=[rect(-4,-4,4,4)],region_mode='layer',cleanup_contours=True,
            compress_collinear=True)
        args.update(extra)
        return generate_stl_roughing(pocket() if mesh is None else mesh,**args)

    def test_clipped_triangle_shadow_has_analytic_area(self):
        triangles=np.array([[[0,0,0],[2,0,2],[0,2,0]]],float)
        self.assertAlmostEqual(region_area(shadow_above(triangles,1)),.5)
        self.assertAlmostEqual(region_area(shadow_above(triangles,-1)),2)
        self.assertEqual(shadow_above(triangles,3),[])

    def test_coplanar_top_protected_but_floor_tangency_allowed(self):
        mesh=plane(lambda x,y:0,x0=-2,x1=2,y0=-2,y1=2)
        self.assertEqual(shadow_above(mesh,0),[])
        self.assertAlmostEqual(region_area(shadow_above(mesh,0,include_coplanar=True)),16)
        self.assertFalse(free_layer_regions(mesh,[np.array(rect(-1,-1,1,1))],0,.5,include_coplanar=True))

    def test_region_preserves_island_as_hole(self):
        free=free_layer_regions(pocket(True),[np.array(rect(-4,-4,4,4))],-1,.5)
        # At least one negative-winding loop must remain; normalizing solids
        # here would silently fill the island's protected area.
        from region_core import signed_area
        self.assertTrue(any(signed_area(p)<0 for p in free))

    def test_closed_cleanup_and_native_motion_depth_replay(self):
        job=self.job()
        self.assertGreater(job['cleanup_polyline_count'],0)
        cleanup=[p for l in job['layers'] for p in l['polylines'] if p['kind']=='cleanup']
        self.assertTrue(all(p['closed'] for p in cleanup))
        plan=plan_ramps_and_links(job,pocket())
        self.assertEqual(plan['validation']['status'],'passed')
        self.assertEqual(plan['validation']['source_edges_preserved'],job['cutting_edges'])

    def test_planar_island_and_physical_exclusion_clearance(self):
        job=self.job(pocket(True),strategy='planar',exclusions=[rect(1,-.5,1.5,.5)])
        self.assertGreater(job['cutting_edges'],0)
        for layer,a,b in all_edges(job):
            for t in np.linspace(0,1,5):
                p=np.array(a)*(1-t)+np.array(b)*t
                self.assertGreaterEqual(np.linalg.norm(np.maximum(abs(p[:2])-.7,0)),.5-1e-7)
                dx=max(1-p[0],p[0]-1.5,0);dy=max(-.5-p[1],p[1]-.5,0)
                self.assertGreaterEqual(np.hypot(dx,dy),.5-1e-7)

    def test_full_exclusion_skips_contact_and_paths(self):
        job=self.job(exclusions=[rect(-100,-100,100,100)])
        self.assertEqual(job['cutting_edges'],0);self.assertEqual(job['contact_samples'],0)

    def test_silhouette_domain_never_adds_outside_centers(self):
        job=self.job(domain_mode='silhouette',raster_angle_deg=23)
        self.assertGreater(job['cutting_edges'],0)
        for _,a,b in all_edges(job):
            for p in (a,b):self.assertTrue(-5<=p[0]<=5 and -5<=p[1]<=5)

    def test_explicit_stock_domain_roughs_around_a_vertical_cube(self):
        mesh=box()
        job=self.job(mesh,boundaries=[rect(-14,-14,14,14)],z_bottom=-4,
                     diameter=2,stepover=1,sampling=.2)
        self.assertGreater(job['cutting_edges'],0)
        for _,a,b in all_edges(job):
            for p in (a,b):
                self.assertTrue(-13<=p[0]<=13 and -13<=p[1]<=13)
                self.assertGreaterEqual(np.linalg.norm(np.maximum(abs(np.asarray(p[:2]))-10,0)),1-1e-7)
        self.assertEqual(plan_ramps_and_links(job,mesh)['validation']['status'],'passed')

    def test_silhouette_cube_retains_material_outside_its_footprint(self):
        job=self.job(box(),boundaries=[rect(-14,-14,14,14)],z_bottom=-4,
                     domain_mode='silhouette')
        self.assertEqual(job['cutting_edges'],0)

    def test_cleared_area_can_prove_adjacent_passes_but_not_unremoved_strip(self):
        area=ClearedArea(2,0)
        for y in (-.3,.3):area.add([-3,y,-1],[3,y,-1])
        self.assertTrue(area.covers([-1,0,-2],[1,0,-2],-1))
        self.assertFalse(area.covers([-1,1,-2],[1,1,-2],-1))
        self.assertFalse(area.covers([-1,0,-2],[1,0,-2],-1.1))

    def test_cleared_area_does_not_credit_above_height_or_future_moves(self):
        area=ClearedArea(1,0)
        self.assertFalse(area.covers([0,0,-2],[1,0,-2],-1))
        area.add([-2,0,-2],[3,0,0])
        self.assertFalse(area.covers([0,0,-2],[1,0,-2],-1))

    def test_staging_prepares_new_deep_footprint_before_descent(self):
        paths=[{'polylines':[{'kind':'cleanup','points':[[0,0,-2],[4,0,-2]]}]}]
        count=stage_paths(paths,diameter=1,stock_top=0,stepdown=.7)
        self.assertEqual(count,2)
        depths=[p['points'][0][2] for p in paths[0]['polylines']]
        np.testing.assert_allclose(depths,[-.6,-1.3,-2])
        job={'tool':{'diameter':1,'length':5},'parameters':{'z_top':0,'stepdown':.7},'layers':paths}
        plan=plan_ramps_and_links(job,plane())
        self.assertEqual(plan['validation']['status'],'passed')

    def test_excessive_staging_has_controlled_limit_not_python_recursion_error(self):
        paths=[{'polylines':[{'kind':'cleanup','points':[[0,0,-12],[4,0,-12]]}]}]
        with self.assertRaisesRegex(ValueError,'staging pass limit'):
            stage_paths(paths,diameter=1,stock_top=0,stepdown=.01)

    def test_wrong_domain_and_cleanup_combinations_are_rejected(self):
        for change in ({'region_mode':'magic'},{'domain_mode':'magic'},
                       {'region_mode':'projected','cleanup_contours':True}):
            with self.subTest(change=change),self.assertRaises(ValueError):self.job(**change)

    def test_ramp_cannot_enter_an_uncleared_region_at_deep_z(self):
        source={'tool':{'diameter':1,'length':10},'parameters':{'z_top':0,'stepdown':2},
            'layers':[{'polylines':[{'points':[[0,0,-2],[1,0,-2]]}]},
                      {'polylines':[{'points':[[0,0,-2.5],[10,0,-2.5]]}]}]}
        with self.assertRaisesRegex(MotionPlanningError,'Ramp exceeds'):
            plan_ramps_and_links(source,plane())

    def test_keepout_blocks_raster_cleanup_staging_and_low_feeds(self):
        job=self.job(exclusions=[rect(-.2,-5,.2,5)])
        self.assertGreater(job['cleanup_polyline_count'],0)
        plan=plan_ramps_and_links(job,pocket(),obstacle_top=3)
        for move in plan['moves']:
            if move['kind'] in ('travel','retract','clearance_adjust'):continue
            a,b=move['start'],move['end']
            self.assertGreaterEqual(min(abs(a[0]),abs(b[0])),.7-1e-7)
            self.assertGreater(a[0]*b[0],0)
        self.assertEqual(plan['safe_z'],5.54)

    def test_reference_keepout_estimate_is_explicitly_not_original_or_independent(self):
        moves=[{'mode':1,'start':[0,0,-1],'end':[2,0,-1]},
               {'mode':0,'start':[2,0,2],'end':[0,10,2]},
               {'mode':1,'start':[0,10,-1],'end':[2,10,-1]}]
        mask=approximate_reference_keepout(moves,diameter=1,workspace=[-10,-10,20,20])
        self.assertEqual(len(mask['authorized_physical_windows_xyxy_mm']),2)
        self.assertFalse(mask['exact_original_keepout']);self.assertTrue(mask['derived_from_reference_nc'])
        self.assertTrue(mask['exclusions_mm'])
        for polygon in mask['exclusions_mm']:
            x,y=np.mean(polygon,axis=0)
            self.assertFalse(any(a<x<c and b<y<d for a,b,c,d in mask['authorized_physical_windows_xyxy_mm']))


if __name__=='__main__':unittest.main()
