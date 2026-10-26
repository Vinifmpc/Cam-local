"""Real spawn/Node calculations preserve all serial geometry and limits."""
import os
import unittest
from unittest.mock import patch
import numpy as np

from camadas_desbaste import planejar_camadas
from layer_roughing import prepare_layer_sources
from parallel_workers import geometry_workers,worker_limit
from stl_roughing import contact_paths
from test_layer_roughing import pocket
from test_stl_roughing import plane,rect


class ParallelGeometryTests(unittest.TestCase):
    def test_automatic_worker_budget_and_small_job_threshold(self):
        with patch.dict(os.environ,{'CAM_WORKERS':''}),patch('parallel_workers.os.cpu_count',return_value=20):
            self.assertEqual(worker_limit(),4)
            self.assertEqual(geometry_workers(25,69_850),4)
            self.assertEqual(geometry_workers(3,100_000),1)
            self.assertEqual(geometry_workers(25,500),1)
        with patch.dict(os.environ,{'CAM_WORKERS':'1'}):
            self.assertEqual(geometry_workers(25,69_850),1)
        for value in ('zero','0','9'):
            with patch.dict(os.environ,{'CAM_WORKERS':value}),self.assertRaisesRegex(ValueError,'CAM_WORKERS'):
                worker_limit()

    def test_spawn_layer_regions_match_serial_exactly_in_both_strategies(self):
        triangles=pocket(True);centers=[np.asarray(rect(-4,-4,4,4),float)]
        layers=planejar_camadas(-3,-3,0,1)
        for strategy in ('conformal','planar'):
            with self.subTest(strategy=strategy):
                options=dict(radius=.605,top=0,axial_allowance=.1,strategy=strategy,
                    stepover=.8,phase=0,angle=23,cleanup=True)
                with patch('layer_roughing.geometry_workers',return_value=1):
                    expected=prepare_layer_sources(triangles,centers,layers,**options)
                events=[]
                with patch('layer_roughing.geometry_workers',return_value=2):
                    actual=prepare_layer_sources(triangles,centers,layers,**options,
                        progress=lambda p,f:events.append((p,f)))
                self.assertEqual(actual,expected)
                fractions=[f for _,f in events]
                self.assertEqual(fractions,sorted(fractions));self.assertEqual(fractions[-1],1)
                self.assertTrue(any('2 processos' in p for p,_ in events))

    def test_parallel_node_contact_matches_all_serial_samples_in_source_order(self):
        triangles=np.concatenate([plane(lambda x,y:-3+.1*x),plane(lambda x,y:0,x0=-1,x1=1,y0=-1,y1=1)])
        segments=[{'start':[-4,y],'end':[4-i*.2,y]} for i,y in enumerate(np.linspace(-3,3,40))]
        options=dict(diameter=1,length=10,sampling=.2,floor=-10)
        with patch('stl_roughing.geometry_workers',return_value=1):
            expected=contact_paths(triangles,segments,**options)
        events=[]
        with patch('stl_roughing.geometry_workers',return_value=4):
            actual=contact_paths(triangles,segments,**options,progress=lambda p,f:events.append((p,f)))
        self.assertEqual(actual,expected)
        fractions=[f for _,f in events]
        self.assertEqual(fractions,sorted(fractions));self.assertEqual(fractions[-1],1)

    def test_parallel_contact_retains_global_sample_limit(self):
        with patch('stl_roughing.geometry_workers',return_value=4),self.assertRaisesRegex(ValueError,'sample limit'):
            contact_paths(plane(),[{'start':[0,0],'end':[100,0]}]*400,
                          diameter=1,length=10,sampling=.02,floor=-10)

    def test_worker_errors_are_propagated_without_partial_result(self):
        options=dict(diameter=1,length=10,sampling=.2,floor=-10)
        with patch('stl_roughing.geometry_workers',return_value=2),\
                patch('stl_roughing._contact_batch',side_effect=RuntimeError('native worker failed')),\
                self.assertRaisesRegex(RuntimeError,'native worker failed'):
            contact_paths(plane(),[{'start':[0,0],'end':[2,0]}]*40,**options)


if __name__=='__main__':unittest.main()
