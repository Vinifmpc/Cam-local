"""Analytical integration checks; do not claim equivalence to full MeshCAM."""
import math
import unittest
from planar_roughing import plan_planar_roughing, controlled_example


def rect(x0, y0, x1, y1):
    return [[x0,y0], [x1,y0], [x1,y1], [x0,y1]]


class PlanarRoughingTests(unittest.TestCase):
    def test_depths_and_full_tool_clearance_in_all_layers(self):
        result = controlled_example()
        self.assertEqual([layer['z'] for layer in result['layers']], [-2,-4,-6])
        self.assertEqual(result['segment_count'], 66)
        radius = 3.175 / 2
        for layer in result['layers']:
            self.assertLessEqual(layer['passo'], 2.5)
            for segment in layer['segments']:
                a, b = segment['start'], segment['end']
                self.assertEqual(a[2], layer['z'])
                self.assertEqual(b[2], layer['z'])
                self.assertEqual(a[1], b[1])
                left, right = sorted([a[0], b[0]])
                # Analytical distance between a horizontal segment and the
                # physical forbidden rectangle, independent of Clipper.
                dx = max(12-right, left-18, 0)
                dy = max(7-a[1], a[1]-13, 0)
                self.assertGreaterEqual(math.hypot(dx, dy), radius)
                for x,y,_ in (a,b):
                    self.assertGreaterEqual(x, radius)
                    self.assertLessEqual(x, 30-radius)
                    self.assertGreaterEqual(y, radius)
                    self.assertLessEqual(y, 20-radius)

    def test_fully_excluded_job_has_no_cutting_segments(self):
        result = plan_planar_roughing([rect(0,0,30,20)], [rect(-1,-1,31,21)],
            z_min_model=-6, z_min_limit=-6, z_top=0,
            stepdown=2.5, stepover=1.27, diameter=3.175)
        self.assertEqual(result['layer_count'], 3)
        self.assertEqual(result['segment_count'], 0)
        self.assertEqual(result['cutting_length_mm'], 0)
        self.assertTrue(all(not layer['segments'] for layer in result['layers']))

    def test_disconnected_regions_have_no_segment_across_gap(self):
        result = plan_planar_roughing([rect(0,0,10,10),rect(20,0,30,10)], [],
            z_min_model=-2, z_min_limit=-2, z_top=0,
            stepdown=1, stepover=1.27, diameter=3.175)
        self.assertGreater(result['segment_count'], 0)
        for layer in result['layers']:
            for segment in layer['segments']:
                xs = [segment['start'][0], segment['end'][0]]
                self.assertTrue(max(xs) < 10 or min(xs) > 20)

    def test_z_tolerance_does_not_change_xy_clearance(self):
        kwargs = dict(z_min_model=-6, z_min_limit=-6, z_top=0,
                      stepdown=2.5, stepover=1.27, diameter=3.175)
        plain = plan_planar_roughing([rect(0,0,30,20)], [], **kwargs)
        adjusted = plan_planar_roughing([rect(0,0,30,20)], [], tolerance=.1, **kwargs)
        self.assertAlmostEqual(adjusted['layers'][-1]['z'], -5.9)
        self.assertEqual(plain['center_regions'], adjusted['center_regions'])
        self.assertEqual(plain['boundary_margin'], adjusted['boundary_margin'])


if __name__ == '__main__':
    unittest.main()
