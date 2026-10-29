"""Independent counterexamples for completed-cut low-link routing.

These assertions check the emitted movement against the replay proof. A graph
connection, metadata flag or a future path is never accepted as clearance.
"""
import copy
import math
import unittest

import numpy as np

from cleared_area import ClearedArea
from motion_planner import (MotionPlanningError,_cleared_link_supported,
    _completed_cut_route,plan_ramps_and_links,validate_motion)
from track_index import CutTrackIndex


MESH=np.asarray([[[-20,-20,-4],[20,-20,-4],[20,20,-4]]],float)


def source(layers):
    return {'parameters':{'z_top':0,'stepdown':1},
        'tool':{'diameter':1,'length':10},
        'layers':[{'polylines':[{'points':points} for points in layer]} for layer in layers]}


def state(edges):
    tracks=CutTrackIndex(1);area=ClearedArea(1,0)
    for a,b in edges:tracks.append((a,b));area.add(a,b)
    return tracks,area


class LowLinkAuditTests(unittest.TestCase):
    def test_old_elbow_routes_every_leg_but_not_the_uncut_diagonal(self):
        tracks,area=state([([0,0,-1],[0,5,-1]),([0,5,-1],[5,5,-1])])
        start,end=[5,5,-1],[0,0,-1]
        self.assertFalse(_cleared_link_supported(start,end,tracks,area))
        route=_completed_cut_route(start,end,tracks,area,max_length=20)
        self.assertIsNotNone(route)
        self.assertEqual(route[0],start);self.assertEqual(route[-1],end)
        self.assertGreater(sum(math.dist(a,b) for a,b in zip(route,route[1:])),math.dist(start,end))
        for a,b in zip(route,route[1:]):
            self.assertEqual(a[2],-1);self.assertEqual(b[2],-1)
            self.assertTrue(_cleared_link_supported(a,b,tracks,area))

    def test_disconnected_endpoints_and_future_elbow_never_make_a_corridor(self):
        tracks,area=state([([4,5,-1],[5,5,-1]),([0,0,-1],[0,1,-1])])
        self.assertIsNone(_completed_cut_route([5,5,-1],[0,0,-1],tracks,area,max_length=20))
        # A future bridge would make the route possible, but it must not enter
        # the chronological proof state until its actual cut has completed.
        future=[([0,0,-1],[0,5,-1]),([0,5,-1],[5,5,-1])]
        for a,b in future:tracks.append((a,b));area.add(a,b)
        self.assertIsNotNone(_completed_cut_route([5,5,-1],[0,0,-1],tracks,area,max_length=20))

    def test_high_end_of_old_ramp_is_not_a_horizontal_clearance_floor(self):
        tracks,area=state([([0,0,-2],[0,5,-.5]),([0,5,-2],[5,5,-2])])
        self.assertIsNone(_completed_cut_route([5,5,-1],[0,0,-1],tracks,area,max_length=20))
        flat,area2=state([([0,0,-2],[0,5,-2]),([0,5,-2],[5,5,-2])])
        self.assertIsNotNone(_completed_cut_route([5,5,-1],[0,0,-1],flat,area2,max_length=20))
        self.assertIsNone(_completed_cut_route([5,5,-2.1],[0,0,-2.1],flat,area2,max_length=20))

    def test_domain_gate_and_length_budget_are_applied_to_the_entire_route(self):
        tracks,area=state([([0,0,-1],[0,5,-1]),([0,5,-1],[5,5,-1])])
        self.assertIsNone(_completed_cut_route([5,5,-1],[0,0,-1],tracks,area,max_length=6))
        def disallow_vertical(a,b):return not (abs(a[0])<1e-8 and abs(b[0])<1e-8)
        self.assertIsNone(_completed_cut_route([5,5,-1],[0,0,-1],tracks,area,
            max_length=20,edge_allowed=disallow_vertical))

    def test_microscopic_endpoint_gap_at_nc_rounding_boundary_is_not_a_join(self):
        # The two X values round to different NC5 positions even though their
        # real distance is below the planner EPS. Merging them by EPS would
        # invent a horizontal connector and credit an uncut end-cap sliver.
        left=1.000004999;right=1.000005001
        self.assertNotEqual(round(left,5),round(right,5))
        tracks,area=state([([0,0,-1],[left,0,-1]),([right,0,-1],[2,0,-1])])
        route=_completed_cut_route([0,0,-1],[2,0,-1],tracks,area,max_length=4)
        self.assertIsNone(route)

    def test_sub_eps_old_height_above_nc_rounding_boundary_is_not_a_floor(self):
        old=-1.000004999;requested=-1.000005001
        self.assertGreater(round(old,5),round(requested,5))
        tracks,area=state([([0,0,old],[0,5,old]),([0,5,old],[5,5,old])])
        self.assertIsNone(_completed_cut_route([5,5,requested],[0,0,requested],
            tracks,area,max_length=20))

    def test_replay_rejects_a_diagonal_shortcut_of_the_planned_old_elbow(self):
        job=source([[[[0,0,-1],[0,5,-1],[5,5,-1]]],
            [[[3,5,-2],[5,5,-2]],[[0,0,-2],[0,2,-2]]]])
        plan=plan_ramps_and_links(job,MESH,path_order='region_first')
        self.assertEqual(validate_motion(plan,job)['status'],'passed')
        links=[m for m in plan['moves'] if m['kind']=='link_cleared'
               and m.get('layer')==1 and m.get('polyline')==1]
        self.assertGreaterEqual(len(links),2)
        forged=copy.deepcopy(plan)
        first=forged['moves'][links[0]['id']]
        following=forged['moves'][links[1]['id']]
        # Keep continuity at the shared point, so this is a clearance test,
        # not merely rejection of a broken movement list.
        first['end']=[2.5,2.5,-1];following['start']=[2.5,2.5,-1]
        with self.assertRaisesRegex(MotionPlanningError,'Low link'):
            validate_motion(forged,job)


if __name__=='__main__':unittest.main()
