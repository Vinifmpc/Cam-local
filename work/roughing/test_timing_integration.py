import copy
from dataclasses import asdict,replace
import unittest
from cam_operations import OperationSettings,add_timing
from cam_tools import Tool
from grbl_post import render,verify_readback
from pathlib import Path
import tempfile


class TimingIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tool=Tool(id='t',name='t',diameter_mm=3.175,cutting_length_mm=22)
        self.options=OperationSettings(roughing_feed_mm_min=600,plunge_mm_min=150,spindle_rpm=12000,
            machine_max_rate_mm_min=[1500,1500,1500],machine_acceleration_mm_s2=[10,10,10])
        self.motion={'moves':[
            {'kind':'cut','start':[0,0,2],'end':[100,0,2],'operation':'roughing'},
            {'kind':'cut','start':[100,0,2],'end':[100,100,2],'operation':'roughing'},
            {'kind':'retract','start':[100,100,2],'end':[100,100,5],'operation':'roughing'}],
            'initial_position':[0,0,2],'final_position':[100,100,5],'safe_z':5}

    def test_profile_changes_time_and_playback_without_changing_nc_or_feeds(self):
        a=add_timing(copy.deepcopy(self.motion),self.options,self.tool)
        b=add_timing(copy.deepcopy(self.motion),replace(self.options,machine_acceleration_mm_s2=[20,20,20]),self.tool)
        c=add_timing(copy.deepcopy(self.motion),replace(self.options,timing_model='constant'),self.tool)
        self.assertGreater(a['timing']['duration_s'],b['timing']['duration_s'])
        self.assertGreater(b['timing']['duration_s'],c['timing']['duration_s'])
        text_a,mapping=render(a,12000,'roughing_then_cutout')
        self.assertEqual(text_a,render(b,12000,'roughing_then_cutout')[0])
        self.assertEqual(text_a,render(c,12000,'roughing_then_cutout')[0])
        self.assertEqual([m['feed_mm_min'] for m in a['moves']],[600,600,3000])
        self.assertEqual(a['timing']['by_operation_s']['roughing'],sum(m['duration_s'] for m in a['moves']))
        self.assertTrue(all('timing_profile' in m for m in a['moves']))
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'program.nc';path.write_text(text_a,encoding='ascii')
            self.assertEqual(verify_readback(path,a,mapping,12000)['status'],'passed')

    def test_rapid_legacy_estimate_is_ignored_in_acceleration_mode(self):
        a=add_timing(copy.deepcopy(self.motion),self.options,self.tool)
        b=add_timing(copy.deepcopy(self.motion),replace(self.options,rapid_mm_min=99999),self.tool)
        self.assertEqual(a['timing']['duration_s'],b['timing']['duration_s'])
        self.assertEqual(a['moves'][-1]['timing_profile']['nominal_speed_mm_s'],25)

    def test_legacy_mode_and_old_project_defaults_are_explicit(self):
        old=OperationSettings.from_dict({'roughing_feed_mm_min':600})
        self.assertEqual(old.timing_model,'acceleration');self.assertEqual(old.machine_planner_blocks,15)
        a=add_timing(copy.deepcopy(self.motion),self.options,self.tool)
        b=add_timing(a,replace(self.options,timing_model='constant'),self.tool)
        self.assertFalse(any('timing_profile' in m for m in b['moves']))
        self.assertAlmostEqual(b['timing']['duration_s'],20.06)

    def test_settings_reject_malformed_profile_and_do_not_alias_input(self):
        bad=[{'machine_acceleration_mm_s2':[10,0,10]}, {'machine_max_rate_mm_min':[1500,1500]},
             {'machine_steps_per_mm':[True,400,400]}, {'machine_planner_blocks':16.5},
             {'machine_junction_deviation_mm':-1}, {'timing_model':'untrusted'},
             {'machine_acceleration_mm_s2':None}]
        for patch in bad:
            with self.subTest(patch=patch),self.assertRaises(ValueError):replace(self.options,**patch)
        values=[1,2,3];options=replace(self.options,machine_acceleration_mm_s2=values);values[0]=999
        self.assertEqual(options.machine_acceleration_mm_s2,[1,2,3])
        self.assertEqual(OperationSettings.from_dict(asdict(options)),options)

    def test_missing_or_unrepresentable_feed_keeps_unavailable_timing(self):
        for rate in (None,1e-9):
            result=add_timing(copy.deepcopy(self.motion),replace(self.options,roughing_feed_mm_min=rate),self.tool)
            self.assertFalse(result['timing']['available'])
            self.assertIsNone(result['timing']['duration_s'])


if __name__=='__main__':unittest.main()
