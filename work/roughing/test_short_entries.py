import copy
import unittest
from motion_planner import plan_ramps_and_links,MotionPlanningError
from short_entries import extend_short_entries,validate_short_entries
from test_stl_roughing import plane


class ShortEntryTests(unittest.TestCase):
    def setUp(self):
        self.layers=[{'polylines':[
            {'kind':'cleanup','points':[[0,0,-1],[1,0,-1],[3,0,-1]]},
            {'kind':'raster','points':[[1,.02,-.6],[1.0009,.02,-.6]]}]}]
        self.args=dict(diameter=1,contact_diameter=1.2,stock_top=0,angle=3,contains=lambda a,b:True)
    def job(self):return {'layers':self.layers,'parameters':{'z_top':0,'stepdown':1.1},'tool':{'diameter':1,'length':10}}
    def test_short_raster_enters_via_completed_cleanup_without_center_plunge(self):
        with self.assertRaises(MotionPlanningError):plan_ramps_and_links(self.job(),plane(lambda x,y:-3))
        original=copy.deepcopy(self.layers[0]['polylines'][1]['points'])
        self.assertEqual(extend_short_entries(self.layers,**self.args),1)
        validate_short_entries(self.layers,diameter=1,contact_diameter=1.2)
        plan=plan_ramps_and_links(self.job(),plane(lambda x,y:-3))
        self.assertEqual(plan['validation']['status'],'passed');self.assertEqual(plan['center_plunge_entries'],0)
        cuts=[m for m in plan['moves'] if m['kind']=='cut']
        self.assertTrue(any(m['start']==original[0] and m['end']==original[1] for m in cuts))
    def test_distant_or_deeper_or_protected_connector_is_never_invented(self):
        for change in ('distant','deeper','protected','no_contact_guard'):
            with self.subTest(change=change):
                layers=copy.deepcopy(self.layers);args=dict(self.args)
                if change=='distant':
                    for p in layers[0]['polylines'][1]['points']:p[1]=.2
                if change=='deeper':
                    for p in layers[0]['polylines'][1]['points']:p[2]=-2
                if change=='protected':args['contains']=lambda a,b:False
                if change=='no_contact_guard':args['contact_diameter']=1
                self.assertEqual(extend_short_entries(layers,**args),0)
    def test_export_replay_rejects_changed_connector_or_fictitious_cleanup(self):
        extend_short_entries(self.layers,**self.args)
        for change in ('point','proof','missing_reference'):
            layers=copy.deepcopy(self.layers);p=layers[0]['polylines'][1]
            if change=='point':p['points'][1][0]+=.01
            if change=='proof':p['entry_bridge']['cleanup_edge'][0][2]-=.1
            if change=='missing_reference':layers[0]['polylines'].pop(0)
            with self.assertRaisesRegex(ValueError,'sem prova'):validate_short_entries(layers,diameter=1,contact_diameter=1.2)
    def test_raised_depth_preparation_retains_the_contact_certificate(self):
        extend_short_entries(self.layers,**self.args)
        p=copy.deepcopy(self.layers[0]['polylines'][1]);p['kind']='preclear'
        for point in p['points']:point[2]=max(point[2],-.2)
        self.layers[0]['polylines'].insert(1,p)
        validate_short_entries(self.layers,diameter=1,contact_diameter=1.2)

if __name__=='__main__':unittest.main()
