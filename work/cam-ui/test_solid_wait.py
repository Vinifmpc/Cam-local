import unittest
from unittest.mock import patch
from server import App  # Configure the same engine import path as the app.
from command_client import CommandClient,CommandError,command_schema


class SolidWaitTests(unittest.TestCase):
    def client(self,states):
        client=CommandClient.__new__(CommandClient)
        snapshots=iter(states)
        client.ui=lambda command:{'simulation':next(snapshots)}
        return client

    def test_final_wait_does_not_require_grid_or_change_playback_position(self):
        common={'stock_ready':False,'stock_busy':True,'stock_applied':0,'stock_target':0,'solid_ready':False,'time_s':0}
        ready={**common,'solid_precompute':{'status':'ready'}}
        client=self.client([{**common,'solid_precompute':{'status':'running'}},ready])
        with patch('command_client.time.sleep'):
            result=client.execute({'action':'simulation.wait','surface':'final'})
        self.assertIs(result,ready)
        self.assertEqual(result['time_s'],0)

    def test_failed_and_missing_final_surface_report_immediately(self):
        for value,phrase in (({'status':'error','error':'Mesh failed'},'Mesh failed'),({'status':'idle'},'Calcule')):
            client=self.client([{'solid_precompute':value}])
            with self.assertRaisesRegex(CommandError,phrase):
                client.execute({'action':'simulation.wait','surface':'final'})

    def test_current_solid_wait_still_requires_matching_grid_state(self):
        pending={'stock_ready':True,'stock_busy':True,'stock_applied':0,'stock_target':1,'solid_ready':True}
        ready={**pending,'stock_busy':False,'stock_applied':1}
        with patch('command_client.time.sleep'):
            result=self.client([pending,ready]).execute({'action':'simulation.wait','surface':'solid'})
        self.assertIs(result,ready)

    def test_invalid_surface_is_rejected_and_schema_documents_background_wait(self):
        with self.assertRaisesRegex(CommandError,'surface'):
            self.client([]).execute({'action':'simulation.wait','surface':'unknown'})
        self.assertIn('final',command_schema()['actions']['simulation.wait']['surface'])

    def test_gpu_wait_is_independent_of_cpu_grid_and_requires_current_target(self):
        common={'stock_ready':False,'stock_busy':True,'stock_applied':0,'stock_target':5,'solid_ready':False}
        pending={**common,'gpu':{'available':True,'ready':True,'target':4}}
        ready={**common,'gpu':{'available':True,'ready':True,'target':5}}
        with patch('command_client.time.sleep'):
            self.assertIs(self.client([pending,ready]).execute({'action':'simulation.wait','surface':'gpu'}),ready)
        with self.assertRaisesRegex(CommandError,'driver unavailable'):
            self.client([{'gpu':{'available':False,'error':'driver unavailable'}}]).execute({'action':'simulation.wait','surface':'gpu'})
