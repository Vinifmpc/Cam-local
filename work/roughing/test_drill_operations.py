"""Three-operation ordering, saved settings and drilling feed/reach contracts."""
from dataclasses import asdict
from itertools import permutations,product
import math
from types import SimpleNamespace
import unittest

from cam_operations import OperationSettings,add_timing,compose,validate_operations
from cam_tools import Tool


class DrillOperationSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tool=Tool(id='flat',name='Topo 3 mm',diameter_mm=3,cutting_length_mm=10,
                       feed_mm_min=600,plunge_mm_min=120)
        self.rough=SimpleNamespace(stock_top_mm=2,bottom_mm=-8)

    def test_all_orders_filter_enabled_operations_and_keep_legacy_order_consistent(self):
        names=['roughing','drill','cutout']
        for order in permutations(names):
            for enabled in product((False,True),repeat=3):
                if not any(enabled):continue
                values={name+'_enabled':active for name,active in zip(names,enabled)}
                with self.subTest(order=order,enabled=enabled):
                    settings=OperationSettings(operation_sequence=list(order),**values)
                    self.assertEqual(settings.sequence(),[name for name in order if values[name+'_enabled']])
                    expected='roughing_then_cutout' if order.index('roughing')<order.index('cutout') else 'cutout_then_roughing'
                    self.assertEqual(settings.order,expected)
                    self.assertEqual(OperationSettings.from_dict(asdict(settings)),settings)

    def test_legacy_order_preserves_existing_relative_order_and_appends_drill(self):
        for order,expected in (('roughing_then_cutout',['roughing','cutout','drill']),
                               ('cutout_then_roughing',['cutout','roughing','drill'])):
            with self.subTest(order=order):
                settings=OperationSettings(order=order,cutout_enabled=True,drill_enabled=True)
                self.assertIsNone(settings.operation_sequence)
                self.assertEqual(settings.sequence(),expected)
                old=OperationSettings.from_dict({'order':order,'roughing_enabled':True,'cutout_enabled':True})
                self.assertEqual(old.sequence(),expected[:2])
                self.assertFalse(old.drill_enabled)
                self.assertFalse(old.drill_allow_helix)
                self.assertFalse(old.drill_center_cutting)
                self.assertFalse(old.drill_compensate_facets)

    def test_sequence_is_an_exact_permutation_and_does_not_alias_input_list(self):
        invalid=([],['roughing','cutout'],['roughing','cutout','cutout'],
                 ['roughing','drill','unknown'],['roughing','drill',0],
                 ('roughing','drill','cutout'),'roughing,drill,cutout',
                 {'roughing':0,'drill':1,'cutout':2})
        for sequence in invalid:
            with self.subTest(sequence=sequence),self.assertRaisesRegex(ValueError,'Sequência'):
                OperationSettings(operation_sequence=sequence)
        sequence=['drill','roughing','cutout']
        settings=OperationSettings(operation_sequence=sequence,drill_enabled=True)
        sequence.reverse()
        self.assertEqual(settings.sequence(),['drill','roughing'])

    def test_drill_only_and_disabling_all_operations(self):
        self.assertEqual(OperationSettings(roughing_enabled=False,drill_enabled=True).sequence(),['drill'])
        with self.assertRaisesRegex(ValueError,'Ative ao menos'):
            OperationSettings(roughing_enabled=False,cutout_enabled=False,drill_enabled=False)

    def test_drill_booleans_require_explicit_boolean_values(self):
        for key in ('drill_enabled','drill_allow_helix','drill_center_cutting','drill_compensate_facets'):
            for value in (0,1,None,'false'):
                with self.subTest(key=key,value=value),self.assertRaisesRegex(ValueError,'booleano'):
                    OperationSettings(**{key:value})

    def test_facet_compensation_is_explicit_and_persists_as_boolean(self):
        self.assertFalse(OperationSettings().drill_compensate_facets)
        settings=OperationSettings(drill_enabled=True,drill_compensate_facets=True)
        self.assertTrue(OperationSettings.from_dict(asdict(settings)).drill_compensate_facets)

    def test_drill_dimensions_and_feeds_are_finite_and_positive(self):
        for key in ('drill_peck_mm','drill_tolerance_mm','drill_feed_mm_min'):
            for value in (0,-1,True,float('nan'),float('inf'),'1'):
                with self.subTest(key=key,value=value),self.assertRaises(ValueError):
                    OperationSettings(**{key:value})
        for value in (True,float('nan'),float('inf'),'-8'):
            with self.subTest(bottom=value),self.assertRaisesRegex(ValueError,'Z final do drill'):
                OperationSettings(drill_bottom_mm=value)
        settings=OperationSettings(drill_bottom_mm=-8.5,drill_peck_mm=.4,drill_tolerance_mm=.01,
                                   drill_feed_mm_min=350)
        self.assertEqual(settings.drill_bottom_mm,-8.5)

    def test_reach_uses_stock_top_and_default_bottom_preserves_cutout_return(self):
        options=OperationSettings(roughing_enabled=False,drill_enabled=True)
        self.assertEqual(validate_operations(options,self.rough,self.tool),-8)
        self.assertEqual(validate_operations(OperationSettings(roughing_enabled=False,drill_enabled=True,
            cutout_bottom_mm=-4,drill_bottom_mm=-8),self.rough,self.tool),-4)
        for bottom,message in ((2,'positiva'),(3,'positiva'),(-8.001,'comprimento de corte')):
            with self.subTest(bottom=bottom),self.assertRaisesRegex(ValueError,message):
                validate_operations(OperationSettings(roughing_enabled=False,drill_enabled=True,
                    drill_bottom_mm=bottom),self.rough,self.tool)
        deep=SimpleNamespace(stock_top_mm=2,bottom_mm=-9)
        with self.assertRaisesRegex(ValueError,'drill excede'):
            validate_operations(options,deep,self.tool)
        # An inactive operation does not reject an otherwise valid setup.
        validate_operations(OperationSettings(drill_bottom_mm=-100),self.rough,self.tool)

    def test_timing_selects_drill_feed_and_keeps_plunge_and_rapid_rules(self):
        options=OperationSettings(drill_enabled=True,roughing_feed_mm_min=500,
            cutout_feed_mm_min=400,drill_feed_mm_min=300,plunge_mm_min=100,rapid_mm_min=3000)
        motion={'moves':[
            {'kind':'cut','operation':'roughing','start':[0,0,0],'end':[5,0,0]},
            {'kind':'cut','operation':'cutout','start':[0,0,0],'end':[5,0,0]},
            {'kind':'drill_helix','operation':'drill','start':[0,0,0],'end':[3,4,-1]},
            {'kind':'drill_peck','operation':'drill','start':[0,0,0],'end':[0,0,-2]},
            {'kind':'retract','operation':'drill','start':[0,0,-2],'end':[0,0,2]},
        ]}
        add_timing(motion,options,self.tool)
        self.assertEqual([m['feed_mm_min'] for m in motion['moves']],[500,400,300,100,3000])
        expected=60*(5/500+5/400+math.sqrt(26)/300+2/100+4/3000)
        self.assertAlmostEqual(motion['timing']['duration_s'],expected)
        self.assertTrue(motion['timing']['available'])

    def test_drill_feed_falls_back_to_tool_and_missing_feed_keeps_untimed_contract(self):
        def motion():return {'moves':[{'kind':'drill_helix','operation':'drill',
                                      'start':[0,0,0],'end':[1,0,-1]}]}
        timed=add_timing(motion(),OperationSettings(drill_enabled=True),self.tool)
        self.assertEqual(timed['moves'][0]['feed_mm_min'],600)
        nofeed=Tool(id='bare',name='Sem avanços',diameter_mm=3,cutting_length_mm=10)
        untimed=add_timing(motion(),OperationSettings(drill_enabled=True),nofeed)
        self.assertFalse(untimed['timing']['available'])
        self.assertIsNone(untimed['moves'][0]['duration_s'])

    def test_composition_with_intervening_drill_keeps_prior_roughing_proof_offset(self):
        def plan(start,end,proof):
            return {'initial_position':start,'final_position':end,'safe_z':3,
                'moves':[{'id':0,'kind':'cut','start':start,'end':end,'proof':proof}],
                'entries':[],'validation':{'status':'passed','source_edges_preserved':1}}
        # A Drill before Rough changes Rough's global source-move offset.
        drill=plan([0,0,3],[1,0,3],{'source_cut_move':0})
        rough=plan([1,0,3],[2,0,3],{'source_cut_move':0})
        cutout=plan([2,0,3],[3,0,3],{'source_prior_cut_move':0})
        cutout['prior_roughing']=True
        options=OperationSettings(drill_enabled=True,cutout_enabled=True,
                                 operation_sequence=['drill','roughing','cutout'])
        result=compose([('drill',drill),('roughing',rough),('cutout',cutout)],options,self.tool)
        self.assertEqual([m['operation'] for m in result['moves']],options.sequence())
        self.assertEqual(result['moves'][2]['proof']['source_cut_move'],1)
        self.assertEqual(result['validation']['source_edges_preserved'],3)
        with self.assertRaisesRegex(ValueError,'anterior incompatível'):
            compose([('cutout',cutout),('roughing',rough),('drill',drill)],options,self.tool)


if __name__=='__main__':unittest.main()
