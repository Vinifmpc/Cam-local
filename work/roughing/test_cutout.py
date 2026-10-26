import math
import unittest
import numpy as np
from cutout import generate_cutout
from cam_operations import OperationSettings,add_timing,compose,validate_operations
from cam_tools import Tool
from motion_planner import plan_ramps_and_links
from region_core import signed_area


def ring():
    outer=[[-10,-10],[10,-10],[10,10],[-10,10]]
    inner=[[-4,-4],[4,-4],[4,4],[-4,4]]
    tris=[]
    for i in range(4):
        j=(i+1)%4
        for face in [[outer[i],outer[j],inner[j]],[outer[i],inner[j],inner[i]]]:
            tris.append([[*p,0] for p in face])
    return np.asarray(tris,float)


class CutoutTests(unittest.TestCase):
    def job(self,**kw):
        return generate_cutout(ring(),diameter=2,tool_length=22,top=0,bottom=-17.1,stepdown=.635,**kw)

    def test_radius_compensation_and_internal_full_depth_first(self):
        job=self.job()
        self.assertEqual([p['kind'] for p in job['contours']],['internal','external'])
        inner,outer=[np.asarray(c['points_xy']) for c in job['contours']]
        np.testing.assert_allclose(inner.min(axis=0),[-3,-3]);np.testing.assert_allclose(inner.max(axis=0),[3,3])
        np.testing.assert_allclose(outer.min(axis=0),[-11,-11]);np.testing.assert_allclose(outer.max(axis=0),[11,11])
        self.assertEqual(len(job['depth_levels']),27)
        self.assertAlmostEqual(job['depth_levels'][0]['passo'],17.1/27)
        self.assertAlmostEqual(job['layers'][26]['z'],-17.1)
        self.assertEqual(job['layers'][26]['contour_kind'],'internal')
        self.assertEqual(job['layers'][27]['contour_kind'],'external')

    def test_small_hole_is_rejected_not_silently_dropped(self):
        with self.assertRaisesRegex(ValueError,'estreito'):
            generate_cutout(ring(),diameter=9,tool_length=22,top=0,bottom=-2,stepdown=1)

    def test_external_selection_does_not_require_a_tool_to_fit_internal_holes(self):
        job=generate_cutout(ring(),diameter=9,tool_length=22,top=0,bottom=-2,
            stepdown=1,contours='external')
        self.assertEqual(job['contours_selection'],'external')
        self.assertEqual(job['internal_contours_total'],1)
        self.assertEqual(job['skipped_internal_contours'],1)
        self.assertEqual([p['kind'] for p in job['contours']],['external'])
        self.assertTrue(all(p['contour_kind']=='external' for p in job['layers']))

    def test_explicit_internal_selection_requires_machinable_holes(self):
        with self.assertRaisesRegex(ValueError,'somente contornos externos'):
            generate_cutout(ring(),diameter=9,tool_length=22,top=0,bottom=-2,
                stepdown=1,contours='all')
        self.assertEqual(self.job(contours='all')['skipped_internal_contours'],0)
        with self.assertRaisesRegex(ValueError,'Seleção de contornos'):
            self.job(contours='invalid')

    def test_blocked_complete_contour_rejected(self):
        with self.assertRaisesRegex(ValueError,'bloqueado'):
            self.job(boundaries=[[[-5,-5],[5,-5],[5,5],[-5,5]]])
        with self.assertRaisesRegex(ValueError,'bloqueado'):
            self.job(exclusions=[[[9,-2],[12,-2],[12,2],[9,2]]])
        self.assertEqual(len(self.job(boundaries=[[[-15,-15],[15,-15],[15,15],[-15,15]]])['contours']),2)

    def test_direction_and_tool_reach(self):
        self.assertGreater(signed_area(self.job()['contours'][0]['points_xy']),0)
        self.assertLess(signed_area(self.job(direction='conventional')['contours'][0]['points_xy']),0)
        with self.assertRaisesRegex(ValueError,'comprimento'):
            generate_cutout(ring(),diameter=2,tool_length=2,top=0,bottom=-3,stepdown=1)

    def test_cutout_ramps_and_combined_continuity(self):
        job=generate_cutout(ring(),diameter=2,tool_length=5,top=0,bottom=-2,stepdown=1)
        a=plan_ramps_and_links(job,ring())
        b=plan_ramps_and_links(job,ring(),initial_position=a['final_position'])
        tool=Tool(id='t',name='t',diameter_mm=2,cutting_length_mm=5,feed_mm_min=600,plunge_mm_min=120)
        result=compose([('roughing',a),('cutout',b)],OperationSettings(),tool)
        self.assertEqual(result['validation']['status'],'passed');self.assertTrue(result['timing']['available'])
        for left,right in zip(result['moves'],result['moves'][1:]):self.assertEqual(left['end'],right['start'])
        b['initial_position']=[0,0,999]
        with self.assertRaisesRegex(ValueError,'Descontinuidade'):compose([('roughing',a),('cutout',b)],OperationSettings(),tool)

    def test_time_is_3d_length_over_feed_and_vertical_plunge(self):
        tool=Tool(id='t',name='t',diameter_mm=2,cutting_length_mm=5)
        result={'moves':[
            {'kind':'cut','start':[0,0,0],'end':[100,0,0],'operation':'roughing'},
            {'kind':'cut','start':[0,0,0],'end':[0,3,4],'operation':'cutout'},
            {'kind':'approach','start':[0,0,0],'end':[0,0,-2]},
            {'kind':'travel','start':[0,0,0],'end':[100,0,0]}]}
        o=OperationSettings(roughing_feed_mm_min=600,cutout_feed_mm_min=300,plunge_mm_min=120,rapid_mm_min=3000)
        add_timing(result,o,tool)
        self.assertEqual([m['duration_s'] for m in result['moves']],[10,1,1,2])
        self.assertEqual(result['timing']['duration_s'],14)
        add_timing(result,OperationSettings(),tool);self.assertFalse(result['timing']['available'])


if __name__=='__main__':unittest.main()
