"""Continuous annular roughing keeps walls, depth and stock removal."""
from dataclasses import replace
import math
from pathlib import Path
import tempfile
import unittest
import numpy as np
from annular_pocket import annular_contours
from grbl_post import export_grbl
from smart_planner import _edge_in_domain
import test_smart_released_part as fixtures


def circles():
    angles=np.linspace(0,2*np.pi,64,endpoint=False)
    xy=np.c_[np.cos(angles),np.sin(angles)]
    return [xy*12,(xy*8)[::-1]]


def stepped_ring():
    profile=[(8,-4),(14,-4),(14,0),(11,0),(11,-1.8),(8,-1.8)]
    triangles=[]
    for i in range(48):
        a,b=2*math.pi*i/48,2*math.pi*(i+1)/48
        p=lambda r,z,t:[r*math.cos(t),r*math.sin(t),z]
        for (r,z),(s,w) in zip(profile,profile[1:]+profile[:1]):
            v=[p(r,z,a),p(r,z,b),p(s,w,b),p(s,w,a)]
            triangles.extend([[v[0],v[1],v[2]],[v[0],v[2],v[3]]])
    return np.array(triangles,float)


class AnnularTests(unittest.TestCase):
    def candidate(self,regions=None,**kw):
        args=dict(stepover=.8,tool_radius=1,tolerance=.02,raster_length=400,cleanup_length=130,raster_count=100)
        args.update(kw)
        return annular_contours(circles() if regions is None else regions,**args)

    def test_loops_are_closed_inside_original_domain_with_area_coverage_proof(self):
        result=self.candidate();self.assertIsNotNone(result)
        sources,proof=result;allowed=[p.tolist() for p in circles()]
        self.assertEqual(proof['method'],'guarded_annular_contour_coverage')
        self.assertLessEqual(proof['physical_boundary_tolerance_mm'],.02)
        for kind,_,path in sources:
            self.assertEqual(kind,'cleanup');self.assertEqual(path[0],path[-1])
            self.assertTrue(all(_edge_in_domain(a,b,allowed) for a,b in zip(path,path[1:])))
        edges=np.array([[a,b] for _,_,p in sources for a,b in zip(p,p[1:])])
        # Independent Euclidean swept-disk oracle in the annular material.
        points=np.array([[r*math.cos(t),r*math.sin(t)] for r in np.linspace(7.1,12.9,41) for t in np.linspace(0,2*math.pi,96,endpoint=False)])
        d=edges[:,1]-edges[:,0];q=points[:,None]-edges[None,:,0];t=np.clip((q*d).sum(axis=2)/(d*d).sum(axis=1),0,1)
        nearest=np.linalg.norm(q-t[:,:,None]*d,axis=2).min(axis=1)
        self.assertLessEqual(float(nearest.max()),1.)

    def test_strict_precision_nonannular_or_unprofitable_cases_keep_original_strategy(self):
        self.assertIsNone(self.candidate(tolerance=0))
        self.assertIsNone(self.candidate(tolerance=.001))
        self.assertIsNone(self.candidate(regions=[circles()[0]]))
        self.assertIsNone(self.candidate(raster_length=1,cleanup_length=1))

    def test_stepped_ring_preserves_recess_with_verified_loops_or_raster_fallback(self):
        f=fixtures.ReleasedPartTests();f.setUp()
        settings=replace(f.settings,stepdown_mm=.5,stepover_mm=.4,bottom_mm=-4,strategy='planar',
                         exclusions_mm=[fixtures.rect(-1,-1,1,1)],obstacle_top_mm=2)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);project,result=f.calculate(root,mesh=stepped_ring(),settings=settings)
            layers=[l for l in result['roughing']['layers'] if l.get('annular_pocket')]
            self.assertGreater(result['roughing']['cutting_edges'],0)
            if not layers:self.assertGreater(result['roughing']['raster_polyline_count'],0)
            self.assertTrue(all(p['closed'] for l in layers for p in l['polylines']))
            if result['cutout'] is not None:
                self.assertEqual([p['kind'] for p in result['cutout']['contours']],['internal'])
            else:self.assertEqual(list(result['operations']),['roughing'])
            self.assertEqual(export_grbl(result,project,root/'ring.nc')['status'],'passed')


if __name__=='__main__':unittest.main()
