"""Independent polygon proofs for one-sided compensated contour smoothing."""
import json
import unittest
from unittest.mock import patch
import numpy as np

from contour_flow import PROTECTED_GUARD_MM,simplify_cutout_tracks
from region_core import boolean,offset,pyclipr,signed_area


def circle(radius=10.,count=720,center=(0.,0.),hole=False):
    angles=np.linspace(0,2*np.pi,count,endpoint=False)
    path=np.column_stack((np.cos(angles),np.sin(angles)))*radius+center
    return path[::-1] if hole else path


def dense_polygon(points,subdivisions=40):
    points=np.asarray(points,float)
    return np.concatenate([a+(b-a)*np.arange(subdivisions)[:,None]/subdivisions
                           for a,b in zip(points,np.roll(points,-1,axis=0))])


class ContourFlowTests(unittest.TestCase):
    def assert_proved(self,source,result,tolerance):
        self.assertEqual(len(source),len(result))
        self.assertEqual([signed_area(path)>0 for path in source],
                         [signed_area(path)>0 for path in result])
        self.assertFalse(boolean(source,result,pyclipr.Difference),'protected region was cut')
        self.assertFalse(boolean(result,offset(source,tolerance),pyclipr.Difference),
                         'candidate exceeded the supplied offset bound')

    def test_dense_circle_reduces_vertices_and_proves_one_sided_bound(self):
        source=[circle()];before=source[0].copy()
        result,report=simplify_cutout_tracks(source,.01)
        self.assertTrue(report['applied'],report)
        self.assertLess(report['vertices_after'],report['vertices_before']//2)
        self.assertEqual(report['effective_tolerance_mm'],.01)
        np.testing.assert_array_equal(source[0],before)
        self.assert_proved(source,result,.01)
        self.assertEqual(PROTECTED_GUARD_MM,.00002)
        self.assertFalse(boolean(offset(source,PROTECTED_GUARD_MM),result,pyclipr.Difference))
        rounded=[np.round(path,5) for path in result]
        self.assertFalse(boolean(source,rounded,pyclipr.Difference),
                         'five-decimal NC rounding entered the protected region')
        json.dumps(report,allow_nan=False)

    def test_concavity_remains_protected(self):
        source=[dense_polygon([(0,0),(8,0),(8,8),(5,8),(5,2),(3,2),(3,8),(0,8)])]
        result,report=simplify_cutout_tracks(source,.01)
        self.assertTrue(report['applied'],report)
        self.assert_proved(source,result,.01)
        # A chord across the bottom convex corners would otherwise gouge.
        self.assertFalse(boolean(source,result,pyclipr.Difference))

    def test_holes_components_identity_winding_and_repeated_closure(self):
        outer=circle(10,720);hole=circle(3,360,hole=True)
        island=circle(.5,120);second=circle(2,240,center=(25,0))
        # Deliberately put holes first, and include a nested protected island.
        source=[np.vstack([hole,hole[0]]),second,outer,island]
        result,report=simplify_cutout_tracks(source,.01)
        self.assertTrue(report['applied'],report)
        self.assert_proved(source,result,.01)
        self.assertTrue(np.array_equal(result[0][0],result[0][-1]))
        self.assertTrue(all(not np.array_equal(path[0],path[-1]) for path in result[1:]))
        self.assertGreater(result[1][:,0].min(),20)
        self.assertLess(result[3][:,0].max(),1)

    def test_hole_collapse_and_component_merge_return_original(self):
        cases=[([circle(10),circle(.003,60,hole=True)],'offset_topology_changed'),
               ([circle(1,180),circle(1,180,center=(2.004,0))],'offset_topology_changed')]
        for source,reason in cases:
            with self.subTest(reason=reason):
                result,report=simplify_cutout_tracks(source,.01)
                self.assertFalse(report['applied'])
                self.assertEqual(report['reason'],reason)
                self.assertEqual(report['effective_tolerance_mm'],0)
                for before,after in zip(source,result):np.testing.assert_array_equal(before,after)

    def test_adversarial_shortcut_is_rejected_by_independent_polygon_proof(self):
        source=[circle(10)]
        # Model an overly aggressive simplifier, independent of the normal
        # edge-domain acceptance: this inscribed triangle cuts original stock.
        def shortcut(path,regions,tolerance):
            return np.vstack([path[::max(1,len(path)//3)][:3],path[0]])
        with patch('contour_flow.simplify_allowed_loop',side_effect=shortcut):
            result,report=simplify_cutout_tracks(source,.5)
        self.assertFalse(report['applied'])
        np.testing.assert_array_equal(result[0],source[0])
        self.assert_proved(source,result,.5)

    def test_translation_preserves_result_and_disabled_is_exact(self):
        source=[circle(10,527),circle(3,317,hole=True)]
        result,report=simplify_cutout_tracks(source,.01)
        self.assertTrue(report['applied'],report)
        shift=np.array([12345.6789,-98765.4321])
        translated,translated_report=simplify_cutout_tracks([path+shift for path in source],.01)
        self.assertEqual(report,translated_report)
        for before,after in zip(result,translated):
            np.testing.assert_allclose(before,after-shift,rtol=0,atol=1e-8)
        closed=np.vstack([source[0],source[0][0]])
        unchanged,disabled=simplify_cutout_tracks([closed],0)
        np.testing.assert_array_equal(unchanged[0],closed)
        self.assertFalse(disabled['applied']);self.assertEqual(disabled['reason'],'disabled')

    def test_invalid_and_tiny_tolerances(self):
        for tolerance in (-1,float('nan'),float('inf')):
            with self.subTest(tolerance=tolerance),self.assertRaises(ValueError):
                simplify_cutout_tracks([circle()],tolerance)
        result,report=simplify_cutout_tracks([circle()],1e-8)
        self.assertEqual(report['reason'],'tolerance_below_geometry_resolution')
        self.assertFalse(report['applied'])
        self.assertEqual(len(result[0]),720)


if __name__=='__main__':unittest.main()
