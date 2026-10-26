"""Prior roughing clearance is credited only from completed same-tool cuts."""
import copy
import unittest

from cam_operations import OperationSettings,compose
from cam_tools import Tool
from motion_planner import (MotionPlanningError,build_prior_cut_state,
                            plan_ramps_and_links,validate_motion)
from test_motion_planner import job_for_layers
from test_stl_roughing import plane


class PriorMotionTests(unittest.TestCase):
    def setUp(self):
        self.mesh=plane(lambda x,y:-4)
        self.rough=job_for_layers([[[[0,0,-1],[10,0,-1]]],[[[0,0,-2],[10,0,-2]]]])
        self.prior=plan_ramps_and_links(self.rough,self.mesh)

    def cutout(self,points=None,**changes):
        job=job_for_layers([[points or [[0,0,-2.5],[5,0,-2.5]]]])
        plan=plan_ramps_and_links(job,self.mesh,initial_position=self.prior['final_position'],
                                 prior_motion=changes.pop('prior_motion',self.prior),**changes)
        return job,plan

    def test_entry_reuses_actual_prior_floor_and_replay_requires_that_prior(self):
        job,plan=self.cutout()
        self.assertEqual(plan['entries'][0]['cleared_floor'],-2)
        self.assertEqual(plan['prior_reused_entries'],1)
        self.assertEqual(plan['prior_roughing']['cut_moves'],2)
        self.assertEqual(validate_motion(plan,job,prior_motion=self.prior)['status'],'passed')
        with self.assertRaisesRegex(MotionPlanningError,'desbaste anterior'):
            validate_motion(plan,job)
        with self.assertRaisesRegex(MotionPlanningError,'one stepdown'):
            plan_ramps_and_links(job,self.mesh,initial_position=self.prior['final_position'])

    def test_already_cleared_depth_enters_without_a_new_ramp(self):
        _,plan=self.cutout([[2,0,-1.5],[8,0,-1.5]])
        self.assertEqual(plan['entries'][0]['ramp_passes'],0)
        self.assertNotIn('ramp',plan['move_counts'])

    def test_later_cutout_layers_keep_deep_prior_clearance_after_creating_new_vertices(self):
        job=job_for_layers([[[[2,0,-1],[8,0,-1]]],[[[2,0,-1.5],[8,0,-1.5]]]])
        plan=plan_ramps_and_links(job,self.mesh,initial_position=self.prior['final_position'],
                                 prior_motion=self.prior)
        self.assertEqual([e['ramp_passes'] for e in plan['entries']],[0,0])
        self.assertEqual([e['cleared_floor'] for e in plan['entries']],[-2,-2])

    def test_layer_order_cutout_can_link_through_proved_prior_tracks(self):
        job=job_for_layers([[[[0,0,-1.5],[2,0,-1.5]],[[3,0,-1.5],[5,0,-1.5]]]])
        plan=plan_ramps_and_links(job,self.mesh,path_order='layer',
            initial_position=self.prior['final_position'],prior_motion=self.prior)
        self.assertEqual(plan['stay_down_entries'],1)
        self.assertEqual(plan['move_counts']['link_cleared'],1)
        self.assertEqual(validate_motion(plan,job,prior_motion=self.prior)['status'],'passed')

    def test_same_xy_tracks_prove_sweeps_but_shallow_and_offset_tracks_do_not(self):
        state=build_prior_cut_state(self.prior,{'diameter':1,'length':10},0)
        self.assertTrue(state.covers_edge([0,0,-2],[10,0,-2]))
        self.assertTrue(state.covers_edge([3,0,-1.5],[5,0,-1.5]))
        self.assertFalse(state.covers_edge([0,0,-2.1],[10,0,-2.1]))
        self.assertFalse(state.covers_edge([0,.02,-2],[10,.02,-2]))

    def test_travel_moves_never_become_removed_stock(self):
        state=build_prior_cut_state(self.prior,{'diameter':1,'length':10},0)
        self.assertFalse(state.covers_edge([0,4,-1],[10,4,-1]))
        self.assertEqual(state.cut_count,2)
        empty=copy.deepcopy(self.prior)
        for move in empty['moves']:
            if move['kind']=='cut':move['kind']='travel'
        self.assertEqual(build_prior_cut_state(empty,{'diameter':1,'length':10},0).cut_count,0)

    def test_changed_tool_unvalidated_prior_and_wrong_initial_state_are_rejected(self):
        for key in ('diameter','length'):
            tool={'diameter':1,'length':10};tool[key]+=.1
            with self.subTest(tool=tool),self.assertRaisesRegex(MotionPlanningError,'mesma fresa'):
                build_prior_cut_state(self.prior,tool,0)
        bad=copy.deepcopy(self.prior);bad['validation']['status']='failed'
        with self.assertRaisesRegex(MotionPlanningError,'validado'):self.cutout(prior_motion=bad)
        job=job_for_layers([[[[0,0,-1],[5,0,-1]]]])
        with self.assertRaisesRegex(MotionPlanningError,'posição final'):
            plan_ramps_and_links(job,self.mesh,initial_position=[99,0,2.54],prior_motion=self.prior)

    def test_changed_prior_fingerprint_is_rejected_by_replay(self):
        job,plan=self.cutout();plan['prior_roughing']['sha256']='changed'
        with self.assertRaisesRegex(MotionPlanningError,'mudou'):
            validate_motion(plan,job,prior_motion=self.prior)

    def test_composition_maps_prior_cut_references_to_real_global_rough_moves(self):
        _,plan=self.cutout()
        tool=Tool(id='one',name='Topo1',diameter_mm=1,cutting_length_mm=10)
        combined=compose([('roughing',self.prior),('cutout',plan)],OperationSettings(cutout_enabled=True),tool)
        references=[m for m in combined['moves'] if m['operation']=='cutout' and
                    isinstance(m['proof'].get('source_cut_move'),int)]
        self.assertTrue(references)
        for move in references:
            old=combined['moves'][move['proof']['source_cut_move']]
            self.assertEqual(old['operation'],'roughing');self.assertEqual(old['kind'],'cut')
        with self.assertRaisesRegex(ValueError,'ordem'):
            compose([('cutout',plan),('roughing',self.prior)],OperationSettings(cutout_enabled=True),tool)

    def test_new_options_are_strict_and_old_region_flag_has_no_effect(self):
        self.assertEqual(OperationSettings().cutout_contours,'external')
        self.assertTrue(OperationSettings().cutout_use_prior_roughing)
        self.assertFalse(OperationSettings.from_dict({'cutout_use_roughing_regions':True}).cutout_use_roughing_regions)
        for change in ({'cutout_contours':'internal'},{'cutout_use_prior_roughing':1}):
            with self.subTest(change=change),self.assertRaises(ValueError):OperationSettings(**change)


if __name__=='__main__':unittest.main()
