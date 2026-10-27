import copy
import json
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'roughing'))
from machining_presets import PresetStore,normalize_profile


class PresetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.store=PresetStore(self.root/'machining-presets.json')
        self.profile={'tool':{'id':'fresa','name':'Fresa','diameter_mm':3.175,'cutting_length_mm':22},
            'settings':{'stepdown_mm':.7},'operations':{'roughing_feed_mm_min':700,'plunge_mm_min':150,
                'spindle_rpm':8000,'machining_mode':'smart'},'stepover_percent':40}
    def tearDown(self):self.temp.cleanup()
    def test_named_and_last_used_survive_reopening_and_updates_are_explicit(self):
        d=self.store.update({'action':'save','name':' MDF · 3,175 ','profile':self.profile});identifier=d['selected_id']
        self.assertEqual(PresetStore(self.store.path).read(),d);self.assertEqual(d['presets'][0]['name'],'MDF · 3,175')
        self.profile['operations']['plunge_mm_min']=120
        d=self.store.update({'action':'remember','profile':self.profile,'selected_id':identifier})
        self.assertEqual(d['last_used']['operations']['plunge_mm_min'],120)
        self.assertEqual(d['presets'][0]['profile']['operations']['plunge_mm_min'],150)
        d=self.store.update({'action':'save','id':identifier,'name':'MDF','profile':self.profile})
        self.assertEqual(len(d['presets']),1);self.assertEqual(d['presets'][0]['profile']['operations']['plunge_mm_min'],120)
        d=self.store.update({'action':'delete','id':identifier})
        self.assertFalse(d['presets']);self.assertIsNone(d['selected_id']);self.assertIsNotNone(d['last_used'])
    def test_invalid_values_or_geometry_never_replace_valid_preferences(self):
        self.store.update({'action':'remember','profile':self.profile});before=self.store.path.read_bytes()
        bad=[]
        for key,value in [('plunge_mm_min',-1),('roughing_feed_mm_min',float('nan')),('drill_center_cutting','yes')]:
            p=copy.deepcopy(self.profile);p['operations'][key]=value;bad.append(p)
        for key,value in [('boundaries_mm',[]),('stock_top_mm',42)]:
            p=copy.deepcopy(self.profile);p['settings'][key]=value;bad.append(p)
        p=copy.deepcopy(self.profile);p['operations']['smart_stock_bottom_mm']=-80;bad.append(p)
        for p in bad:
            with self.assertRaises(ValueError):self.store.update({'action':'remember','profile':p})
            self.assertEqual(self.store.path.read_bytes(),before)
    def test_atomic_failure_and_corrupt_file_preserve_existing_bytes(self):
        self.store.update({'action':'remember','profile':self.profile});before=self.store.path.read_bytes()
        with patch('cam_tools.os.replace',side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):self.store.update({'action':'remember','profile':self.profile})
        self.assertEqual(self.store.path.read_bytes(),before)
        self.store.path.write_text('{broken','utf8')
        with self.assertRaisesRegex(ValueError,'preservado'):self.store.read()
        self.assertEqual(self.store.path.read_text('utf8'),'{broken')
    def test_upgrade_recovers_last_settings_without_importing_geometry(self):
        projects=self.root/'projects';p=projects/'job';p.mkdir(parents=True)
        d={'tool':self.profile['tool'],'roughing':{**self.profile['settings'],'stepover_mm':1.27,'bottom_mm':-17,'boundaries_mm':[[1,2]]},
           'operations':{**self.profile['operations'],'cutout_bottom_mm':-17}}
        (p/'project.json').write_text(json.dumps(d),'utf8');self.store.migrate_latest(projects)
        saved=self.store.read()['last_used'];self.assertEqual(saved['operations']['roughing_feed_mm_min'],700)
        self.assertNotIn('boundaries_mm',saved['settings']);self.assertNotIn('cutout_bottom_mm',saved['operations'])
        self.assertAlmostEqual(saved['stepover_percent'],40)
    def test_missing_id_duplicate_limits_and_bad_names_do_not_mutate(self):
        for action in ('save','delete','remember'):
            with self.assertRaises(ValueError):self.store.update({'action':action,'id':'missing','selected_id':'missing','name':'ok','profile':self.profile})
        for name in ('','   ','x'*81,'line\nbreak'):
            with self.assertRaises(ValueError):self.store.update({'action':'save','name':name,'profile':self.profile})
    def test_disabled_operations_can_be_remembered_without_enabling_a_cut(self):
        self.profile['operations'].update(machining_mode='manual',roughing_enabled=False,cutout_enabled=False,drill_enabled=False)
        d=self.store.update({'action':'remember','profile':self.profile});o=d['last_used']['operations']
        self.assertFalse(o['roughing_enabled']);self.assertFalse(o['cutout_enabled']);self.assertFalse(o['drill_enabled'])
        self.assertEqual(PresetStore(self.store.path).read(),d)

if __name__=='__main__':unittest.main()
