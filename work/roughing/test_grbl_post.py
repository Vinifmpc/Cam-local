from dataclasses import asdict
import copy
import json
from pathlib import Path
import tempfile
import unittest
from cam_operations import OperationSettings
from cam_project import create_project,calculate_project,RoughingSettings
from cam_tools import Tool,write_json
from grbl_post import export_grbl,COORD_ERROR,render,verify_readback
from audit_gcode import audit


STL='''solid plane
facet normal 0 0 1
outer loop
vertex -5 -5 -2
vertex 5 -5 -2
vertex 5 5 -2
endloop
endfacet
facet normal 0 0 1
outer loop
vertex -5 -5 -2
vertex 5 5 -2
vertex -5 5 -2
endloop
endfacet
endsolid plane
'''


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.stl=self.root/'model.stl';self.stl.write_text(STL,encoding='ascii')
        self.tool=Tool(id='t',name='t',diameter_mm=1,cutting_length_mm=5)
        self.s=RoughingSettings(1,.8,0,-2,boundaries_mm=[[[-2,-1],[2,-1],[2,1],[-2,1]]])
    def tearDown(self):self.temp.cleanup()
    def calculate(self,**changes):
        values={'cutout_enabled':True,'cutout_bottom_mm':-2.1,'roughing_feed_mm_min':700,
                'cutout_feed_mm_min':900,'plunge_mm_min':150,'spindle_rpm':8000,**changes}
        self.options=OperationSettings(**values);self.project=self.root/'project.json'
        create_project(self.stl,self.project,units='mm',tool=self.tool,settings=self.s,operations=self.options)
        return calculate_project(self.project,include_motion=True)

    def test_both_orders_are_continuous_and_read_back_with_feeds_and_rpm(self):
        for order,sequence in [('roughing_then_cutout',['roughing','cutout']),('cutout_then_roughing',['cutout','roughing'])]:
            result=self.calculate(order=order)
            self.assertEqual(list(result['operations']),sequence)
            for a,b in zip(result['motion']['moves'],result['motion']['moves'][1:]):self.assertEqual(a['end'],b['start'])
            path=self.root/(order+'.nc');report=export_grbl(result,self.project,path)
            self.assertEqual(report['order'],sequence)
            self.assertLessEqual(report['maximum_coordinate_error_mm'],COORD_ERROR)
            summary,moves=audit(path)
            self.assertFalse(summary['assumptions']);self.assertEqual(summary['spindle_commands'],[8000])
            self.assertEqual(summary['feedrates_mm_min'],[150,700,900])
            text=path.read_text(encoding='ascii')
            self.assertLess(text.index('(OP '+sequence[0].upper()+')'),text.index('(OP '+sequence[1].upper()+')'))
            self.assertNotIn('G28',text);self.assertTrue(text.endswith('M5\nM2\n'))

    def test_single_operations_and_legacy_defaults(self):
        self.assertEqual(OperationSettings().sequence(),['roughing'])
        for name in ['roughing','cutout']:
            result=self.calculate(roughing_enabled=name=='roughing',cutout_enabled=name=='cutout')
            self.assertEqual(list(result['operations']),[name])
            export_grbl(result,self.project,self.root/(name+'.nc'))
        with self.assertRaises(ValueError):OperationSettings(order='injected')

    def test_missing_rpm_or_feed_is_rejected_and_no_file_is_published(self):
        for changes in [{'spindle_rpm':None},{'roughing_feed_mm_min':None},
                        {'spindle_rpm':1e-9},{'roughing_feed_mm_min':1e-9}]:
            result=self.calculate(**changes);destination=self.root/'rejected.nc'
            with self.assertRaises(ValueError):export_grbl(result,self.project,destination)
            self.assertFalse(destination.exists())

    def test_changed_project_source_or_motion_is_rejected(self):
        result=self.calculate();record=json.loads(self.project.read_text(encoding='utf8'));record['notes']='changed'
        write_json(self.project,record)
        with self.assertRaisesRegex(ValueError,'Projeto mudou'):export_grbl(result,self.project,self.root/'bad.nc')
        result=json.loads(json.dumps(self.calculate()));result['motion']['moves'][0]['end'][0]+=1
        with self.assertRaisesRegex(ValueError,'mudou'):export_grbl(result,self.project,self.root/'bad.nc')
        result=self.calculate();result['operations']['roughing']['path_order']='layer'
        with self.assertRaisesRegex(ValueError,'Prioridade'):export_grbl(result,self.project,self.root/'bad.nc')
        result=self.calculate();self.stl.write_text(STL.replace('vertex 5 5 -2','vertex 6 5 -2'),encoding='ascii')
        with self.assertRaisesRegex(ValueError,'STL mudou'):export_grbl(result,self.project,self.root/'bad.nc')

    def test_disabled_roughing_does_not_block_cutout_with_irrelevant_reach_or_stepover(self):
        self.s=RoughingSettings(1,8,0,-20)
        result=self.calculate(roughing_enabled=False)
        export_grbl(result,self.project,self.root/'cutout.nc')

    def test_export_report_cannot_overwrite_project(self):
        result=self.calculate()
        # This project name is the sidecar chosen for candidate.nc.
        renamed=self.root/'candidate.validacao.json'
        self.project.rename(renamed);self.project=renamed
        original=renamed.read_bytes()
        destination=self.root/'candidate.nc'
        with self.assertRaisesRegex(ValueError,'relatório.*projeto'):
            export_grbl(result,self.project,destination)
        self.assertEqual(renamed.read_bytes(),original)
        self.assertFalse(destination.exists())

    def test_readback_rejects_ramp_made_steeper_by_nc_rounding(self):
        # Float geometry is 3 degrees. Five-decimal Z quantization turns
        # this tiny final ramp into 5.71 degrees despite a valid XYZ error.
        import math
        a=[42.,0.,-167.];b=[42.0001,0.,-167.-math.tan(math.radians(3))*.0001]
        move={'kind':'ramp','start':a,'end':b,'operation':'roughing','feed_mm_min':700}
        motion={'initial_position':a,'final_position':b,'safe_z':-168,
            'moves':[move],'entry_angle_limit_deg':3}
        program,mapping=render(motion,8000,'roughing_then_cutout')
        path=self.root/'quantized.nc';path.write_text(program,encoding='ascii')
        with self.assertRaisesRegex(ValueError,'Ângulo.*arredondar'):
            verify_readback(path,motion,mapping,8000)

    def test_readback_reports_real_rounded_ramp_angle(self):
        a=[42.,0.,-167.];b=[43.,0.,-167.01]
        motion={'initial_position':a,'final_position':b,'safe_z':-168,
            'moves':[{'kind':'ramp','start':a,'end':b,'operation':'roughing','feed_mm_min':700}],
            'entry_angle_limit_deg':3}
        program,mapping=render(motion,8000,'roughing_then_cutout')
        path=self.root/'safe-ramp.nc';path.write_text(program,encoding='ascii')
        report=verify_readback(path,motion,mapping,8000)
        self.assertEqual(report['entry_angle_limit_deg'],3)
        self.assertGreater(report['maximum_entry_descent_angle_deg'],.57)
        self.assertLess(report['maximum_entry_descent_angle_deg'],.58)


if __name__=='__main__':unittest.main()
