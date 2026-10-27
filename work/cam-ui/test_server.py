import io
import http.client
import json
from pathlib import Path
import struct
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import zipfile
from http.server import ThreadingHTTPServer
from server import App,handler_for


def plane_stl():
    triangles=[[-5,-5,-2,5,-5,-2,5,5,-2],[-5,-5,-2,5,5,-2,-5,5,-2]]
    return bytes(80)+struct.pack('<I',2)+b''.join(struct.pack('<12fH',0,0,1,*p,0) for p in triangles)


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.app=App(self.root/'data',self.root/'outputs/projects')
        self.asset=self.app.upload(plane_stl(),'../../plane.stl')
        self.request={'asset':self.asset,'placement':{'units':'mm','xy_origin':'keep','z_origin':'keep'},
            'tool':{'id':'one','name':'Topo 1','diameter_mm':1,'cutting_length_mm':5},
            'settings':{'stepdown_mm':1,'stepover_mm':.8,'stock_top_mm':0,'bottom_mm':-2,
                'boundaries_mm':[[[-2,-1],[2,-1],[2,1],[-2,1]]]},
            'ui':{'windows':[[-2,-1,2,1]],'approximate_regions':True}}
    def tearDown(self):
        self.app.pool.shutdown(wait=True);self.temp.cleanup()

    def test_upload_filename_cannot_escape_and_unit_inspection(self):
        item=self.app.asset(self.asset)
        self.assertEqual(item['name'],'plane.stl');self.assertEqual(item['path'].parent,self.app.data)
        scene=self.app.inspect(self.asset,{'units':'inch'})
        self.assertAlmostEqual(scene['mesh']['bounds_mm']['size'][0],254)
        with self.assertRaises(ValueError):self.app.inspect('../outside',{'units':'mm'})

    def test_saved_bundle_roundtrip_preserves_tool_regions_units_and_approximate_note(self):
        self.request['ui']['stock']={'x0':-6,'y0':-7,'x1':8,'y1':9,'step':.25}
        identifier,path=self.app.prepare(self.request)
        payload=self.app.bundle(identifier)
        scene=self.app.restore(payload)
        self.assertEqual(scene['tool']['diameter_mm'],1)
        self.assertEqual(scene['settings']['boundaries_mm'],self.request['settings']['boundaries_mm'])
        self.assertEqual(scene['windows'],self.request['ui']['windows'])
        self.assertTrue(scene['approximate_regions']);self.assertIsNone(scene['motion'])
        self.assertEqual(scene['stock'],self.request['ui']['stock'])

    def test_simulation_stock_metadata_rejects_inverted_or_invalid_grid(self):
        stock={'x0':0,'y0':0,'x1':10,'y1':20,'step':.5}
        for key,value in [('x1',-1),('step',0),('y1',float('nan')),('x0',True)]:
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValueError,'bruto'):
                    self.app.ui_metadata({'stock':{**stock,key:value}})

    def test_zip_external_source_is_replaced_and_hash_is_still_checked(self):
        identifier,path=self.app.prepare(self.request)
        record=json.loads(path.read_text());record['source']['path']='C:/secret.stl'
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w') as archive:
            archive.writestr('project.json',json.dumps(record));archive.writestr('model.stl',plane_stl())
            archive.writestr('../outside.txt','must not be extracted')
        self.app.restore(buf.getvalue())
        self.assertFalse((self.app.outputs.parent/'outside.txt').exists())
        record['source']['sha256']='0'*64;buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w') as archive:
            archive.writestr('project.json',json.dumps(record));archive.writestr('model.stl',plane_stl())
        with self.assertRaisesRegex(ValueError,'STL mudou'):self.app.restore(buf.getvalue())

    def test_async_calculation_reaches_real_engine_and_saves_validated_result(self):
        task=self.app.calculate(self.request);deadline=time.monotonic()+10
        while self.app.jobs[task['job']]['status']=='running' and time.monotonic()<deadline:time.sleep(.01)
        state=self.app.jobs[task['job']]
        self.assertEqual(state['status'],'complete',state)
        self.assertGreater(state['motion']['cutting_edges'],0)
        self.assertEqual(state['motion']['validation']['status'],'passed')
        self.assertTrue((self.app.saved[task['job']].parent/'result.json').exists())

    def test_http_loopback_origin_and_token_guards(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(self.app))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def request(method,path,body=None,headers=None):
            con=http.client.HTTPConnection('127.0.0.1',server.server_port)
            con.request(method,path,body=body,headers=headers or {});response=con.getresponse()
            result=(response.status,response.read());con.close();return result
        try:
            self.assertEqual(request('GET','/')[0],200)
            self.assertEqual(request('GET','/vendor/manifold.js')[0],200)
            status,wasm=request('GET','/vendor/manifold.wasm')
            self.assertEqual(status,200);self.assertEqual(wasm[:4],b'\x00asm')
            self.assertEqual(request('GET','/api/bootstrap',headers={'Origin':'https://example.com'})[0],403)
            self.assertEqual(request('POST','/api/save',json.dumps(self.request))[0],403)
            self.assertEqual(request('POST','/api/presets',json.dumps({'action':'delete','id':'missing'}))[0],403)
            status,body=request('POST','/api/save',json.dumps(self.request),{'X-Cam-Token':self.app.token})
            self.assertEqual(status,200,body)
            self.assertEqual(request('GET','/../../server.py')[0],403)
        finally:server.shutdown();server.server_close();thread.join()

    def test_invalid_or_unsupported_tool_never_starts_a_job(self):
        self.request['tool']['kind']='ball_end_mill'
        with self.assertRaises(ValueError):self.app.calculate(self.request)
        self.assertIsNone(self.app.active)

    def test_preparation_runs_in_worker_and_job_reports_progress_without_blocking(self):
        entered=threading.Event();release=threading.Event();prepare=self.app.prepare
        def slow_prepare(request,identifier=None):
            entered.set();release.wait(5)
            return prepare(request,identifier)
        with patch.object(self.app,'prepare',side_effect=slow_prepare):
            started=time.monotonic();task=self.app.calculate(self.request)
            try:
                self.assertLess(time.monotonic()-started,.5)
                self.assertTrue(entered.wait(2))
                state=self.app.job_state(task['job'])
                self.assertEqual(state['status'],'running')
                self.assertIn('STL',state['phase']);self.assertGreaterEqual(state['elapsed_s'],0)
                with self.assertRaisesRegex(RuntimeError,'andamento'):self.app.calculate(self.request)
            finally:release.set()
        self.app.pool.shutdown(wait=True)
        state=self.app.job_state(task['job'])
        self.assertEqual(state['status'],'complete',state)
        self.assertEqual(state['progress'],1);self.assertGreater(state['elapsed_s'],0)

    def test_failed_worker_releases_active_job_and_next_calculation_can_finish(self):
        self.request['asset']=self.app.upload(b'invalid STL','invalid.stl')
        with self.assertLogs(level='ERROR'):
            task=self.app.calculate(self.request)
            deadline=time.monotonic()+5
            while self.app.job_state(task['job'])['status']=='running' and time.monotonic()<deadline:time.sleep(.01)
            state=self.app.job_state(task['job'])
            self.assertEqual(state['status'],'failed');self.assertIn('STL',state['error'])
            self.assertIsNone(self.app.active)
        self.request['asset']=self.asset
        next_task=self.app.calculate(self.request);deadline=time.monotonic()+10
        while self.app.job_state(next_task['job'])['status']=='running' and time.monotonic()<deadline:time.sleep(.01)
        self.assertEqual(self.app.job_state(next_task['job'])['status'],'complete')

    def test_filled_operation_feeds_satisfy_inspection_with_blank_catalogue_feeds(self):
        self.request['operations']={'roughing_feed_mm_min':700,'plunge_mm_min':150,'spindle_rpm':8000}
        _,path=self.app.prepare(self.request)
        inspection=json.loads(path.read_text())['inspection']
        self.assertFalse(any('Avanços/rotação' in warning for warning in inspection['warnings']))

    def test_operation_settings_survive_zip_and_cutout_only_goes_below_model(self):
        self.request['operations']={'roughing_enabled':False,'cutout_enabled':True,
            'cutout_bottom_mm':-2.1,'cutout_stepdown_mm':.8,'cutout_feed_mm_min':900,
            'plunge_mm_min':150,'rapid_mm_min':2400,'cutout_use_roughing_regions':False}
        identifier,path=self.app.prepare(self.request)
        scene=self.app.restore(self.app.bundle(identifier))
        self.assertEqual(scene['operations']['cutout_bottom_mm'],-2.1)
        self.assertFalse(scene['operations']['roughing_enabled'])
        from cam_project import calculate_project
        result=calculate_project(path,include_motion=True)
        self.assertEqual(result['roughing']['cutting_edges'],0)
        self.assertGreater(result['cutout']['cutting_edges'],0)
        self.assertTrue(all(m['operation']=='cutout' for m in result['motion']['moves']))
        self.assertTrue(result['motion']['timing']['available'])
        self.assertAlmostEqual(min(m['end'][2] for m in result['motion']['moves']),-2.1)

    def test_combined_job_times_both_operations_with_rough_only_regions(self):
        self.request['operations']={'cutout_enabled':True,'cutout_bottom_mm':-2.1,
            'roughing_feed_mm_min':700,'cutout_feed_mm_min':900,'plunge_mm_min':150}
        _,path=self.app.prepare(self.request)
        from cam_project import calculate_project
        result=calculate_project(path,include_motion=True)
        view=self.app.motion_view(result)
        self.assertEqual(set(m[8] for m in view['moves']),{'roughing','cutout'})
        self.assertAlmostEqual(sum(view['durations_s']),view['timing']['duration_s'])
        for a,b in zip(view['moves'],view['moves'][1:]):self.assertEqual(a[4:7],b[1:4])
        self.request['operations']['cutout_use_roughing_regions']=True
        _,path=self.app.prepare(self.request)
        scoped=calculate_project(path,include_motion=True)
        self.assertEqual(scoped['cutout'],result['cutout'])
        self.assertEqual(scoped['motion']['moves'],result['motion']['moves'])
        self.assertFalse(json.loads(path.read_text(encoding='utf8'))['operations']['cutout_use_roughing_regions'])

    def test_reverse_order_persists_exports_and_downloads_only_registered_nc(self):
        self.request['operations']={'order':'cutout_then_roughing','cutout_enabled':True,
            'cutout_bottom_mm':-2.1,'roughing_feed_mm_min':700,'cutout_feed_mm_min':900,
            'plunge_mm_min':150,'spindle_rpm':8000}
        task=self.app.calculate(self.request);deadline=time.monotonic()+10
        while self.app.jobs[task['job']]['status']=='running' and time.monotonic()<deadline:time.sleep(.01)
        state=self.app.jobs[task['job']];self.assertEqual(state['status'],'complete',state)
        self.assertEqual(list(state['motion']['operations']),['cutout','roughing'])
        scene=self.app.restore(self.app.bundle(task['job']))
        self.assertEqual(scene['operations']['order'],'cutout_then_roughing')
        server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(self.app))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def request(method,path,body=None,headers=None):
            con=http.client.HTTPConnection('127.0.0.1',server.server_port)
            con.request(method,path,body=body,headers=headers or {});response=con.getresponse()
            out=(response.status,response.read());con.close();return out
        try:
            body=json.dumps({'project_id':task['job']})
            self.assertEqual(request('POST','/api/export',body)[0],403)
            status,data=request('POST','/api/export',body,{'X-Cam-Token':self.app.token})
            self.assertEqual(status,200,data);export=json.loads(data)
            self.assertEqual(export['report']['order'],['cutout','roughing'])
            another=self.app.export(task['job'])
            self.assertNotEqual(export['filename'],another['filename'])
            status,nc=request('GET','/api/nc/'+export['export_id']);self.assertEqual(status,200)
            self.assertIn(b'S8000.00000 M3',nc)
            self.assertLess(nc.index(b'(OP CUTOUT)'),nc.index(b'(OP ROUGHING)'))
            self.assertEqual(request('GET','/api/nc/../../server.py')[0],400)
        finally:server.shutdown();server.server_close();thread.join()

    def test_uncalculated_project_or_unknown_order_cannot_export(self):
        identifier,_=self.app.prepare(self.request)
        with self.assertRaisesRegex(ValueError,'Calcule'):self.app.export(identifier)
        self.request['operations']={'order':'unknown'}
        with self.assertRaises(ValueError):self.app.calculate(self.request)
        self.assertIsNone(self.app.active)

    def test_roughing_region_priority_persists_and_reaches_calculation_and_preview(self):
        self.request['settings']['boundaries_mm']=[
            [[-4,-1],[-2,-1],[-2,1],[-4,1]],[[2,-1],[4,-1],[4,1],[2,1]]]
        for mode in ('layer','region_first'):
            self.request['operations']={'roughing_order':mode,'roughing_feed_mm_min':700,
                'plunge_mm_min':150,'spindle_rpm':8000}
            identifier,path=self.app.prepare(self.request)
            restored=self.app.restore(self.app.bundle(identifier))
            self.assertEqual(restored['operations']['roughing_order'],mode)
            from cam_project import calculate_project
            result=calculate_project(path,include_motion=True)
            view=self.app.motion_view(result)
            self.assertEqual(view['operations']['roughing']['path_order'],mode)
            if mode=='region_first':self.assertEqual(view['operations']['roughing']['regions'],2)


if __name__=='__main__':unittest.main()
