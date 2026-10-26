"""Explicit internal cutouts fail fast; roughing regions never constrain cutout."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cam_operations import OperationSettings
from cam_project import calculate_project,create_project,RoughingSettings
from cam_tools import Tool
from cutout import generate_cutout
from stl_roughing import generate_stl_roughing
from test_cam_setup import binary
from test_cutout import ring
from test_stl_roughing import plane,rect


class CutoutPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
        self.stl=self.folder/'model.stl';self.project=self.folder/'project.json'

    def tearDown(self):self.temp.cleanup()

    def prepare(self,mesh,diameter=1,**options):
        binary(self.stl,mesh)
        tool=Tool(id='tool',name='Topo',diameter_mm=diameter,cutting_length_mm=5)
        settings=RoughingSettings(stepdown_mm=1,stepover_mm=.8,stock_top_mm=0,bottom_mm=-2,
            boundaries_mm=[rect(-14,-14,14,14)])
        create_project(self.stl,self.project,units='mm',tool=tool,settings=settings,
            operations=OperationSettings(cutout_enabled=True,cutout_bottom_mm=-2,**options))

    def test_internal_hole_fails_before_roughing_for_both_execution_orders(self):
        for order in ('roughing_then_cutout','cutout_then_roughing'):
            with self.subTest(order=order):
                self.prepare(ring()-[0,0,2],diameter=9,order=order,cutout_contours='all')
                events=[]
                with patch('stl_roughing.generate_stl_roughing') as rough,\
                        self.assertRaisesRegex(ValueError,'diâmetro 9 mm.*contornos externos'):
                    calculate_project(self.project,include_motion=True,
                        progress=lambda phase,fraction:events.append((phase,fraction)))
                rough.assert_not_called()
                self.assertEqual(events[-1][1],.06)

    def test_legacy_roughing_region_flag_does_not_constrain_cutout(self):
        self.prepare(plane(lambda x,y:-2),cutout_use_roughing_regions=True)
        # An excluded strip intersects the external contour.
        import json
        from cam_tools import write_json
        record=json.loads(self.project.read_text(encoding='utf8'))
        record['roughing']['exclusions_mm']=[rect(4,-10,7,10)]
        write_json(self.project,record)
        result=calculate_project(self.project)
        self.assertTrue(result['cutout']['layers'])
        self.assertEqual(result['cutout']['contours_selection'],'external')
        expected=generate_cutout(plane(lambda x,y:-2),diameter=1,tool_length=5,
            top=0,bottom=-2,stepdown=.635,contours='external')
        self.assertEqual(result['cutout'],expected)

    def test_valid_cutout_is_generated_once_before_roughing_and_order_is_preserved(self):
        for order in ('roughing_then_cutout','cutout_then_roughing'):
            with self.subTest(order=order):
                self.prepare(plane(lambda x,y:-2),order=order)
                calls=[];events=[]
                def cutout(*args,**kwargs):calls.append('cutout');return generate_cutout(*args,**kwargs)
                def rough(*args,**kwargs):calls.append('roughing');return generate_stl_roughing(*args,**kwargs)
                with patch('cutout.generate_cutout',side_effect=cutout),\
                        patch('stl_roughing.generate_stl_roughing',side_effect=rough):
                    result=calculate_project(self.project,include_motion=True,
                        progress=lambda phase,fraction:events.append((phase,fraction)))
                self.assertEqual(calls,['cutout','roughing'])
                self.assertEqual(list(result['operations']),OperationSettings(order=order,cutout_enabled=True).sequence())
                self.assertEqual(result['motion']['validation']['status'],'passed')
                self.assertEqual([f for _,f in events],sorted(f for _,f in events))
                self.assertEqual(events[-1][1],.95)
                expected=generate_cutout(plane(lambda x,y:-2),diameter=1,
                    tool_length=5,top=0,bottom=-2,stepdown=.635,direction='climb',contours='external')
                if order=='roughing_then_cutout':
                    self.assertEqual(result['cutout']['rest_source_layers'],expected['layers'])
                    from cutout_rest import validate_cutout_rest
                    self.assertEqual(validate_cutout_rest(result['cutout'],result['operations']['roughing'])['status'],'passed')
                else:self.assertEqual(result['cutout'],expected)


if __name__=='__main__':unittest.main()
