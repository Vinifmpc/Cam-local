"""Hole inspection uses the real model/tool without calculating or changing it."""
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


class DrillInspectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        source=self.root/'holes.stl';binary(source,plate(hole_radius=2,bottom=-2))
        self.app=App(self.root/'uploads',self.root/'projects')
        asset=self.app.upload(source.read_bytes(),source.name)
        self.request={'asset':asset,'placement':{'units':'mm','xy_origin':'keep','z_origin':'keep'},
            'tool':{'id':'flat4','name':'Topo 4','diameter_mm':4,'cutting_length_mm':5},
            'settings':{'stepdown_mm':1,'stepover_mm':1,'stock_top_mm':0,'bottom_mm':-2},
            'operations':{'roughing_enabled':False,'cutout_enabled':False,'drill_enabled':False,
                          'drill_center_cutting':True,'drill_compensate_facets':True}}
        self.server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(self.app))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()

    def tearDown(self):
        self.app.shutdown();self.server.shutdown();self.server.server_close();self.thread.join();self.temp.cleanup()

    def inspect(self,request):
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port)
        connection.request('POST','/api/drill-inspect',json.dumps(request),{'Content-Type':'application/json','X-Cam-Token':self.app.token})
        response=connection.getresponse();data=json.loads(response.read());connection.close()
        return response.status,data

    def test_inspection_without_enabled_operation_or_feeds_is_read_only(self):
        before=copy.deepcopy(self.request);code,report=self.inspect(self.request)
        self.assertEqual(code,200,report);self.assertEqual(report['eligible_count'],1)
        self.assertEqual(report['holes'][0]['method'],'peck')
        self.assertEqual(report['holes'][0]['fit_basis'],'nominal')
        self.assertEqual(self.request,before);self.assertFalse(self.app.saved);self.assertFalse(self.app.jobs)
        self.assertEqual(len(self.app.assets),1)

    def test_strict_fit_and_unconfirmed_center_cutting_have_explicit_reasons(self):
        self.request['operations']['drill_compensate_facets']=False
        code,report=self.inspect(self.request);self.assertEqual(code,200)
        self.assertEqual(report['eligible_count'],0);self.assertIn('mínimo',report['holes'][0]['reason'])
        self.request['operations'].update(drill_compensate_facets=True,drill_center_cutting=False)
        code,report=self.inspect(self.request);self.assertEqual(code,200)
        self.assertEqual(report['eligible_count'],0);self.assertIn('central',report['holes'][0]['reason'])

    def test_command_is_discoverable_and_queued_normally(self):
        self.assertIn('drill.inspect',command_schema()['actions'])
        box=CommandMailbox();identifier=box.submit({'action':'drill.inspect'})['command_id']
        self.assertEqual(box.next('ui',0)['command']['action'],'drill.inspect')
        box.complete(identifier,'ui',{'eligible_count':1})
        self.assertEqual(box.result(identifier)['result']['eligible_count'],1)


if __name__=='__main__':unittest.main()
