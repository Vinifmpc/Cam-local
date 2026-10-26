"""Clearance acceleration must preserve material proofs and bounded staging."""
import math
import unittest
from unittest.mock import patch
import numpy as np
from cleared_area import ClearedArea,capsule,GUARD
from depth_staging import stage_paths
from region_core import boolean,pyclipr


def global_proof(cuts,a,b,height,diameter):
    clips=[polygon for c,e in cuts if max(c[2],e[2])<=height
           for polygon in capsule(c,e,diameter/2-GUARD)]
    if not clips:return False
    radius=diameter/2+GUARD
    if math.dist(a[:2],b[:2])<1e-12:radius/=math.cos(math.pi/128)
    return not boolean(capsule(a,b,radius),clips,pyclipr.Difference)


class UncachedArea(ClearedArea):
    def _union(self,subjects):
        return boolean(subjects,[],pyclipr.Union)


def square(x=0,dtype=float):
    return np.array([[x,0],[x+1,0],[x+1,1],[x,1]],dtype=dtype)


class ClearanceOptimizationTests(unittest.TestCase):
    def test_union_reuses_exact_copies_but_not_mutation_order_or_dtype(self):
        area=ClearedArea(2,0);a=square();b=square(2)
        with patch('cleared_area.boolean',wraps=boolean) as native:
            first=area._union([a,b])
            copied=area._union([np.asfortranarray(a),b.copy()])
            self.assertEqual(native.call_count,1)
            self.assertEqual(len(first),len(copied))
            for original,cached in zip(first,copied):
                np.testing.assert_array_equal(original,cached)
            # Even differences below Clipper's coordinate resolution must
            # miss: the key never rounds or normalizes input geometry.
            a[0,0]+=1e-12
            area._union([a,b])
            area._union([b,a])
            area._union([b.astype(np.float32),a.astype(np.float32)])
            self.assertEqual(native.call_count,4)
        self.assertEqual(area.union_cache_hits,1)
        self.assertEqual(area.union_cache_misses,4)

    def test_union_lru_is_bounded_and_retains_the_recently_used_entry(self):
        area=ClearedArea(2,0);a,b,c=[square(x) for x in (0,2,4)]
        with patch('cleared_area.MAX_UNION_ENTRIES',2):
            with patch('cleared_area.boolean',wraps=boolean) as native:
                for polygon in (a,b,a,c,a,b):area._union([polygon])
                self.assertEqual(native.call_count,4)
                self.assertEqual(area.union_cache_hits,2)
                self.assertEqual(len(area.union_cache),2)

    def test_union_byte_limit_evicts_and_does_not_retain_oversized_entries(self):
        area=ClearedArea(2,0);a=square()
        result=area._union([a])
        minimum=a.nbytes+sum(np.asarray(p).nbytes for p in result)
        self.assertGreaterEqual(area.union_cache_bytes,minimum)
        budget=area.union_cache_bytes
        limited=ClearedArea(2,0)
        with patch('cleared_area.MAX_UNION_BYTES',budget):
            limited._union([a]);limited._union([square(2)])
            self.assertEqual(len(limited.union_cache),1)
            self.assertLessEqual(limited.union_cache_bytes,budget)
            limited._union([square(2)])
            self.assertEqual(limited.union_cache_hits,1)
        oversized=ClearedArea(2,0)
        with patch('cleared_area.MAX_UNION_BYTES',minimum-1):
            oversized._union([a]);oversized._union([a.copy()])
            self.assertEqual(oversized.union_cache_hits,0)
            self.assertEqual(len(oversized.union_cache),0)
            self.assertEqual(oversized.union_cache_bytes,0)

    def test_union_empty_results_are_reused_and_cache_is_instance_local(self):
        first=ClearedArea(2,0);second=ClearedArea(4,0)
        with patch('cleared_area.boolean',return_value=[]) as native:
            self.assertEqual(first._union([square()]),[])
            self.assertEqual(first._union([square()]),[])
            self.assertEqual(second._union([square()]),[])
            self.assertEqual(native.call_count,2)
        self.assertEqual(first.union_cache_hits,1)
        self.assertEqual(second.union_cache_hits,0)
        self.assertIsNot(first.union_cache,second.union_cache)
        wide=ClearedArea(2,0);narrow=ClearedArea(.1,0)
        for y in (-.3,.3):
            for area in (wide,narrow):area.add([-3,y,-1],[3,y,-1])
        self.assertTrue(wide.covers([-1,0,-2],[1,0,-2],-1))
        self.assertFalse(narrow.covers([-1,0,-2],[1,0,-2],-1))

    def test_cached_real_proofs_match_uncached_after_deeper_completed_cuts(self):
        cached=ClearedArea(2,0);uncached=UncachedArea(2,0)
        queries=[([-2,0,-3],[2,0,-3]),([2,0,-3],[-2,0,-3]),
                 ([-2,.25,-3],[2,.25,-3]),([-2,2,-3],[2,2,-3]),
                 ([0,0,-3],[0,0,-3])]
        observed=[]
        for completed_depth in (-.5,-1.5,-2):
            for y in np.linspace(-.8,.8,40):
                a,b=[-4,float(y),completed_depth],[4,float(y),completed_depth]
                cached.add(a,b);uncached.add(a,b)
            for height in (0,-.5,-1,-1.5,-2,-2.01):
                for a,b in queries:
                    with self.subTest(completed=completed_depth,height=height,a=a,b=b):
                        expected=uncached.covers(a,b,height,require_cut=True)
                        self.assertEqual(cached.covers(a,b,height,require_cut=True),expected)
                        observed.append(expected)
        self.assertIn(True,observed);self.assertIn(False,observed)
        self.assertGreater(cached.proofs,0)

    def test_subset_proof_still_requires_final_difference_at_each_new_height(self):
        area=ClearedArea(2,0)
        for y in np.linspace(-.8,.8,40):area.add([-4,float(y),-2],[4,float(y),-2])
        with patch('cleared_area.boolean',wraps=boolean) as native:
            for height in (-1,-2):
                self.assertTrue(area.covers([-2,0,-3],[2,0,-3],height))
        differences=[call for call in native.call_args_list if call.args[2]==pyclipr.Difference]
        self.assertEqual(len(differences),2)
        self.assertEqual(area.proofs,2)

    def test_dense_overlapping_capsules_preserve_global_proof_at_multiple_heights(self):
        diameter=3.175;area=ClearedArea(diameter,0);cuts=[]
        # Similar to the faceted cleanup loops that made the full job spend
        # minutes at 34%: many nearby arcs repeated at different depths.
        for z in (-.7,-1.4,-2.1):
            for angle in np.linspace(0,2*math.pi,96,endpoint=False):
                a=[2*math.cos(angle),2*math.sin(angle),z]
                b=[2*math.cos(angle+.09),2*math.sin(angle+.09),z]
                cuts.append((a,b));area.add(a,b)
        queries=[([2,0,-3],[2,.25,-3]),([0,0,-3],[0,.2,-3]),
                 ([3,0,-3],[3,.2,-3]),([2,0,-3],[2,0,-3])]
        for height in (-.7,-1.5,-2.1,-2.2):
            for a,b in queries:
                with self.subTest(height=height,a=a,b=b):
                    self.assertEqual(area.covers(a,b,height),
                                     global_proof(cuts,a,b,height,diameter))

    def test_duplicate_xy_depth_dominance_requires_the_highest_endpoint(self):
        area=ClearedArea(2,0)
        for y in (-.3,.3):
            area.add([-3,y,-3],[3,y,0])
            area.add([3,y,-1],[-3,y,-1])
            area.add([-3,y,-.5],[3,y,-.5])
        self.assertTrue(area.covers([-1,0,-2],[1,0,-2],-1))
        self.assertFalse(area.covers([-1,0,-2],[1,0,-2],-1.01))
        # Later completed cuts can make a failed query valid.
        for y in (-.3,.3):area.add([-3,y,-2],[3,y,-2])
        self.assertTrue(area.covers([-1,0,-3],[1,0,-3],-2))
        self.assertTrue(area.covers([-1,0,-2],[1,0,-2],-1))

    def test_vertex_selection_does_not_approve_an_uncut_interior_hole(self):
        area=ClearedArea(1,0);cuts=[]
        angles=np.linspace(0,2*math.pi,96,endpoint=False)
        for angle in angles:
            a=[.8*math.cos(angle),.8*math.sin(angle),-1]
            b=[.8*math.cos(angle+.08),.8*math.sin(angle+.08),-1]
            area.add(a,b);cuts.append((a,b))
        # The full boundary is covered, but material remains at the centre.
        self.assertFalse(area.covers([0,0,-2],[0,0,-2],-1))
        self.assertFalse(global_proof(cuts,[0,0,-2],[0,0,-2],-1,1))

    def test_local_subset_reuse_checks_depth_and_matches_global_proof(self):
        area=ClearedArea(2,0);cuts=[]
        for y in np.linspace(-.8,.8,48):
            a,b=[-4,float(y),-1],[4,float(y),-1]
            area.add(a,b);cuts.append((a,b))
        self.assertTrue(area.covers([0,0,-2],[.1,0,-2],-1))
        self.assertTrue(area.local_subsets)
        for height in (-1,-1.01):
            for x in (0,.1,.3):
                a,b=[x,.05,-2],[x+.15,.05,-2]
                self.assertEqual(area.covers(a,b,height),global_proof(cuts,a,b,height,2))
        # A later traversal changes eligibility but never the XY footprint.
        for a,b in cuts:area.add([*a[:2],-2],[*b[:2],-2])
        self.assertTrue(area.covers([0,.05,-3],[.1,.05,-3],-2))

    def test_staging_retains_an_actionable_resource_budget(self):
        layers=[{'polylines':[{'kind':'cleanup','points':
                              [[0,0,-.5],[1,0,-.5],[1,1,-.5],[0,1,-.5]]}]}]
        with patch('depth_staging.MAX_STAGED_EDGES',2):
            with self.assertRaisesRegex(ValueError,'Reduza a área ou profundidade'):
                stage_paths(layers,diameter=1,stock_top=0,stepdown=1)


if __name__=='__main__':unittest.main()
