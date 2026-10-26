"""Exercise process isolation, failure transport, cancellation and deadlines."""
import json
import multiprocessing
from pathlib import Path
import tempfile
import threading
import unittest

from calculation_worker import run_calculation,CalculationCancelled
from test_server import plane_stl
from server import App


class CalculationWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.app=App(self.root/'uploads',self.root/'outputs/projects')
        asset=self.app.upload(plane_stl())
        self.request={'asset':asset,'placement':{'units':'mm','xy_origin':'keep','z_origin':'keep'},
            'tool':{'id':'one','name':'Topo 1','diameter_mm':1,'cutting_length_mm':5},
            'settings':{'stepdown_mm':1,'stepover_mm':.8,'stock_top_mm':0,'bottom_mm':-2,
                'boundaries_mm':[[[-2,-1],[2,-1],[2,1],[-2,1]]]}}
        _,self.project=self.app.prepare(self.request)

    def tearDown(self):
        self.app.shutdown();self.temp.cleanup()

    def test_real_process_calculates_and_returns_validated_result(self):
        events=[]
        result=run_calculation(self.project,events.append,threading.Event())
        self.assertEqual(result['motion']['validation']['status'],'passed')
        self.assertGreater(len(result['motion']['moves']),0)
        self.assertTrue(events[0]['worker_alive']);self.assertIsInstance(events[0]['worker_pid'],int)
        self.assertTrue(self.project.with_name('result.json').exists())

    def test_child_exception_is_reported_and_persisted(self):
        self.project.write_text('{invalid JSON',encoding='utf8')
        with self.assertRaises(RuntimeError):run_calculation(self.project,lambda update:None,threading.Event())
        failure=json.loads(self.project.with_name('calculation-error.json').read_text(encoding='utf8'))
        self.assertEqual(failure['status'],'failed');self.assertIn('JSON',failure['error_type'])
        self.assertIn('Traceback',failure['traceback'])

    def test_cancellation_stops_owned_process_and_releases_resources(self):
        signal=threading.Event();pids=[]
        def cancel_after_start(update):
            if update.get('worker_pid'):
                pids.append(update['worker_pid']);signal.set()
        with self.assertRaises(CalculationCancelled):run_calculation(self.project,cancel_after_start,signal)
        self.assertTrue(pids)
        self.assertFalse(any(p.pid in pids for p in multiprocessing.active_children()))

    def test_deadline_terminates_a_job_without_publishing_a_result(self):
        with self.assertRaisesRegex(TimeoutError,'excedeu'):
            run_calculation(self.project,lambda update:None,threading.Event(),timeout_s=.001)
        self.assertFalse(self.project.with_name('result.json').exists())


if __name__=='__main__':unittest.main()
