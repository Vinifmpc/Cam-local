"""Controller routes exercise real loopback authentication, never a serial port."""
import json
from http.server import ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock
import urllib.error
import urllib.request

from server import App, handler_for
from command_client import CommandClient, command_schema
from command_control import UI_ACTIONS


class GrblHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        root=Path(self.temp.name)
        self.app=App(root/'uploads',root/'projetos')
        self.controller=Mock()
        self.app.controller=self.controller
        self.server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(self.app))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.client=CommandClient(root,self.server.server_port)

    def tearDown(self):
        self.app.shutdown()
        self.server.shutdown();self.server.server_close();self.thread.join()
        self.temp.cleanup()

    def test_routes_forward_bounded_profile_without_a_model(self):
        self.controller.ports.return_value={'ports':[{'port':'COM4','description':'Test'}]}
        self.assertEqual(self.client.http('/api/grbl/ports',{}),self.controller.ports.return_value)
        self.controller.read.return_value={'read_id':'snapshot','status':'read'}
        connection={'port':'COM4','baudrate':115200}
        self.assertEqual(self.client.http('/api/grbl/read',connection),self.controller.read.return_value)
        self.controller.read.assert_called_once_with(connection)
        target={'machine_max_rate_mm_min':[1500]*3,'machine_acceleration_mm_s2':[80,80,100]}
        report={'status':'partial','verified':False,'written_settings':['$120'],'error':'Test interruption'}
        self.controller.apply.return_value=report
        result=self.client.http('/api/grbl/apply',{**connection,'read_id':'snapshot','values':target})
        self.assertEqual(result,report)
        self.controller.apply.assert_called_once_with(connection,target,'snapshot')
        self.assertFalse(self.app.jobs)

    def test_controller_routes_require_token_and_same_origin_before_dispatch(self):
        for action in ('ports','read','apply'):
            for headers in ({},{'X-Cam-Token':self.app.token,'Origin':'https://example.com'}):
                request=urllib.request.Request(self.client.base+'/api/grbl/'+action,data=b'{}',headers=headers)
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(request)
                self.assertEqual(caught.exception.code,403)
        self.assertEqual(self.controller.mock_calls,[])

    def test_connection_failure_is_reported_without_retry(self):
        self.controller.read.side_effect=RuntimeError('Porta ocupada pelo CNCjs')
        with self.assertRaisesRegex(RuntimeError,'CNCjs'):
            self.client.http('/api/grbl/read',{'port':'COM4'})
        self.controller.read.assert_called_once()
        self.controller.apply.assert_not_called()

    def test_schema_exposes_controller_actions_without_a_running_app(self):
        actions=command_schema()['actions']
        for name in ('controller.ports','controller.read','controller.apply','controller.import'):
            self.assertIn(name,UI_ACTIONS)
            self.assertIn(name,actions)


if __name__=='__main__':unittest.main()
