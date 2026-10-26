"""Saved STL -> ordered operations -> independently checked GRBL drilling."""
import copy
from itertools import permutations
import json
import math
from pathlib import Path
import re
import tempfile
import unittest

from cam_operations import OperationSettings
from cam_project import RoughingSettings,create_project,calculate_project
from cam_tools import Tool
from drill import validate_drill_motion
from grbl_post import export_grbl
from mesh_geometry import read_stl
from test_cam_setup import binary
from test_drill import plate


class DrillPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.stl=self.root/'plate.stl';self.project=self.root/'plate.cam.json'
        binary(self.stl,plate(hole_radius=2.,outer_radius=4.,bottom=-1.))
        self.tool=Tool(id='flat',name='Topo real 1 mm',diameter_mm=1.,cutting_length_mm=5.,
                       feed_mm_min=600.,plunge_mm_min=120.,spindle_rpm=8000.)
        self.settings=RoughingSettings(stepdown_mm=.5,stepover_mm=.8,stock_top_mm=0.,
            bottom_mm=-1.,sampling_mm=.2,boundaries_mm=[[[-1.4,-1.4],[1.4,-1.4],[1.4,1.4],[-1.4,1.4]]],
            compress_collinear=True,region_mode='layer')

    def tearDown(self):self.tmp.cleanup()

    def calculate(self,*,tool=None,**options):
        operations=OperationSettings(**options)
        create_project(self.stl,self.project,units='mm',tool=tool or self.tool,
                       settings=self.settings,operations=operations)
        return calculate_project(self.project,include_motion=True)

    def export(self,result,name='drill.nc'):
        destination=self.root/name
        report=export_grbl(result,self.project,destination)
        self.assertEqual(report['status'],'passed')
        self.assertEqual(report['mapped_motion_moves'],len(result['motion']['moves']))
        return destination.read_text(encoding='ascii'),report

    def test_nominal_equal_diameter_pecks_opt_in_preserves_real_tool_and_exports_linear_grbl(self):
        tool=Tool.from_dict({**self.tool.as_dict(),'name':'Topo real 4 mm','diameter_mm':4.})
        result=self.calculate(tool=tool,roughing_enabled=False,drill_enabled=True,
            drill_center_cutting=True,drill_compensate_facets=True,drill_peck_mm=.4)
        self.assertEqual(list(result['operations']),['drill'])
        self.assertIsNone(result['cutout'])
        self.assertEqual(result['drill']['tool']['diameter'],4.)
        self.assertEqual(result['motion']['tool_profile']['diameter_mm'],4.)
        hole=result['drill']['holes'][0]
        self.assertEqual(hole['basis'],'fitted_circle')
        self.assertEqual(hole['strategy'],'plunge')
        cuts=[m for m in result['operations']['drill']['moves'] if m['kind']=='cut']
        self.assertEqual(len(cuts),math.ceil(1./.4))
        self.assertTrue(all(m['start'][:2]==m['end'][:2] for m in cuts))
        self.assertTrue(all(m['feed_mm_min']==120. for m in result['motion']['moves'] if m['kind']=='cut'))
        program,report=self.export(result)
        self.assertIn('(OP DRILL)',program)
        self.assertNotIn('(OP ROUGHING)',program)
        self.assertEqual(report['order'],['drill'])
        codes=re.findall(r'^(G\d+)(?:\s|$)',program,re.MULTILINE)
        self.assertTrue(set(codes)<={'G0','G1','G17','G21','G40','G49','G54','G90','G94'})

    def test_larger_hole_requires_helix_toggle_and_enabled_helix_clears_core(self):
        with self.assertRaisesRegex(ValueError,'helicoidal'):
            self.calculate(roughing_enabled=False,drill_enabled=True,drill_center_cutting=True)
        result=self.calculate(roughing_enabled=False,drill_enabled=True,drill_center_cutting=True,
            drill_allow_helix=True,drill_peck_mm=.5,drill_feed_mm_min=350.)
        self.assertEqual(result['drill']['holes'][0]['strategy'],'helix')
        cut=[m for m in result['operations']['drill']['moves'] if m['kind']=='cut']
        self.assertTrue(any(m['proof'].get('strategy')=='overlapping_radial_step' for m in cut))
        self.assertTrue(any(m['proof'].get('strategy')=='cleared_disk_return' for m in cut))
        bottom=[m for m in cut if max(m['start'][2],m['end'][2])<=-1.+1e-8]
        # At least one full-depth cutter footprint reaches the hole centre;
        # a wall-only helix would leave its centre unmachined.
        def distance_to_segment(move):
            a=move['start'];b=move['end'];dx=b[0]-a[0];dy=b[1]-a[1]
            denominator=dx*dx+dy*dy
            t=max(0.,min(1.,-(a[0]*dx+a[1]*dy)/denominator)) if denominator else 0.
            return math.hypot(a[0]+t*dx,a[1]+t*dy)
        self.assertLessEqual(min(map(distance_to_segment,bottom)),self.tool.diameter_mm/2+1e-8)
        _,report=self.export(result)
        self.assertEqual(report['order'],['drill'])
        self.assertEqual(result['operations']['drill']['validation']['status'],'passed')

    def test_all_three_operation_orders_are_continuous_replayed_and_exported_in_order(self):
        for sequence in permutations(['roughing','drill','cutout']):
            with self.subTest(sequence=sequence):
                result=self.calculate(roughing_enabled=True,drill_enabled=True,cutout_enabled=True,
                    drill_center_cutting=True,drill_allow_helix=True,drill_peck_mm=.5,
                    cutout_stepdown_mm=.5,operation_sequence=list(sequence))
                self.assertEqual(list(result['operations']),list(sequence))
                self.assertGreater(result['roughing']['cutting_edges'],0)
                plans=list(result['operations'].values())
                for previous,next_plan in zip(plans,plans[1:]):
                    self.assertEqual(previous['final_position'],next_plan['initial_position'])
                for plan in plans:self.assertEqual(plan['validation']['status'],'passed')
                moves=result['motion']['moves']
                for previous,next_move in zip(moves,moves[1:]):
                    self.assertEqual(previous['end'],next_move['start'])
                self.assertEqual(result['motion']['validation']['status'],'passed')
                mesh=read_stl(self.stl,units='mm')
                replay=validate_drill_motion(result['operations']['drill'],result['drill'],mesh.triangles)
                self.assertEqual(replay['status'],'passed')
                program,report=self.export(result)
                self.assertEqual(report['order'],list(sequence))
                self.assertEqual(re.findall(r'^\(OP (\w+)\)$',program,re.MULTILINE),
                                 [name.upper() for name in sequence])

    def test_export_rejects_forged_hole_move_and_facet_compensation_parameter(self):
        tool=Tool.from_dict({**self.tool.as_dict(),'diameter_mm':4.})
        result=self.calculate(tool=tool,roughing_enabled=False,drill_enabled=True,
            drill_center_cutting=True,drill_compensate_facets=True)
        for mutation in ('hole','move','compensation','composed_move'):
            altered=copy.deepcopy(result)
            if mutation=='hole':altered['drill']['holes'][0]['center'][0]+=.1
            elif mutation=='move':
                next(m for m in altered['operations']['drill']['moves'] if m['kind']=='cut')['end'][0]+=.1
            elif mutation=='compensation':altered['drill']['parameters']['compensate_facets']=False
            else:next(m for m in altered['motion']['moves'] if m['kind']=='cut')['end'][0]+=.1
            destination=self.root/(mutation+'.nc')
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                export_grbl(altered,self.project,destination)
            self.assertFalse(destination.exists())

    def test_legacy_rough_and_cutout_project_keeps_identical_nc_with_drill_disabled(self):
        for order in ('roughing_then_cutout','cutout_then_roughing'):
            with self.subTest(order=order):
                result=self.calculate(cutout_enabled=True,cutout_stepdown_mm=.5,order=order)
                program,report=self.export(result,'modern.nc')
                record=json.loads(self.project.read_text(encoding='utf8'))
                record['operations']={key:value for key,value in record['operations'].items()
                    if not key.startswith('drill_') and key!='operation_sequence'}
                self.project.write_text(json.dumps(record),encoding='utf8')
                legacy=calculate_project(self.project,include_motion=True)
                legacy_program,legacy_report=self.export(legacy,'legacy.nc')
                self.assertEqual(program,legacy_program)
                self.assertEqual(report['order'],legacy_report['order'])
                self.assertNotIn('(OP DRILL)',legacy_program)


if __name__=='__main__':unittest.main()
