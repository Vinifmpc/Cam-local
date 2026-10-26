import copy
import unittest
import numpy as np

from stl_roughing import generate_stl_roughing,simplify_collinear
from motion_planner import plan_ramps_and_links,MotionPlanningError,_track_depth_supported
from roughing_compare import swept_floor,compare_sweeps
from cam_project import RoughingSettings
from test_stl_roughing import plane,rect,all_edges
from test_motion_planner import job_for_layers


class RoughingV2Tests(unittest.TestCase):
    def job(self,mesh,**extra):
        values=dict(diameter=1,tool_length=10,stepdown=1,stepover=.8,sampling=.2,
                    z_top=0,z_bottom=-3,boundaries=[rect(-3,-2,3,2)])
        values.update(extra)
        return generate_stl_roughing(mesh,**values)

    def test_planar_slope_every_point_stays_at_layer_and_above_contact(self):
        mesh=plane(lambda x,y:-3+.2*x)
        job=self.job(mesh,strategy='planar',compress_collinear=True)
        self.assertGreater(job['cutting_edges'],0)
        for layer,a,b in all_edges(job):
            self.assertEqual(a[2],layer['z']);self.assertEqual(b[2],layer['z'])
            for t in (0,.25,.5,.75,1):
                p=np.array(a)*(1-t)+np.array(b)*t
                self.assertGreaterEqual(p[2]+1e-8,-3+.2*p[0]+.1)

    def test_rotated_raster_clears_physical_keepout_and_matches_direction(self):
        job=self.job(plane(),raster_angle_deg=37,exclusions=[rect(-.4,-.4,.4,.4)])
        edges=list(all_edges(job));self.assertTrue(edges)
        direction=np.array([np.cos(np.deg2rad(37)),np.sin(np.deg2rad(37))])
        for layer,a,b in edges:
            d=np.array(b[:2])-a[:2]
            self.assertAlmostEqual(d[0]*direction[1]-d[1]*direction[0],0,places=8)
            # Sample every edge; rectangle clearance is analytic at each point.
            for t in np.linspace(0,1,7):
                p=np.array(a)*(1-t)+np.array(b)*t
                delta=np.maximum(np.abs(p[:2])-.4,0)
                self.assertGreaterEqual(np.linalg.norm(delta),.5-1e-8)

    def test_compaction_preserves_swept_floor_and_reduces_edges(self):
        a=self.job(plane());b=self.job(plane(),compress_collinear=True)
        self.assertLess(b['cutting_edges'],a['cutting_edges']/5)
        self.assertEqual(b['polyline_count'],a['polyline_count'])
        self.assertAlmostEqual(b['cutting_length_mm'],a['cutting_length_mm'])
        def segments(job):return [[u,v] for _,u,v in all_edges(job)]
        probes=np.random.default_rng(42).uniform([-4,-3],[4,3],(200,2))
        old=swept_floor(probes,segments(a),diameter=1)
        new=swept_floor(probes,segments(b),diameter=1)
        np.testing.assert_allclose(old,new,atol=1e-9,rtol=0)
        plan=plan_ramps_and_links(b,plane())
        self.assertEqual(plan['validation']['status'],'passed')

    def test_compaction_keeps_corner_and_reversal(self):
        points=[[0,0,0],[1,0,0],[2,0,0],[1,0,0],[1,1,0]]
        self.assertEqual(simplify_collinear(points),[[0,0,0],[2,0,0],[1,0,0],[1,1,0]])
        self.assertEqual(simplify_collinear([[0,0,0],[1,0,1],[2,0,0]]),[[0,0,0],[1,0,1],[2,0,0]])

    def test_compaction_does_not_skip_thin_ridge(self):
        mesh=np.concatenate([plane(lambda x,y:-3),plane(lambda x,y:-.1,x0=.45,x1=.55,y0=-3,y1=3)])
        job=self.job(mesh,diameter=.2,sampling=1,stepover=.5,z_bottom=-3,
                     boundaries=[rect(0,-1,1,1)],compress_collinear=True)
        for _,a,b in all_edges(job):self.assertGreaterEqual(min(a[2],b[2]),-.10000001)

    def test_segment_union_proves_depth_across_different_subdivisions(self):
        previous=[([0,0,-1],[2,0,-1]),([2,0,-1],[5,0,-1])]
        self.assertTrue(_track_depth_supported([0,0,-2],[5,0,-2],previous,0,1))
        self.assertTrue(_track_depth_supported([5,0,-2],[0,0,-2],previous,0,1))
        self.assertFalse(_track_depth_supported([0,0,-2],[5,0,-2],
            [([0,0,-1],[2,0,-1]),([2.1,0,-1],[5,0,-1])],0,1))
        self.assertFalse(_track_depth_supported([0,0,-2],[5,0,-2],
            [([0,.01,-1],[5,.01,-1])],0,1))

    def test_interval_proof_rejects_hidden_depth_inside_source_span(self):
        old=[([0,0,-1],[2,0,-.1]),([2,0,-.1],[5,0,-1])]
        self.assertFalse(_track_depth_supported([0,0,-2],[5,0,-2],old,0,1))

    def test_reentry_on_previously_cut_segment_interior(self):
        source=job_for_layers([[[[0,0,-1],[5,0,-1]]],[[[2,0,-2],[5,0,-2]]]])
        plan=plan_ramps_and_links(source,plane())
        self.assertEqual(plan['entries'][1]['cleared_floor'],-1)
        self.assertEqual(plan['validation']['status'],'passed')

    def test_invalid_new_parameters_rejected(self):
        for extra in ({'strategy':'magic'},{'raster_angle_deg':float('nan')},
                      {'raster_angle_deg':180},{'compress_collinear':1}):
            with self.subTest(extra=extra),self.assertRaises(ValueError):self.job(plane(),**extra)

    def test_swept_floor_slope_caps_vertical_and_empty(self):
        p=[[5,0],[5,1],[5,2],[-1,0],[11,0]]
        heights=swept_floor(p,[[[0,0,0],[10,0,-10]]],diameter=2)
        np.testing.assert_allclose(heights,[-6,-5,0,0,-10])
        heights=swept_floor([[2,2],[3.1,2]],[[[2,2,1],[2,2,-3]]],diameter=2)
        np.testing.assert_array_equal(heights,[-3,0])
        np.testing.assert_array_equal(swept_floor([[0,0]],[],diameter=1),[0])

    def test_sweep_comparison_sign_and_grid_limit(self):
        old=[[[0,0,-1],[2,0,-1]]];new=[[[0,0,-2],[2,0,-2]]]
        summary,data=compare_sweeps(old,new,diameter=1,spacing=.2)
        self.assertGreater(summary['generated_deeper_by_more_than_0_1_mm_points'],0)
        self.assertEqual(summary['generated_shallower_by_more_than_0_1_mm_points'],0)
        with self.assertRaises(ValueError):compare_sweeps(old,new,diameter=1,spacing=.0001)


if __name__=='__main__':unittest.main()
