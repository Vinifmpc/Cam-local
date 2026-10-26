import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer

from command_control import CommandMailbox
from command_client import CommandClient,CommandError,run_commands
from server import App,handler_for


class MailboxTests(unittest.TestCase):
    def test_delivered_once_and_ack_is_idempotent(self):
        box=CommandMailbox();identifier=box.submit({'action':'state'})['command_id']
        item=box.next('ui',0);self.assertEqual(item['command_id'],identifier)
        self.assertIsNone(box.next('ui',0)['command_id'])
        box.complete(identifier,'ui',{'revision':3})
        box.complete(identifier,'ui',{'revision':4})
        self.assertEqual(box.result(identifier),{'status':'complete','result':{'revision':3}})

    def test_expired_pending_action_never_executes(self):
        box=CommandMailbox()
        with patch('command_control.time.monotonic',return_value=10):identifier=box.submit({'action':'calculate.start'},1)['command_id']
        with patch('command_control.time.monotonic',return_value=12):
            self.assertEqual(box.result(identifier)['status'],'expired')
            self.assertIsNone(box.next('ui',0)['command_id'])

    def test_reject_unknown_actions_and_wrong_owner(self):
        box=CommandMailbox()
        with self.assertRaises(ValueError):box.submit({'action':'eval','code':'anything'})
        identifier=box.submit({'action':'state'})['command_id'];box.next('first',0)
        with self.assertRaises(RuntimeError):box.next('second',0)
        with self.assertRaises(ValueError):box.complete(identifier,'second',{})
        box.close();self.assertEqual(box.result(identifier)['status'],'failed')

    def test_queue_is_bounded_without_dropping_live_actions(self):
        box=CommandMailbox()
        for _ in range(128):box.submit({'action':'state'})
        with self.assertRaises(RuntimeError):box.submit({'action':'state'})
        first=box.next('ui',0);box.complete(first['command_id'],'ui',{})
        box.submit({'action':'state'});self.assertEqual(len(box.records),128)


class CommandHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.app=App(self.root/'data',self.root/'outputs/projects')
        self.server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(self.app))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.client=CommandClient(self.root,self.server.server_port)

    def tearDown(self):
        self.app.shutdown();self.server.shutdown();self.server.server_close();self.thread.join();self.temp.cleanup()

    def test_real_http_dispatch_reply_and_failure_are_compact(self):
        def ui():
            for i in range(2):
                item=self.client.http('/api/commands/next',{'client':'test-ui','wait_s':1})
                self.client.http('/api/commands/complete',{'client':'test-ui','command_id':item['command_id'],
                    **({'result':{'revision':7}} if i==0 else {'error':'Erro de ferramenta'})})
        thread=threading.Thread(target=ui);thread.start()
        self.assertEqual(self.client.ui({'action':'state'}),{'revision':7})
        with self.assertRaisesRegex(CommandError,'Erro de ferramenta'):self.client.ui({'action':'tool.set','id':'bad'})
        thread.join()

    def test_command_routes_require_token(self):
        import urllib.request,urllib.error
        req=urllib.request.Request(self.client.base+'/api/commands/submit',data=b'{"command":{"action":"state"}}')
        with self.assertRaises(urllib.error.HTTPError) as result:urllib.request.urlopen(req)
        self.assertEqual(result.exception.code,403)

    def test_native_show_does_not_depend_on_a_polling_javascript_client(self):
        shown=threading.Event();self.app.on_show=shown.set
        self.assertEqual(self.client.execute({'action':'app.show'}),{'shown':True})
        self.assertTrue(shown.wait(1));self.assertFalse(self.app.commands.records)

    def test_batch_stops_on_failure_and_schema_works_without_app(self):
        report=self.root/'reply.json'
        result=run_commands([{'action':'schema'}],report,self.root,port=1)
        self.assertEqual(result['status'],'complete');self.assertIn('simulation.seek',result['results'][0]['result']['actions'])
        result=run_commands([{'action':'ping'},{'action':'unknown'},{'action':'calculate.start'}],report,self.root,port=self.server.server_port)
        self.assertEqual(result['status'],'failed');self.assertEqual(result['current_index'],1)
        self.assertEqual(len(result['results']),1);self.assertEqual(json.loads(report.read_text())['status'],'failed')

    def test_output_is_not_silently_overwritten(self):
        output=self.root/'preserve.nc';output.write_bytes(b'original')
        with self.assertRaisesRegex(CommandError,'Destino já existe'):
            self.client.execute({'action':'nc.export','path':str(output)})
        self.assertEqual(output.read_bytes(),b'original');self.assertFalse(self.app.commands.records)

    def test_summary_never_transfers_large_motion_or_changes_job(self):
        self.app.jobs['test']={'status':'complete','motion':{'moves':[[0]*9]*10000,'timing':{},'counts':{},'validation':{},'operations':{}},'inspection':{'big':[0]*1000}}
        result=self.client.http('/api/jobs/test?summary=1')
        self.assertEqual(result['motion_summary']['moves'],10000);self.assertNotIn('motion',result);self.assertNotIn('inspection',result)
        self.assertEqual(len(self.app.jobs['test']['motion']['moves']),10000)


if __name__=='__main__':unittest.main()
