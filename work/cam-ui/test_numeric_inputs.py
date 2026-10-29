"""Browser number constraints must accept the CAM's actual decimal values."""
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path
import unittest


class InputParser(HTMLParser):
    def __init__(self,html):
        super().__init__();self.inputs={};self.feed(html)
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='input' and attrs.get('type')=='number':self.inputs[attrs['id']]=attrs


def accepted(attributes,value):
    if value=='':return 'required' not in attributes
    value=Decimal(str(value))
    if 'min' in attributes and value<Decimal(attributes['min']):return False
    if 'max' in attributes and value>Decimal(attributes['max']):return False
    step=attributes.get('step','1')
    if step=='any':return True
    base=Decimal(attributes.get('min',attributes.get('value','0')))
    return (value-base)%Decimal(step)==0


class NumericInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs=InputParser((Path(__file__).parent/'static/index.html').read_text('utf8')).inputs

    def test_common_saved_values_are_valid_for_browser_constraints(self):
        examples={'toolLength':22,'toolOverall':40,'toolDiameter':3.175,'toolFeed':1000.5,
            'toolPlunge':200.25,'toolRpm':12000,'bottom':17,'stepdown':.8,'stepover':40,
            'surfaceError':.15,'sampling':.2,'roughFeed':1000,'plungeFeed':200,'clearance':2.54,
            'drillDepth':17,'drillPeck':1,'drillRetract':1,'drillReentryGap':.25,
            'drillTolerance':.03,'cutoutDepth':17.1,'cutoutStepdown':.7,'spindleRpm':12000,
            'machineMaxRateX':1500,'machineAccelerationX':80,'machineStepsX':400,
            'stockX0':-5.125,'regionRadiusX':1.5875,'originPointX':12.3456}
        for name,value in examples.items():
            with self.subTest(field=name,value=value):self.assertTrue(accepted(self.inputs[name],value))

    def test_continuous_fields_do_not_quantize_valid_values(self):
        for name,attrs in self.inputs.items():
            if name not in ('toolFlutes','machinePlannerBlocks'):
                with self.subTest(field=name):self.assertEqual(attrs['step'],'any')
        for value in ('22','22.1','22.0255'):
            self.assertTrue(accepted(self.inputs['toolLength'],value))

    def test_required_fields_integer_counts_and_ranges_remain_enforced(self):
        for field in ('toolLength','toolDiameter'):
            for value in ('',0,-1):self.assertFalse(accepted(self.inputs[field],value))
        self.assertTrue(accepted(self.inputs['toolOverall'],''))
        for field,valid in (('toolFlutes',2),('machinePlannerBlocks',15)):
            self.assertTrue(accepted(self.inputs[field],valid))
            self.assertFalse(accepted(self.inputs[field],1.5))
        self.assertFalse(accepted(self.inputs['toolFlutes'],101))
        self.assertFalse(accepted(self.inputs['stepover'],101))


if __name__=='__main__':unittest.main()
