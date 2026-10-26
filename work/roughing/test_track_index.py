import unittest
import math
import numpy as np
from track_index import CutTrackIndex
from motion_planner import _track_depth_supported
from stl_roughing import simplify_collinear
from cleared_area import ClearedArea,capsule,GUARD
from region_core import boolean,pyclipr


class TrackIndexTests(unittest.TestCase):
    def test_boundary_buckets_and_original_provenance_order(self):
        index=CutTrackIndex(1)
        for record in (([0,0,-1],[1,0,-1],7),([9,9,-1],[10,9,-1],9),
                       ([1,0,-2],[2,0,-2],12)):
            index.append(record)
        self.assertEqual([x[2] for x in index.overlapping([1,0,0],[1,0,0])],[7,12])

    def test_long_segment_and_query_fallbacks_are_conservative(self):
        index=CutTrackIndex(.01)
        record=([0,0,-1],[1000,1000,-1])
        index.append(record)
        self.assertEqual(list(index.overlapping([500,500,0],[501,501,0])),[record])
        self.assertEqual(list(index.overlapping([-1,-1,0],[2000,2000,0])),[record])

    def test_indexed_depth_proof_matches_full_scan(self):
        rng=np.random.default_rng(702)
        tracks=[];index=CutTrackIndex(1)
        for _ in range(250):
            y=int(rng.integers(-5,6));x=float(rng.uniform(-10,5));z=-float(rng.uniform(0,4))
            edge=([x,y,z],[x+float(rng.uniform(.1,8)),y,z])
            tracks.append(edge);index.append(edge)
        for _ in range(100):
            x=float(rng.uniform(-10,5));y=int(rng.integers(-5,6));z=-float(rng.uniform(0,5))
            a,b=[x,y,z],[x+float(rng.uniform(.1,8)),y,z]
            self.assertEqual(_track_depth_supported(a,b,tracks,0,.7),
                             _track_depth_supported(a,b,index,0,.7))

    def test_compaction_preserves_all_original_vertices_within_epsilon(self):
        x=np.linspace(0,100,10001);eps=1e-8
        source=np.column_stack((x,np.sin(x)*eps*.2,np.zeros(len(x))))
        result=simplify_collinear(source,epsilon=eps)
        self.assertEqual(len(result),2)
        a,b=np.asarray(result);v=b-a;t=(source-a)@v/(v@v)
        self.assertLessEqual(float(np.linalg.norm(source-a-t[:,None]*v,axis=1).max()),eps)
        self.assertTrue(np.all(np.diff(t)>=0))

    def test_compaction_retains_a_reversal_on_a_line(self):
        points=[[0,0,0],[1,0,0],[2,0,0],[1,0,0],[0,0,0]]
        self.assertEqual(simplify_collinear(points),[[0,0,0],[2,0,0],[0,0,0]])

    def test_local_area_proof_matches_global_union_on_bucket_edges_and_slopes(self):
        rng=np.random.default_rng(1729)
        for diameter in (.6,2.0,3.175):
            area=ClearedArea(diameter,0);cuts=[]
            for y in np.linspace(-diameter,diameter,7):
                edge=([-4,y,-2],[4,y,-2]);cuts.append(edge);area.add(*edge)
            for _ in range(12):
                a=rng.uniform([-6,-4,-3],[6,4,0]);b=a+rng.uniform([-.8,-.8,-.5],[.8,.8,.5])
                cuts.append((a,b));area.add(a,b)
            for query in range(20):
                a=[float(rng.uniform(-2,2)),float(rng.uniform(-diameter,diameter)),-3]
                b=a if query%3==0 else [a[0]+.6,a[1],-3]
                height=-2 if query%2==0 else -2.5
                eligible=[p for c,e in cuts if max(c[2],e[2])<=height
                          for p in capsule(c,e,diameter/2-GUARD)]
                if eligible:
                    old_union=boolean(eligible,[],pyclipr.Union)
                    radius=diameter/2+GUARD
                    if math.dist(a[:2],b[:2])<1e-12:radius/=math.cos(math.pi/128)
                    expected=not boolean(capsule(a,b,radius),old_union,pyclipr.Difference)
                else:expected=False
                self.assertEqual(area.covers(a,b,height),expected)

    def test_cached_xy_capsule_does_not_credit_an_ineligible_depth(self):
        area=ClearedArea(2,0)
        for y in (-.3,.3):area.add([-3,y,-1],[3,y,-1])
        self.assertTrue(area.covers([-1,0,-2],[1,0,-2],-1))
        self.assertFalse(area.covers([-1,0,-2],[1,0,-2],-1.1))
        for y in (-.3,.3):area.add([-3,y,-2],[3,y,-2])
        self.assertTrue(area.covers([-1,0,-3],[1,0,-3],-2))


if __name__=='__main__':unittest.main()
