"""Real work counters must reach completion without changing CAM geometry."""
import copy
from pathlib import Path
import tempfile
import unittest

from cam_operations import OperationSettings
from cam_project import RoughingSettings,calculate_project,create_project
from cam_tools import Tool
from depth_staging import stage_paths
from motion_planner import plan_ramps_and_links,validate_motion
from stl_roughing import generate_stl_roughing
from test_cam_setup import binary
from test_layer_roughing import pocket
from test_motion_planner import job_for_layers
from test_stl_roughing import plane,rect


class CalculationProgressTests(unittest.TestCase):
    def assert_progress(self,events,final=1):
        self.assertTrue(events)
        fractions=[fraction for _,fraction in events]
        self.assertTrue(all(isinstance(phase,str) and phase for phase,_ in events))
        self.assertTrue(all(0<=fraction<=1 for fraction in fractions))
        self.assertEqual(fractions,sorted(fractions))
        self.assertEqual(fractions[-1],final)

    def test_depth_staging_reports_completed_source_paths_and_preserves_auxiliary_cuts(self):
        source=[{'polylines':[{'kind':'cleanup','points':[[0,0,-2],[4,0,-2]]},
                               {'kind':'raster','points':[[0,2,-1],[4,2,-1]]}]}]
        expected=copy.deepcopy(source);actual=copy.deepcopy(source);events=[]
        count=stage_paths(expected,diameter=1,stock_top=0,stepdown=.7)
        self.assertEqual(stage_paths(actual,diameter=1,stock_top=0,stepdown=.7,
                                    progress=lambda phase,fraction:events.append((phase,fraction))),count)
        self.assertEqual(actual,expected)
        self.assert_progress(events)
        self.assertTrue(any('1/2' in phase and fraction==.5 for phase,fraction in events))
        empty=[]
        stage_paths([],diameter=1,stock_top=0,stepdown=1,progress=lambda p,f:empty.append((p,f)))
        self.assert_progress(empty)

    def test_projected_and_layer_roughing_report_real_stages_without_geometry_changes(self):
        for mode in ('projected','layer'):
            with self.subTest(region_mode=mode):
                args=dict(diameter=1,tool_length=10,stepdown=1,stepover=1,sampling=.3,
                    z_top=0,z_bottom=-3,boundaries=[rect(-4,-4,4,4)],region_mode=mode,
                    cleanup_contours=mode=='layer',compress_collinear=True)
                expected=generate_stl_roughing(pocket(),**args);events=[]
                actual=generate_stl_roughing(pocket(),**args,progress=lambda p,f:events.append((p,f)))
                self.assertEqual(actual,expected)
                self.assert_progress(events)
                self.assertTrue(any('contato' in phase for phase,_ in events))
                if mode=='layer':
                    self.assertTrue(any('Conferindo profundidade:' in phase for phase,_ in events))

    def test_motion_and_replay_progress_preserve_moves_and_proofs(self):
        source=job_for_layers([[[[0,0,-1],[5,0,-1]],[[0,1,-1],[5,1,-1]]],
                               [[[0,0,-2],[5,0,-2]],[[0,1,-2],[5,1,-2]]]])
        mesh=plane(lambda x,y:-3);events=[]
        expected=plan_ramps_and_links(source,mesh)
        actual=plan_ramps_and_links(source,mesh,progress=lambda p,f:events.append((p,f)))
        self.assertEqual(actual,expected)
        self.assert_progress(events)
        self.assertTrue(any('Rampas e ligações: passada' in phase for phase,_ in events))
        self.assertTrue(any('Revisando movimentos:' in phase for phase,_ in events))
        replay=[]
        self.assertEqual(validate_motion(actual,source,progress=lambda p,f:replay.append((p,f))),
                         expected['validation'])
        self.assert_progress(replay)

    def test_complete_project_progress_is_monotonic_for_both_operation_orders(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);stl=root/'plane.stl';project=root/'plane.cam.json'
            binary(stl,plane(lambda x,y:-2))
            tool=Tool(id='flat-1',name='Topo 1 mm',diameter_mm=1,cutting_length_mm=5)
            settings=RoughingSettings(stepdown_mm=1,stepover_mm=1,stock_top_mm=0,bottom_mm=-2,
                boundaries_mm=[rect(-2,-1,2,1)],region_mode='layer',compress_collinear=True)
            for order in ('roughing_then_cutout','cutout_then_roughing'):
                with self.subTest(order=order):
                    options=OperationSettings(order=order,cutout_enabled=True,cutout_stepdown_mm=1)
                    create_project(stl,project,units='mm',tool=tool,settings=settings,operations=options)
                    events=[]
                    result=calculate_project(project,include_motion=True,progress=lambda p,f:events.append((p,f)))
                    self.assertEqual(result['motion']['validation']['status'],'passed')
                    self.assert_progress(events,final=.95)
                    self.assertTrue(any(.12<fraction<.44 for _,fraction in events))
                    self.assertTrue(any(.52<fraction<.87 for _,fraction in events))


if __name__=='__main__':unittest.main()
