"""Operation scope and verified rest material survive composition and export."""
import copy
from pathlib import Path
import tempfile
import unittest

from cam_operations import OperationSettings
from cam_project import RoughingSettings,create_project,calculate_project
from cam_tools import Tool
from grbl_post import export_grbl
from test_cam_setup import binary
from test_stl_roughing import plane,rect


class CutoutPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.stl=self.root/'model.stl';self.project=self.root/'project.json'
        binary(self.stl,plane(lambda x,y:-2))
        self.tool=Tool(id='flat',name='Topo 1',diameter_mm=1,cutting_length_mm=5,
            feed_mm_min=600,plunge_mm_min=120,spindle_rpm=8000)
        self.settings=RoughingSettings(stepdown_mm=1,stepover_mm=.8,stock_top_mm=0,
            bottom_mm=-2,boundaries_mm=[rect(-3,-3,3,3)],exclusions_mm=[rect(-1,-1,1,1)],
            region_mode='layer',compress_collinear=True)

    def tearDown(self):self.temp.cleanup()

    def calculate(self,**options):
        settings=OperationSettings(cutout_enabled=True,cutout_bottom_mm=-2,
            cutout_stepdown_mm=1,**options)
        create_project(self.stl,self.project,units='mm',tool=self.tool,
            settings=self.settings,operations=settings)
        return calculate_project(self.project,include_motion=True)

    def test_keepin_keepout_only_restrict_rough_and_cutout_exports_outside_them(self):
        result=self.calculate(cutout_use_roughing_regions=True)
        rough=[m for m in result['operations']['roughing']['moves'] if m['kind']=='cut']
        self.assertTrue(rough)
        self.assertTrue(all(abs(p[0])<3 and abs(p[1])<3 for m in rough for p in (m['start'],m['end'])))
        outer=[p for c in result['cutout']['contours'] for p in c['points_xy']]
        self.assertGreater(max(abs(x) for p in outer for x in p),3)
        self.assertTrue(result['cutout']['rest_material']['applied'])
        self.assertEqual(result['cutout']['rest_material']['skipped_depth_passes'],0)
        self.assertEqual(export_grbl(result,self.project,self.root/'out.nc')['status'],'passed')

    def test_inverse_order_never_uses_future_rough_and_reuse_can_be_disabled(self):
        for options in ({'order':'cutout_then_roughing'},{'cutout_use_prior_roughing':False}):
            with self.subTest(options=options):
                result=self.calculate(**options)
                self.assertNotIn('rest_material',result['cutout'])
                self.assertNotIn('prior_roughing',result['operations']['cutout'])
                self.assertEqual(export_grbl(result,self.project,self.root/'out.nc')['status'],'passed')

    def test_export_rejects_forged_missing_cutout_passes_and_wrong_contours(self):
        result=self.calculate()
        altered=copy.deepcopy(result);altered['cutout']['layers'].pop()
        with self.assertRaisesRegex(ValueError,'Cutout restante'):
            export_grbl(altered,self.project,self.root/'bad.nc')
        altered=copy.deepcopy(result);altered['cutout']['contours_selection']='all'
        with self.assertRaisesRegex(ValueError,'Contornos do Cutout'):
            export_grbl(altered,self.project,self.root/'bad.nc')
        self.assertFalse((self.root/'bad.nc').exists())


if __name__=='__main__':unittest.main()
