import copy
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from fixture_travel import FixtureTravel
from grbl_post import export_grbl
from motion_planner import validate_motion,MotionPlanningError
import test_smart_released_part as fixtures
rect=fixtures.rect


class FixtureTravelTests(unittest.TestCase):
    def policy(self,regions=None):
        return {'mode':'avoid_keepout_xy','regions_mm':regions or [rect(-2,-2,2,2)],
                'cutter_radius_mm':1,'margin_mm':.01}

    def test_direct_clear_and_detour_routes_preserve_height_and_tool_footprint(self):
        router=FixtureTravel(self.policy())
        a=[-10,0,5];b=[10,0,5]
        self.assertFalse(router.clear(a,b));path=router.route(a,b)
        self.assertEqual(path[0],a);self.assertEqual(path[-1],b);self.assertGreater(len(path),2)
        self.assertTrue(all(p[2]==5 for p in path))
        self.assertTrue(all(router.clear(p,q) for p,q in zip(path,path[1:])))
        self.assertEqual(router.route([-10,8,5],[10,8,5]),[[-10,8,5],[10,8,5]])
        with self.assertRaisesRegex(ValueError,'dentro da fixação'):router.route([0,0,5],b)

    def test_multiple_and_concave_fixtures_never_use_a_collision_fallback(self):
        shapes=[rect(-6,-2,-3,2),rect(3,-2,6,2)]
        router=FixtureTravel(self.policy(shapes));path=router.route([-12,0,7],[12,0,7])
        self.assertTrue(all(router.clear(p,q) for p,q in zip(path,path[1:])))
        concave=[[-5,-5],[5,-5],[5,5],[2,5],[2,-2],[-2,-2],[-2,5],[-5,5]]
        router=FixtureTravel(self.policy([concave]));path=router.route([0,2,5],[0,12,5])
        self.assertTrue(all(router.clear(p,q) for p,q in zip(path,path[1:])))

    def test_legacy_without_fixture_policy_is_unchanged(self):
        router=FixtureTravel(None);self.assertEqual(router.route([0,0,5],[9,9,5]),[[0,0,5],[9,9,5]])

    def test_independent_replay_rejects_a_forged_straight_rapid_over_clamp(self):
        from motion_planner import plan_ramps_and_links
        from test_stl_roughing import plane
        source={'tool':{'diameter':2,'length':10},'parameters':{'z_top':0,'stepdown':1},
                'layers':[],'fixture_travel':self.policy()}
        plan=plan_ramps_and_links(source,plane(lambda x,y:-1),stock_top=0,obstacle_top=2,
                                  clearance=3,initial_position=[-10,0,5])
        plan['moves']=[{'id':0,'kind':'travel','start':[-10,0,5],'end':[10,0,5],'proof':{}}]
        plan['final_position']=[10,0,5]
        with self.assertRaisesRegex(MotionPlanningError,'cruza a fixação'):validate_motion(plan,source)


if __name__=='__main__':unittest.main()
