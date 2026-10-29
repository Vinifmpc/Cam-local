import copy
from pathlib import Path
import tempfile
import unittest
from cam_operations import OperationSettings
from cam_project import RoughingSettings,create_project,calculate_project
from cam_tools import Tool
from cutout import generate_cutout
from grbl_post import export_grbl
from test_cutout import ring
from test_grbl_post import STL


class CutoutFlowIntegrationTests(unittest.TestCase):
    def test_legacy_default_is_exact_and_flow_keeps_depth_order_and_loop_types(self):
        args=dict(diameter=2,tool_length=5,top=0,bottom=-2,stepdown=.7)
        legacy=generate_cutout(ring(),**args)
        self.assertEqual(legacy,generate_cutout(ring(),**args,smoothing_mm=0))
        smooth=generate_cutout(ring(),**args,smoothing_mm=.01)
        self.assertEqual(smooth['depth_levels'],legacy['depth_levels'])
        self.assertEqual([c['kind'] for c in smooth['contours']],[c['kind'] for c in legacy['contours']])
        self.assertEqual(smooth['parameters']['smoothing_mm'],.01)
        self.assertIn('contour_flow',smooth)
        for value in (-1,.101,True,float('nan')):
            with self.subTest(value=value),self.assertRaises(ValueError):generate_cutout(ring(),**args,smoothing_mm=value)

    def test_export_rebuilds_contour_flow_from_stl_and_saved_tolerance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);stl=root/'model.stl';stl.write_text(STL,encoding='ascii')
            tool=Tool(id='t',name='t',diameter_mm=1,cutting_length_mm=5)
            settings=RoughingSettings(1,.5,0,-2)
            operations=OperationSettings(roughing_enabled=False,cutout_enabled=True,cutout_smoothing_mm=.01,
                cutout_feed_mm_min=800,plunge_mm_min=150,spindle_rpm=12000)
            project=root/'project.json';create_project(stl,project,units='mm',tool=tool,settings=settings,operations=operations)
            r=calculate_project(project,include_motion=True)
            self.assertEqual(export_grbl(r,project,root/'valid.nc')['status'],'passed')
            for field in ('contour_flow','parameters'):
                bad=copy.deepcopy(r);bad['cutout'][field]={}
                with self.assertRaisesRegex(ValueError,'Contornos'):export_grbl(bad,project,root/'bad.nc')
            self.assertFalse((root/'bad.nc').exists())


if __name__=='__main__':unittest.main()
