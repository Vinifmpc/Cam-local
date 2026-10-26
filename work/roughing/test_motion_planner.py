import copy
from collections import Counter
import math
import unittest

from motion_planner import plan_ramps_and_links,validate_motion,MotionPlanningError,NC_COORD_DECIMALS
from stl_roughing import generate_stl_roughing
from test_stl_roughing import plane,rect


def job_for_layers(layers,stepdown=1.1):
    return {'parameters':{'z_top':0,'stepdown':stepdown},
            'tool':{'diameter':1,'length':10},
            'layers':[{'polylines':[{'points':p} for p in paths]} for paths in layers]}


def undirected(a,b):return tuple(sorted([tuple(a),tuple(b)]))


class MotionPlannerTests(unittest.TestCase):
    def setUp(self):self.mesh=plane(lambda x,y:-3)

    def test_ramp_angle_and_complete_path_continuity(self):
        job=job_for_layers([[[[0,0,-1],[5,0,-1]]]])
        plan=plan_ramps_and_links(job,self.mesh,entry_angle_deg=3,initial_position=[-2,0,2.54])
        position=plan['initial_position']
        self.assertGreater(plan['move_counts'].get('ramp',0),0)
        for move in plan['moves']:
            self.assertLess(math.dist(position,move['start']),1e-8)
            a,b=move['start'],move['end']
            if move['kind']=='ramp':
                self.assertLessEqual(math.degrees(math.atan2(a[2]-b[2],math.dist(a[:2],b[:2]))),3+1e-7)
            self.assertGreaterEqual(min(a[2],b[2]),-1-1e-8)
            position=b
        self.assertEqual(position[2],2.54)
        self.assertEqual(plan['validation']['source_edges_preserved'],1)

    def test_interior_peak_uses_proven_backtrack_and_preserves_every_cut(self):
        points=[[0,0,-1],[1,0,-.2],[2,0,-1]]
        job=job_for_layers([[points]])
        plan=plan_ramps_and_links(job,self.mesh)
        cuts=[m for m in plan['moves'] if m['kind']=='cut']
        self.assertEqual(Counter(undirected(m['start'],m['end']) for m in cuts),
                         Counter(undirected(a,b) for a,b in zip(points,points[1:])))
        links=[m for m in plan['moves'] if m['kind']=='link_backtrack']
        self.assertEqual(len(links),1)
        for link in links:
            cut=plan['moves'][link['proof']['source_cut_move']]
            self.assertEqual(link['start'],cut['end'])
            self.assertEqual(link['end'],cut['start'])

    def test_deeper_layer_reenters_only_the_previously_cut_column(self):
        job=job_for_layers([[[[0,0,-1],[5,0,-1]]],[[[0,0,-2],[5,0,-2]]]])
        plan=plan_ramps_and_links(job,self.mesh)
        self.assertEqual([entry['cleared_floor'] for entry in plan['entries']],[0,-1])
        second=[m for m in plan['moves'] if m.get('layer')==1 and m['kind']=='cleared_feed']
        self.assertEqual(second[0]['end'][2],-1)
        self.assertIsNotNone(second[0]['proof']['source_cut_move'])

    def test_deeper_crossing_track_refreshes_a_shallow_cached_entry_vertex(self):
        job=job_for_layers([[[[0,0,-.5],[5,0,-.5]],
                             [[-1,0,-1],[6,0,-1]],
                             [[0,0,-2],[5,0,-2]]]])
        # The first cut caches [0,0] at -0.5. The second clears it to -1
        # inside a segment, so the vertex cache alone is no longer enough.
        for order in ('layer','region_first'):
            with self.subTest(path_order=order):
                plan=plan_ramps_and_links(job,self.mesh,path_order=order)
                self.assertEqual(plan['entries'][2]['cleared_floor'],-1)
                if order=='layer':
                    move=next(m for m in plan['moves'] if m['kind']=='cleared_feed'
                              and m.get('polyline')==2)
                    original=plan['moves'][move['proof']['source_cut_move']]
                    self.assertEqual(original['polyline'],1)
                self.assertEqual(plan['validation']['status'],'passed')

    def test_shallow_cached_vertex_cannot_credit_a_future_or_offset_deep_track(self):
        for deeper in ([[[-1,0,-1],[6,0,-1]]],[[[-1,.01,-1],[6,.01,-1]]]):
            paths=[[[0,0,-.5],[5,0,-.5]],[[0,0,-2],[5,0,-2]]]
            if deeper[0][0][1]:paths.insert(1,deeper[0])
            else:paths.append(deeper[0])
            with self.subTest(paths=paths),self.assertRaisesRegex(MotionPlanningError,'one stepdown'):
                plan_ramps_and_links(job_for_layers([paths]),self.mesh)

    def test_unproven_deep_entry_rejected(self):
        job=job_for_layers([[[[0,0,-.5],[5,0,-.5]]],[[[10,0,-1],[15,0,-1]]]],stepdown=.7)
        with self.assertRaisesRegex(MotionPlanningError,'one stepdown'):
            plan_ramps_and_links(job,self.mesh)

    def test_short_ramp_does_not_fall_back_to_a_plunge(self):
        job=job_for_layers([[[[0,0,-1],[.1,0,-1]]]])
        with self.assertRaisesRegex(MotionPlanningError,'passes'):
            plan_ramps_and_links(job,self.mesh,max_ramp_passes=2)

    def test_keepout_respected_below_clearance_and_crossed_only_above_fixture(self):
        job=generate_stl_roughing(self.mesh,diameter=1,tool_length=10,
            stepdown=1,stepover=1,sampling=.5,z_top=0,z_bottom=-3,
            boundaries=[rect(-5,-2,5,2)],exclusions=[rect(-1,-1,1,1)])
        plan=plan_ramps_and_links(job,self.mesh,obstacle_top=5)
        self.assertEqual(plan['safe_z'],7.54)
        self.assertGreater(plan['move_counts'].get('travel',0),0)
        for move in plan['moves']:
            if move['kind']=='travel':
                self.assertEqual(move['start'][2],7.54)
                self.assertEqual(move['end'][2],7.54)
            elif move['kind'] in ('cut','ramp','ramp_return'):
                a,b=move['start'],move['end'];self.assertAlmostEqual(a[1],b[1])
                left,right=sorted([a[0],b[0]])
                distance=math.hypot(max(-1-right,left-1,0),max(-1-a[1],a[1]-1,0))
                self.assertGreaterEqual(distance,.5)

    def test_low_traverse_tampering_is_detected(self):
        job=job_for_layers([[[[0,0,-1],[5,0,-1]],[[0,1,-1],[5,1,-1]]]])
        plan=plan_ramps_and_links(job,self.mesh)
        bad=copy.deepcopy(plan)
        move=next(m for m in bad['moves'] if m['kind']=='travel')
        move['end'][2]=-.5
        with self.assertRaisesRegex(MotionPlanningError,'Low traverse'):
            validate_motion(bad,job)

    def test_below_envelope_ramp_tampering_is_detected(self):
        job=job_for_layers([[[[0,0,-1],[5,0,-1]]]])
        plan=plan_ramps_and_links(job,self.mesh)
        bad=copy.deepcopy(plan)
        next(m for m in bad['moves'] if m['kind']=='ramp')['end'][2]=-2
        with self.assertRaisesRegex(MotionPlanningError,'below the source'):
            validate_motion(bad,job)

    def test_initial_state_below_clearance_rejected(self):
        job=job_for_layers([[[[0,0,-1],[5,0,-1]]]])
        with self.assertRaisesRegex(MotionPlanningError,'Initial position'):
            plan_ramps_and_links(job,self.mesh,initial_position=[0,0,0])

    def test_higher_initial_state_is_adjusted_vertically_in_air(self):
        job=job_for_layers([[[[0,0,-1],[5,0,-1]]]])
        plan=plan_ramps_and_links(job,self.mesh,initial_position=[0,0,8])
        self.assertEqual(plan['moves'][0]['kind'],'clearance_adjust')
        self.assertEqual(plan['moves'][0]['end'],[0,0,2.54])

    def test_empty_job_does_not_invent_moves(self):
        plan=plan_ramps_and_links(job_for_layers([[]]),self.mesh)
        self.assertEqual(plan['moves'],[])

    def test_subresolution_source_edge_is_rejected_without_internal_type_error(self):
        for length in (1e-11,1e-9,1e-8):
            with self.subTest(length=length),self.assertRaisesRegex(MotionPlanningError,'motion resolution'):
                plan_ramps_and_links(job_for_layers([[[[0,0,0],[length,0,0]]]]),self.mesh)

    def test_cut_cannot_hide_a_deep_drop_after_a_shallow_entry(self):
        job=job_for_layers([[[[0,0,-.1],[5,0,-2]]]],stepdown=.7)
        with self.assertRaisesRegex(MotionPlanningError,'matching cleared track'):
            plan_ramps_and_links(job,self.mesh)

    def test_declared_cutting_length_must_cover_the_stock_column(self):
        job=job_for_layers([[[[0,0,-1],[5,0,-1]]]])
        job['tool']['length']=.5
        with self.assertRaisesRegex(MotionPlanningError,'cutting length'):
            plan_ramps_and_links(job,self.mesh)

    def test_clearance_plane_cannot_be_lowered_below_a_declared_fixture(self):
        job=job_for_layers([[[[0,0,-1],[5,0,-1]]]])
        plan=plan_ramps_and_links(job,self.mesh,obstacle_top=5)
        plan['safe_z']=2.54
        with self.assertRaisesRegex(MotionPlanningError,'Passage plane'):
            validate_motion(plan,job)

    def test_real_cleanup_microedge_at_large_absolute_z_keeps_both_angle_certificates(self):
        # Exact coordinates extracted from the failing user's cleanup path.
        top=-169.04;target=-169.0540795620234
        points=[[-30.117559,-24.531530,target],[-30.117559,-24.531529,target],
                [-29.117559,-24.531529,target]]
        job=job_for_layers([[points]]);job['parameters']['z_top']=top
        plan=plan_ramps_and_links(job,plane(lambda x,y:-180),entry_angle_deg=3)
        self.assertEqual(plan['validation']['status'],'passed')
        self.assert_ramp_precision(plan,3)
        self.assertTrue(any(m['kind']=='ramp' and math.dist(m['start'][:2],m['end'][:2])<2e-6
                            for m in plan['moves']))

    def assert_ramp_precision(self,plan,limit):
        current=plan['initial_position']
        for move in plan['moves']:
            self.assertEqual(current,move['start'])
            current=move['end']
            if move['kind']!='ramp':continue
            for rounded in (False,True):
                a,b=move['start'],move['end']
                if rounded:
                    a,b=([float(f'{v:.{NC_COORD_DECIMALS}f}') for v in p] for p in (a,b))
                angle=math.degrees(math.atan2(max(0,a[2]-b[2]),math.dist(a[:2],b[:2])))
                self.assertLessEqual(angle,limit)
        self.assertEqual(current,plan['final_position'])

    def test_no_microscopic_partial_ramp_or_steep_nc_after_coordinate_rounding(self):
        tangent=math.tan(math.radians(3))
        for top in (0,-167,-1000):
            for x in (0,42,1000):
                for residual in (1e-8,2e-8,1e-7,2e-7,1e-6,1e-5,1e-4):
                    with self.subTest(top=top,x=x,residual=residual):
                        length=.7/tangent-residual
                        points=[[x,0,top-.7],[x+length,0,top-.7]]
                        job=job_for_layers([[points]],stepdown=.7);job['parameters']['z_top']=top
                        plan=plan_ramps_and_links(job,plane(lambda x,y:top-1))
                        self.assert_ramp_precision(plan,3)
                        # A residual descent uses a complete real source edge;
                        # rounding cannot turn a tiny partial into a plunge.
                        self.assertTrue(all(m['end'][:2] in [p[:2] for p in points]
                            for m in plan['moves'] if m['kind']=='ramp'))

    def test_subresolution_reposition_is_emitted_without_hidden_state_change(self):
        job=job_for_layers([[[[0,0,-1],[5,0,-1]]]])
        plan=plan_ramps_and_links(job,self.mesh,initial_position=[1e-9,0,2.54])
        self.assertEqual(plan['moves'][0]['kind'],'travel')
        self.assertEqual(plan['moves'][0]['start'],[1e-9,0,2.54])
        self.assertEqual(plan['moves'][0]['end'],[0,0,2.54])
        self.assert_ramp_precision(plan,3)

    def test_real_steep_ramp_is_still_rejected_by_independent_replay(self):
        job=job_for_layers([[[[0,0,-1],[5,0,-1]]]])
        plan=plan_ramps_and_links(job,self.mesh)
        ramp=next(m for m in plan['moves'] if m['kind']=='ramp')
        ramp['end'][2]=ramp['start'][2]-math.tan(math.radians(4))*math.dist(ramp['start'][:2],ramp['end'][:2])
        with self.assertRaisesRegex(MotionPlanningError,'Entry angle exceeded'):
            validate_motion(plan,job)

    def test_short_region_center_plunge_requires_capability_and_proved_single_step(self):
        job=job_for_layers([[[[0,0,-1],[.001,0,-1]]]])
        plan=plan_ramps_and_links(job,self.mesh,allow_center_plunge=True)
        self.assertEqual(plan['center_plunge_entries'],1)
        plunge=next(m for m in plan['moves'] if m['kind']=='plunge')
        self.assertEqual(plunge['start'],[0,0,0]);self.assertEqual(plunge['end'],[0,0,-1])
        self.assertEqual(plan['validation']['status'],'passed')
        altered=copy.deepcopy(plan);altered['parameters']['allow_center_plunge']=False
        with self.assertRaisesRegex(MotionPlanningError,'confirmed center-cutting'):
            validate_motion(altered,job)
        altered=copy.deepcopy(plan)
        next(m for m in altered['moves'] if m['kind']=='plunge')['proof']['source_edge']=99
        with self.assertRaisesRegex(MotionPlanningError,'source contact vertex'):
            validate_motion(altered,job)
        altered=copy.deepcopy(plan)
        next(m for m in altered['moves'] if m['kind']=='plunge')['end'][0]=.0001
        with self.assertRaisesRegex(MotionPlanningError,'source contact envelope'):
            validate_motion(altered,job)
        altered=copy.deepcopy(plan);deep_job=copy.deepcopy(job)
        for point in deep_job['layers'][0]['polylines'][0]['points']:point[2]=-2
        next(m for m in altered['moves'] if m['kind']=='plunge')['end'][2]=-2
        with self.assertRaisesRegex(MotionPlanningError,'one proved stepdown'):
            validate_motion(altered,deep_job)

    def test_short_smart_region_without_center_capability_has_actionable_error(self):
        job=job_for_layers([[[[0,0,-1],[.001,0,-1]]]])
        job['automatic_regions']={'polygons_mm':[rect(-1,-1,1,1)]}
        with self.assertRaisesRegex(MotionPlanningError,'Região sem espaço para rampa.*corte pelo centro'):
            plan_ramps_and_links(job,self.mesh)


if __name__=='__main__':unittest.main()
