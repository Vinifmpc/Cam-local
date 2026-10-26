"""Smart planning previews the real setup without creating a calculation."""
import copy
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'roughing'))
from test_cam_setup import binary
from test_drill import plate
from server import App,handler_for
from command_client import command_schema
from command_control import CommandMailbox


class SmartPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        source=self.root/'ring.stl';binary(source,plate(hole_radius=4,bottom=-2))
        self.app=App(self.root/'uploads',self.root/'projects')
        asset=self.app.upload(source.read_bytes(),source.name)
        self.request={'asset':asset,'placement':{'units':'mm','xy_origin':'keep','z_origin':'keep'},
            'tool':{'id':'flat2','name':'Topo 2','diameter_mm':2,'cutting_length_mm':5},
            'settings':{'stepdown_mm':1,'stepover_mm':.8,'stock_top_mm':0,'bottom_mm':-1,
                'exclusions_mm':[[[6,6],[7,6],[7,7],[6,7]]]},
            'operations':{'machining_mode':'smart','roughing_enabled':False,'cutout_enabled':True,
                'cutout_contours':'all','cutout_stepdown_mm':2}}
        self.server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(self.app))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()

    def tearDown(self):
        self.app.shutdown();self.server.shutdown();self.server.server_close();self.thread.join();self.temp.cleanup()

    def post(self,path,request,token=True):
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port)
        headers={'Content-Type':'application/json'}
        if token:headers['X-Cam-Token']=self.app.token
        connection.request('POST',path,json.dumps(request),headers)
        response=connection.getresponse();data=json.loads(response.read());connection.close()
        return response.status,data

    def test_preview_is_read_only_and_uses_model_bottom_not_stale_manual_depth(self):
        before=copy.deepcopy(self.request)
        code,report=self.post('/api/smart-plan',self.request)
        self.assertEqual(code,200,report);self.assertTrue(report['enabled'])
        self.assertEqual(report['sequence'],['roughing','cutout'])
        self.assertEqual(report['roughing_bottom_mm'],-2)
        self.assertEqual(report['cutout_bottom_mm'],-2)
        self.assertEqual(report['cutout_stepdown_mm'],1)
        self.assertGreater(report['skin_mm'],0)
        self.assertEqual(self.request,before);self.assertFalse(self.app.saved);self.assertFalse(self.app.jobs)

    def test_explicit_stock_and_breakthrough_are_validated_before_calculation(self):
        self.request['operations'].update(smart_stock_bottom_mm=-3,smart_breakthrough_mm=.1)
        code,report=self.post('/api/smart-plan',self.request)
        self.assertEqual(code,200,report);self.assertAlmostEqual(report['cutout_bottom_mm'],-3.1)
        self.request['operations']['smart_stock_bottom_mm']=-1
        code,error=self.post('/api/validate-config',self.request)
        self.assertEqual(code,400,error);self.assertTrue(error['error'])
        self.assertFalse(self.app.jobs);self.assertFalse(self.app.saved)

    def test_preview_keeps_authentication_and_manual_mode_needs_no_smart_geometry(self):
        code,_=self.post('/api/smart-plan',self.request,token=False);self.assertEqual(code,403)
        self.request['operations']['machining_mode']='manual'
        code,report=self.post('/api/smart-plan',self.request)
        self.assertEqual(code,200,report);self.assertEqual(report,{'enabled':False})

    def test_disabled_manual_bottom_does_not_fail_smart_reach_but_stock_top_still_checked(self):
        self.request['settings']['bottom_mm']=-100
        code,report=self.post('/api/validate-config',self.request)
        self.assertEqual(code,200,report)
        self.assertEqual(report['settings']['bottom_mm'],-100)
        self.request['settings']['stock_top_mm']=-1
        code,error=self.post('/api/smart-plan',self.request)
        self.assertEqual(code,400,error);self.assertIn('Topo',error['error'])

    def test_command_is_discoverable_and_uses_the_bounded_mailbox(self):
        schema=command_schema();self.assertIn('machining.plan',schema['actions'])
        self.assertIn('machining_mode',schema['fields']['operations'])
        box=CommandMailbox();identifier=box.submit({'action':'machining.plan'})['command_id']
        self.assertEqual(box.next('ui',0)['command']['action'],'machining.plan')
        box.complete(identifier,'ui',{'enabled':False})
        self.assertEqual(box.result(identifier)['result'],{'enabled':False})

    def test_automatic_domain_comes_from_part_and_includes_hole_candidates(self):
        self.request['settings']['boundaries_mm']=[[[-30,-30],[30,-30],[30,30],[-30,30]]]
        before=copy.deepcopy(self.request)
        code,report=self.post('/api/smart-plan',self.request)
        self.assertEqual(code,200,report)
        region=report['automatic_regions']
        self.assertEqual(region['source'],'filled_external_silhouette')
        self.assertLess(region['area_mm2'],60*60)
        self.assertEqual(region['exterior_raster_collar_mm'],0)
        from smart_planner import _point_inside
        self.assertTrue(_point_inside([0,0],region['polygons_mm']))
        self.assertFalse(_point_inside([25,25],region['polygons_mm']))
        self.assertEqual(self.request,before)

    def test_stock_sampling_command_is_read_only_and_discoverable(self):
        self.assertIn('simulation.sample',command_schema()['actions'])
        box=CommandMailbox()
        identifier=box.submit({'action':'simulation.sample','points':[[0,0]]})['command_id']
        self.assertEqual(box.next('ui',0)['command']['points'],[[0,0]])
        box.complete(identifier,'ui',{'samples':[{'z_mm':-2}]})
        self.assertEqual(box.result(identifier)['result']['samples'],[{'z_mm':-2}])


if __name__=='__main__':unittest.main()
