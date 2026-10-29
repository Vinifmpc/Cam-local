"""Analytical and planner invariants for the independent timing estimator."""
import json
import math
import random
import unittest

from motion_timing import estimate_acceleration


def moves(points, feed=600., kind='cut', operation='roughing'):
    return [dict(start=list(a), end=list(b), feed_mm_min=feed, kind=kind,
                 operation=operation) for a, b in zip(points, points[1:])]


class AccelerationTimingTests(unittest.TestCase):
    def estimate(self, path, **settings):
        return estimate_acceleration(path, **{
            'max_rates_mm_min': (600., 600., 600.),
            'accelerations_mm_s2': (10., 10., 10.), **settings})

    def assert_profiles(self, result):
        profiles = result['profiles']
        for index, p in enumerate(profiles):
            self.assertEqual(p['source_index'], index)
            self.assertGreaterEqual(p['duration_s'] + 1e-12, p['ideal_duration_s'])
            if not p['length_mm']:
                self.assertEqual(p['duration_s'], 0)
                continue
            self.assertGreaterEqual(p['peak_speed_mm_s'] + 1e-10, p['entry_speed_mm_s'])
            self.assertGreaterEqual(p['peak_speed_mm_s'] + 1e-10, p['exit_speed_mm_s'])
            self.assertLessEqual(p['peak_speed_mm_s'], p['nominal_speed_mm_s'] + 1e-10)
            self.assertAlmostEqual(sum(p[key] for key in
                ('accel_distance_mm', 'cruise_distance_mm', 'decel_distance_mm')),
                p['length_mm'], places=9)
            self.assertAlmostEqual(sum(p[key] for key in
                ('accel_time_s', 'cruise_time_s', 'decel_time_s')), p['duration_s'])
            a, ta = p['acceleration_mm_s2'], p['accel_time_s']
            td = p['decel_time_s']
            self.assertAlmostEqual(p['entry_speed_mm_s'] * ta + .5 * a * ta * ta,
                                   p['accel_distance_mm'])
            self.assertAlmostEqual(p['peak_speed_mm_s'] * td - .5 * a * td * td,
                                   p['decel_distance_mm'])
            if index:
                self.assertAlmostEqual(profiles[index - 1]['exit_speed_mm_s'],
                                       p['entry_speed_mm_s'])
        self.assertAlmostEqual(sum(p['duration_s'] for p in profiles), result['duration_s'])
        self.assertGreaterEqual(result['duration_s'] + 1e-12, result['ideal_duration_s'])
        json.dumps(result, allow_nan=False)

    def test_long_straight_trapezoid_has_analytical_time(self):
        result = self.estimate(moves([(0, 0, 0), (100, 0, 0)]))
        self.assertAlmostEqual(result['duration_s'], 11.)
        p = result['profiles'][0]
        self.assertAlmostEqual(p['accel_time_s'], 1.)
        self.assertAlmostEqual(p['accel_distance_mm'], 5.)
        self.assertAlmostEqual(p['cruise_distance_mm'], 90.)
        self.assertAlmostEqual(p['decel_time_s'], 1.)
        self.assert_profiles(result)

    def test_short_straight_triangle_has_analytical_time(self):
        result = self.estimate(moves([(0, 0, 0), (1, 0, 0)]))
        self.assertAlmostEqual(result['duration_s'], 2 * math.sqrt(1. / 10.))
        self.assertAlmostEqual(result['profiles'][0]['cruise_distance_mm'], 0)
        self.assert_profiles(result)

    def test_collinear_subdivision_is_invariant_within_lookahead(self):
        whole = self.estimate(moves([(0, 0, 0), (100, 0, 0)]))
        split = self.estimate(moves([(x, 0, 0) for x in range(0, 101, 10)]))
        self.assertAlmostEqual(whole['duration_s'], split['duration_s'])
        self.assertEqual(split['profiles'][0]['exit_speed_mm_s'], 10.)
        self.assert_profiles(split)

    def test_reversal_stops_at_junction(self):
        result = self.estimate(moves([(0, 0, 0), (100, 0, 0), (0, 0, 0)]))
        self.assertEqual(result['profiles'][0]['exit_speed_mm_s'], 0.)
        self.assertAlmostEqual(result['duration_s'], 22.)
        self.assert_profiles(result)

    def test_right_angle_projects_corner_acceleration(self):
        result = self.estimate(moves([(0, 0, 0), (100, 0, 0), (100, 100, 0)]))
        # The normal is (-1,+1)/sqrt(2), so two 10 mm/s² axes allow
        # sqrt(2)*10 mm/s² along this corner normal.
        expected = math.sqrt(10 * math.sqrt(2) * .01 *
                             math.sqrt(.5) / (1 - math.sqrt(.5)))
        self.assertAlmostEqual(result['profiles'][0]['exit_speed_mm_s'], expected)
        self.assertGreater(result['duration_s'], 21.)
        self.assertLess(result['duration_s'], 22.)
        self.assert_profiles(result)

    def test_diagonal_projects_axis_rate_and_acceleration(self):
        result = self.estimate(moves([(0, 0, 0), (100, 100, 0)], feed=6000),
                               max_rates_mm_min=(600, 120, 600),
                               accelerations_mm_s2=(10, 2, 10))
        p = result['profiles'][0]
        self.assertAlmostEqual(p['nominal_speed_mm_s'], 2 * math.sqrt(2))
        self.assertAlmostEqual(p['acceleration_mm_s2'], 2 * math.sqrt(2))
        self.assertAlmostEqual(result['ideal_duration_s'], 50.)
        self.assertAlmostEqual(result['duration_s'], 51.)
        self.assert_profiles(result)

    def test_rapid_uses_machine_rate_independently_of_display_feed(self):
        a = moves([(0, 0, 0), (100, 0, 0)], feed=1, kind='travel')
        b = moves([(0, 0, 0), (100, 0, 0)], feed=999999, kind='travel')
        c = moves([(0, 0, 0), (100, 0, 0)], feed=None, kind='travel')
        self.assertEqual(self.estimate(a), self.estimate(b))
        self.assertEqual(self.estimate(a), self.estimate(c))
        self.assertAlmostEqual(self.estimate(a)['duration_s'], 11.)

    def test_feed_below_axis_limit_is_respected(self):
        result = self.estimate(moves([(0, 0, 0), (100, 0, 0)], feed=60))
        self.assertAlmostEqual(result['duration_s'], 100.1)
        self.assert_profiles(result)

    def test_higher_acceleration_shortens_time(self):
        path = moves([(0, 0, 0), (1, 0, 0), (1, 1, 0), (2, 1, 0)])
        low = self.estimate(path)
        high = self.estimate(path, accelerations_mm_s2=(100, 100, 100))
        self.assertLess(high['duration_s'], low['duration_s'])
        self.assert_profiles(high)

    def test_finite_lookahead_cannot_see_arbitrarily_far(self):
        path = moves([(x * .01, 0, 0) for x in range(41)])
        one = self.estimate(path, planner_blocks=1)
        four = self.estimate(path, planner_blocks=4)
        full = self.estimate(path, planner_blocks=64)
        self.assertGreater(one['duration_s'], four['duration_s'])
        self.assertGreater(four['duration_s'], full['duration_s'])
        self.assertTrue(all(p['exit_speed_mm_s'] == 0 for p in one['profiles']))
        self.assert_profiles(four)

    def test_empty_and_zero_step_moves_keep_mapping(self):
        empty = self.estimate([])
        self.assertEqual(empty['duration_s'], 0)
        self.assertEqual(empty['profiles'], [])
        path = moves([(0, 0, 0), (.000004, 0, 0), (.00001, 0, 0),
                      (.00124, 0, 0), (.00125, 0, 0), (1, 0, 0)])
        result = self.estimate(path)
        self.assertEqual(len(result['profiles']), len(path))
        self.assertEqual(result['physical_blocks'], 2)
        self.assertEqual([p['duration_s'] for p in result['profiles'][:3]], [0, 0, 0])
        self.assertEqual(result['profiles'][3]['end'], [.0025, 0, 0])
        self.assert_profiles(result)

    def test_negative_half_step_rounds_away_from_zero(self):
        result = self.estimate(moves([(0, 0, 0), (-.00125, 0, 0)]))
        self.assertEqual(result['profiles'][0]['end'], [-.0025, 0, 0])

    def test_zero_step_between_blocks_preserves_speed(self):
        result = self.estimate(moves([(0, 0, 0), (1, 0, 0),
                                      (1.000001, 0, 0), (2, 0, 0)]))
        self.assertGreater(result['profiles'][1]['entry_speed_mm_s'], 0)
        self.assertEqual(result['profiles'][1]['duration_s'], 0)
        self.assert_profiles(result)

    def test_operation_totals_and_kind_totals(self):
        path = moves([(0, 0, 0), (100, 0, 0)])
        path += moves([(100, 0, 0), (200, 0, 0)], kind='travel', operation='cutout')
        result = self.estimate(path)
        self.assertAlmostEqual(sum(result['by_operation_s'].values()), result['duration_s'])
        self.assertAlmostEqual(sum(result['by_kind_s'].values()), result['duration_s'])
        self.assert_profiles(result)

    def test_axis_dictionary_settings(self):
        result = self.estimate(moves([(0, 0, 0), (100, 0, 0)]),
            max_rates_mm_min={'X': 600, 'Y': 600, 'Z': 600},
            accelerations_mm_s2={'x': 10, 'y': 10, 'z': 10},
            steps_per_mm={'X': 400, 'Y': 400, 'Z': 400})
        self.assertAlmostEqual(result['duration_s'], 11.)

    def test_zero_junction_deviation_preserves_straight_and_stops_corners(self):
        straight = self.estimate(moves([(0, 0, 0), (100, 0, 0), (200, 0, 0)]),
                                 junction_deviation_mm=0)
        corner = self.estimate(moves([(0, 0, 0), (100, 0, 0), (100, 100, 0)]),
                               junction_deviation_mm=0)
        self.assertAlmostEqual(straight['duration_s'], 21.)
        self.assertAlmostEqual(corner['duration_s'], 22.)

    def test_rate_change_brakes_in_previous_block(self):
        path = moves([(0, 0, 0), (100, 0, 0), (101, 0, 0)])
        path[1]['feed_mm_min'] = 60
        result = self.estimate(path)
        self.assertAlmostEqual(result['profiles'][0]['exit_speed_mm_s'], 1.)
        self.assert_profiles(result)

    def test_random_short_blocks_obey_speed_and_kinematic_invariants(self):
        random.seed(725)
        points = [(0, 0, 0)]
        for index in range(300):
            points.append(tuple(value + random.randint(-8, 8) * .0025
                                for value in points[-1]))
        result = self.estimate(moves(points), planner_blocks=16,
            max_rates_mm_min=(600, 180, 120), accelerations_mm_s2=(50, 20, 10))
        self.assert_profiles(result)
        for p in result['profiles']:
            for axis, (a, b) in enumerate(zip(p['start'], p['end'])):
                if not p['length_mm']:
                    continue
                component = abs(b - a) / p['length_mm']
                self.assertLessEqual(p['peak_speed_mm_s'] * component,
                                     (600, 180, 120)[axis] / 60 + 1e-9)
                self.assertLessEqual(p['acceleration_mm_s2'] * component,
                                     (50, 20, 10)[axis] + 1e-9)

    def test_invalid_parameters_are_rejected(self):
        path = moves([(0, 0, 0), (1, 0, 0)])
        for name in ('max_rates_mm_min', 'accelerations_mm_s2', 'steps_per_mm'):
            for value in ((0, 1, 1), (-1, 1, 1), (float('inf'), 1, 1),
                          (float('nan'), 1, 1), (True, 1, 1), (1, 2), {'X': 1}):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    self.estimate(path, **{name: value})
        for value in (0, -1, 1.5, True, 129):
            with self.subTest(planner_blocks=value), self.assertRaises(ValueError):
                self.estimate(path, planner_blocks=value)
        for value in (-1, float('nan'), float('inf')):
            with self.subTest(deviation=value), self.assertRaises(ValueError):
                self.estimate(path, junction_deviation_mm=value)
        with self.assertRaises(ValueError):
            self.estimate(path, max_rates_mm_min='123')

    def test_invalid_moves_and_overflows_are_rejected(self):
        for feed in (None, 0, -1, True, float('nan'), float('inf'), 1e-12):
            with self.subTest(feed=feed), self.assertRaises(ValueError):
                self.estimate(moves([(0, 0, 0), (1, 0, 0)], feed=feed))
        for end in ((float('nan'), 0, 0), (float('inf'), 0, 0), (1e308, 0, 0),
                    (1, 2), (1, 2, 3, 4)):
            with self.subTest(end=end), self.assertRaises(ValueError):
                self.estimate(moves([(0, 0, 0), end]))
        for path in ([None], [{}], None):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.estimate(path)
        discontinuous = moves([(0, 0, 0), (1, 0, 0)])
        discontinuous += moves([(2, 0, 0), (3, 0, 0)])
        with self.assertRaises(ValueError):
            self.estimate(discontinuous)
        with self.assertRaises(ValueError):
            self.estimate(moves([(-1e308, 0, 0), (1e308, 0, 0)]),
                          steps_per_mm=(1, 1, 1))


if __name__ == '__main__':
    unittest.main()
