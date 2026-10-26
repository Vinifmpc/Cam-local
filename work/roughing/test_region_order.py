import copy
from collections import Counter
import math
import unittest
import numpy as np
from motion_planner import plan_ramps_and_links,validate_motion,_cleared_link_supported,MotionPlanningError
from cleared_area import ClearedArea
from region_order import region_first
from cam_operations import OperationSettings
from roughing_compare import swept_floor


MESH=np.asarray([[[-20,-20,-4],[20,-20,-4],[20,20,-4]]],float)
def job(layers,diameter=1):return {'parameters':{'z_top':0,'stepdown':1},'tool':{'diameter':diameter,'length':10},
    'layers':[{'polylines':[{'points':p} for p in layer]} for layer in layers]}
def cuts(plan):return Counter((tuple(m['start']),tuple(m['end'])) for m in plan['moves'] if m['kind']=='cut')
def segments(plan):return [[m['start'],m['end']] for m in plan['moves'] if m['kind'] not in ('travel','retract','clearance_adjust')]


class RegionOrderTests(unittest.TestCase):
    def test_two_pockets_finish_all_depths_before_travelling_between_them(self):
        j=job([[[[0,0,-z],[5,0,-z]],[[0,30,-z],[5,30,-z]]] for z in (1,2,3)])
        old=plan_ramps_and_links(j,MESH);new=plan_ramps_and_links(j,MESH,path_order='region_first')
        self.assertEqual(cuts(old),cuts(new));self.assertEqual(new['region_schedule']['region_count'],2)
        self.assertEqual([e['region'] for e in new['entries']],[0,0,0,1,1,1])
        self.assertEqual([e['layer'] for e in new['entries']],[0,1,2,0,1,2])
        self.assertLess(new['length_mm']['travel'],old['length_mm']['travel']/3)
        query=np.asarray([[x,y] for x in np.arange(-1,6,.25) for y in np.arange(-1,32,.5)])
        np.testing.assert_allclose(swept_floor(query,segments(old),diameter=1),
                                   swept_floor(query,segments(new),diameter=1),atol=1e-8,rtol=0)

    def test_exact_retrace_uses_low_link_without_retract_or_new_material_removal(self):
        j=job([[[[0,0,-1],[10,0,-1]],[[4,0,-1],[7,0,-1]]]])
        old=plan_ramps_and_links(j,MESH);new=plan_ramps_and_links(j,MESH,path_order='region_first')
        self.assertEqual(new['stay_down_entries'],1)
        self.assertEqual(new['validation']['low_links_with_completed_cut_proof'],1)
        self.assertEqual(new['move_counts']['retract'],1)
        self.assertEqual(cuts(old),cuts(new))
        self.assertEqual(next(m for m in new['moves'] if m['kind']=='link_cleared')['end'],[4,0,-1])

    def test_partial_stock_clearance_never_proves_a_link_across_uncut_gap_or_high_fixture(self):
        area=ClearedArea(1,0);a=[0,0,0];b=[4,0,0];area.add(a,b)
        self.assertFalse(_cleared_link_supported(b,[10,0,0],[(a,b)],area))
        self.assertFalse(_cleared_link_supported([4,0,-1],[10,0,-1],[(a,b)],area))
        j=job([[[[0,0,-1],[4,0,-1]],[[10,0,-1],[14,0,-1]]]])
        plan=plan_ramps_and_links(j,MESH,path_order='region_first',obstacle_top=5)
        self.assertEqual(plan['stay_down_entries'],0)
        for m in plan['moves']:
            if m['kind']=='travel':self.assertEqual(m['start'][2],7.54)

    def test_replay_rejects_tampered_low_link(self):
        j=job([[[[0,0,-1],[10,0,-1]],[[4,0,-1],[7,0,-1]]]])
        plan=plan_ramps_and_links(j,MESH,path_order='region_first')
        bad=copy.deepcopy(plan);link=next(m for m in bad['moves'] if m['kind']=='link_cleared')
        link['end'][1]=2
        with self.assertRaisesRegex(MotionPlanningError,'Low link'):validate_motion(bad,j)

    def test_upper_bridge_keeps_clearance_dependencies_in_one_group(self):
        # The first upper pass connects both deep pockets. Conservatively keep
        # the whole dependency group, preserving preparation before descent.
        j=job([[[[0,0,-1],[20,0,-1]]],
               [[[0,0,-2],[5,0,-2]],[[15,0,-2],[20,0,-2]]]])
        plan=plan_ramps_and_links(j,MESH,path_order='region_first')
        self.assertEqual(plan['region_schedule']['region_count'],1)
        self.assertEqual([e['layer'] for e in plan['entries']],[0,1,1])
        self.assertEqual(plan['validation']['status'],'passed')

    def test_closed_ring_and_disconnected_island_inside_its_hole_are_distinct(self):
        ring=[[-10,-10,-1],[10,-10,-1],[10,10,-1],[-10,10,-1],[-10,-10,-1]]
        line=[[-1,0,-1],[1,0,-1]]
        paths=[(0,0,ring),(0,1,line),(1,0,[[x,y,z-1] for x,y,z in ring]),(1,1,[[x,y,z-1] for x,y,z in line])]
        ordered,mapping,meta=region_first(paths,1)
        self.assertEqual(meta['region_count'],2)
        self.assertEqual(mapping[0,0],mapping[1,0]);self.assertNotEqual(mapping[0,0],mapping[0,1])
        self.assertEqual([p[:2] for p in ordered],[(0,0),(1,0),(0,1),(1,1)])

    def test_initial_position_can_choose_nearer_region_without_changing_cut_geometry(self):
        j=job([[[[0,0,-1],[5,0,-1]],[[0,30,-1],[5,30,-1]]]])
        plan=plan_ramps_and_links(j,MESH,path_order='region_first',initial_position=[0,31,2.54])
        self.assertEqual(plan['region_schedule']['visit_order'],[1,0])
        self.assertEqual(plan['entries'][0]['polyline'],1)

    def test_empty_and_invalid_modes(self):
        self.assertEqual(plan_ramps_and_links(job([[]]),MESH,path_order='region_first')['moves'],[])
        with self.assertRaises(ValueError):OperationSettings(roughing_order='bad')
        with self.assertRaises(ValueError):plan_ramps_and_links(job([[]]),MESH,path_order='bad')


if __name__=='__main__':unittest.main()
