"""Short low connectors must go inward before turning at a cut boundary."""
import math
import unittest

from cleared_area import ClearedArea
from motion_planner import _cleared_link_supported,_completed_cut_route
from track_index import CutTrackIndex


class RoughLowLinksTests(unittest.TestCase):
    def raster_stock(self,rows,depth=-1):
        completed=CutTrackIndex(1);area=ClearedArea(1,0)
        for y in rows:
            a,b=[0,y,depth],[4,y,depth]
            completed.append((a,b));area.add(a,b)
        return completed,area

    def test_short_interior_backtrack_avoids_a_whole_row_return(self):
        completed,area=self.raster_stock([-.25,0,.25,.5,.75,1,1.25])
        a,b=[4,0,-1],[4,1,-1]
        # The endpoint cap scallops do not prove the straight boundary chord.
        self.assertFalse(_cleared_link_supported(a,b,completed,area))
        route=_completed_cut_route(a,b,completed,area,2)
        self.assertIsNotNone(route)
        self.assertEqual(route[0],a);self.assertEqual(route[-1],b)
        self.assertTrue(any(p[0]<3.99 for p in route[1:-1]))
        self.assertLessEqual(sum(math.dist(c,e) for c,e in zip(route,route[1:])),2)
        self.assertTrue(all(_cleared_link_supported(c,e,completed,area)
                            for c,e in zip(route,route[1:])))

    def test_a_material_bridge_between_rows_still_prevents_the_low_route(self):
        completed,area=self.raster_stock([-.25,0,1.1,1.35])
        self.assertIsNone(_completed_cut_route([4,0,-1],[4,1.1,-1],completed,area,2))

    def test_route_budget_and_allowed_domain_remain_hard_limits(self):
        completed,area=self.raster_stock([-.25,0,.25,.5,.75,1,1.25])
        a,b=[4,0,-1],[4,1,-1]
        self.assertIsNone(_completed_cut_route(a,b,completed,area,1))
        # A protected strip can leave both endpoints legal while forbidding
        # the inward turn. Graph connectivity never overrides this policy.
        allowed=lambda c,e:min(c[0],e[0])>=3.99
        self.assertIsNone(_completed_cut_route(a,b,completed,area,2,allowed))

    def test_a_shallower_old_pass_never_proves_a_deeper_low_route(self):
        completed,area=self.raster_stock([-.25,0,.25,.5,.75,1,1.25],depth=-.5)
        self.assertIsNone(_completed_cut_route([4,0,-1],[4,1,-1],completed,area,2))


if __name__=='__main__':unittest.main()
