"""Prior roughing may remove complete cutout passes, never uncut regions."""
import copy
from dataclasses import asdict
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np
from camadas_desbaste import planejar_camadas
from cutout_rest import adapt_cutout_to_prior,validate_cutout_rest
from motion_planner import plan_ramps_and_links,validate_motion,MotionPlanningError
from cam_operations import OperationSettings
from cam_tools import Tool
from cam_project import RoughingSettings,calculate_project


MESH=np.asarray([[[-10,-10,-4],[10,-10,-4],[10,10,-4]],
                 [[-10,-10,-4],[10,10,-4],[-10,10,-4]]],float)
CONTOUR=[[-2,-2],[2,-2],[2,2],[-2,2],[-2,-2]]


def cutout_job(bottom=-3):
    levels=planejar_camadas(bottom,bottom,0,1)
    layers=[{'z':level.z,'depth_index':i,'contour':0,'contour_kind':'external',
             'polylines':[{'points':[[x,y,level.z] for x,y in CONTOUR]}]}
            for i,level in enumerate(levels)]
    return {'schema_version':1,'units':'mm','scope':'silhouette_2d_cutout',
        'tool':{'type':'flat_cylindrical','diameter':2,'length':5},
        'parameters':{'z_top':0,'z_bottom':bottom,'stepdown':1,'direction':'climb'},
        'depth_levels':[asdict(level) for level in levels],
        'contours':[{'index':0,'kind':'external','points_xy':CONTOUR}],
        'layers':layers,'cutting_edges':4*len(levels)}


def prior_roughing(*,bottom=-3,partial=False):
    job=cutout_job(bottom)
    if partial:
        for layer in job['layers']:
            # Represents a keep-in window that only cleared one side.
            layer['polylines'][0]['points']=layer['polylines'][0]['points'][:2]
        job['cutting_edges']=len(job['layers'])
    return plan_ramps_and_links(job,MESH)


class CutoutRestMaterialTests(unittest.TestCase):
    def test_fully_cleared_outer_passes_are_omitted_and_empty_plan_is_valid(self):
        source=cutout_job();before=copy.deepcopy(source);prior=prior_roughing()
        effective=adapt_cutout_to_prior(source,prior)
        self.assertEqual(source,before)
        self.assertEqual(effective['layers'],[])
        self.assertEqual(effective['depth_levels'],[])
        self.assertEqual(effective['cutting_edges'],0)
        self.assertEqual(effective['contours'],source['contours'])
        self.assertEqual(effective['rest_material']['skipped_depth_passes'],3)
        self.assertEqual(validate_cutout_rest(effective,prior)['status'],'passed')
        plan=plan_ramps_and_links(effective,MESH,initial_position=prior['final_position'],prior_motion=prior)
        self.assertEqual(plan['moves'],[])
        self.assertEqual(validate_motion(plan,effective,prior_motion=prior)['status'],'passed')

    def test_keep_in_restricted_rough_does_not_remove_whole_cutout_layers(self):
        source=cutout_job();prior=prior_roughing(partial=True)
        effective=adapt_cutout_to_prior(source,prior)
        self.assertEqual(effective['layers'],source['layers'])
        self.assertEqual(effective['cutting_edges'],source['cutting_edges'])
        self.assertEqual(effective['rest_material']['skipped_depth_passes'],0)
        self.assertEqual(validate_cutout_rest(effective,prior)['status'],'passed')

    def test_shallow_roughing_preserves_remaining_bottom_layer(self):
        source=cutout_job();prior=prior_roughing(bottom=-2)
        effective=adapt_cutout_to_prior(source,prior)
        self.assertEqual(effective['layers'],source['layers'][-1:])
        self.assertEqual([level['z'] for level in effective['depth_levels']],[-3])
        self.assertEqual(effective['rest_material']['skipped_depth_passes'],2)
        plan=plan_ramps_and_links(effective,MESH,initial_position=prior['final_position'],prior_motion=prior)
        self.assertEqual(plan['validation']['status'],'passed')
        self.assertEqual(plan['validation']['source_edges_preserved'],4)

    def test_travel_and_future_cutout_paths_do_not_credit_removed_stock(self):
        source=cutout_job();prior=prior_roughing()
        for move in prior['moves']:
            if move['kind']=='cut':move['kind']='travel'
        effective=adapt_cutout_to_prior(source,prior)
        self.assertEqual(effective['layers'],source['layers'])
        self.assertEqual(effective['rest_material']['skipped_depth_passes'],0)

    def test_missing_unvalidated_or_changed_tool_prior_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'anterior validada'):
            adapt_cutout_to_prior(cutout_job(),None)
        prior=prior_roughing();prior['validation']['status']='failed'
        with self.assertRaises(MotionPlanningError):adapt_cutout_to_prior(cutout_job(),prior)
        prior=prior_roughing();source=cutout_job();source['tool']['diameter']=2.1
        with self.assertRaisesRegex(MotionPlanningError,'mesma fresa'):
            adapt_cutout_to_prior(source,prior)

    def test_export_recheck_rejects_tampered_omissions_metadata_and_geometry(self):
        prior=prior_roughing(bottom=-2);effective=adapt_cutout_to_prior(cutout_job(),prior)
        for changed in ('omit_bottom','move_edge','prior_digest','source_geometry','depth_levels'):
            bad=copy.deepcopy(effective)
            if changed=='omit_bottom':bad['layers']=[];bad['cutting_edges']=0
            elif changed=='move_edge':bad['layers'][0]['polylines'][0]['points'][0][0]+=.1
            elif changed=='prior_digest':bad['rest_material']['prior_sha256']='0'*64
            elif changed=='source_geometry':bad['rest_source_layers'][0]['polylines'][0]['points'][0][0]+=.1
            elif changed=='depth_levels':bad['depth_levels']=[]
            with self.subTest(changed=changed),self.assertRaises(ValueError):
                validate_cutout_rest(bad,prior)

    def test_pipeline_reuse_requires_roughing_first_and_enabled_option(self):
        tool=Tool(id='flat2',name='Topo 2',diameter_mm=2,cutting_length_mm=5)
        settings=RoughingSettings(stepdown_mm=1,stepover_mm=1,stock_top_mm=0,bottom_mm=-3)
        mesh=SimpleNamespace(triangles=MESH,summary=lambda:{'triangle_count':2})
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'project.json';path.write_text('{}')
            for order,enabled,roughing,expected in (
                    ('roughing_then_cutout',True,True,1),
                    ('roughing_then_cutout',False,True,0),
                    ('cutout_then_roughing',True,True,0),
                    ('roughing_then_cutout',True,False,0)):
                options=OperationSettings(order=order,roughing_enabled=roughing,cutout_enabled=True,
                                          cutout_use_prior_roughing=enabled)
                record={'operations':asdict(options),'notes':''}
                with self.subTest(order=order,enabled=enabled,roughing=roughing), \
                     patch('cam_project.load_project',return_value=(record,mesh,tool,settings,{})), \
                     patch('stl_roughing.generate_stl_roughing',side_effect=lambda *a,**k:cutout_job()), \
                     patch('cutout_rest.adapt_cutout_to_prior',wraps=adapt_cutout_to_prior) as adapted:
                    result=calculate_project(path,include_motion=True)
                    self.assertEqual(adapted.call_count,expected)
                    self.assertEqual(result['motion']['validation']['status'],'passed')
                    self.assertEqual(bool(result['cutout'].get('rest_material')),bool(expected))


if __name__=='__main__':unittest.main()
