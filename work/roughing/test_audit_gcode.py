import tempfile
from pathlib import Path
import unittest
from audit_gcode import audit,compare


class ModalAuditTests(unittest.TestCase):
    def parse(self,text):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'fixture.nc';p.write_text(text,encoding='utf8')
            return audit(p)

    def test_modal_axis_lines_and_feed_only(self):
        row,moves=self.parse('G21\nG90\nG94\nG0X0Y0Z5\nG1Z0F100\nG1F200\nX10\nY10\n')
        self.assertEqual(len(moves),4)
        self.assertEqual(moves[-1].end,[10,10,0])
        self.assertEqual(row['known_feed_length_mm'],25)
        self.assertAlmostEqual(row['ideal_feed_minutes'],.15)
        self.assertEqual(row['assumptions'],[])

    def test_incremental_and_inches(self):
        _,moves=self.parse('G20\nG90\nG0X0Y0Z0\nG91\nG1X1F2\nY1\n')
        self.assertEqual(moves[-1].end,[25.4,25.4,0])
        self.assertEqual(moves[-1].feed,50.8)

    def test_unknown_start_preserved(self):
        row,moves=self.parse('G21\nG0Z5\nG0X0Y0\nG1X10F100\n')
        self.assertIsNone(moves[0].length)
        self.assertEqual(row['unknown_start_moves'],2)
        self.assertEqual(row['known_feed_length_mm'],10)

    def test_coordinate_change_rejected(self):
        with self.assertRaises(ValueError):
            self.parse('G21\nG90\nG0X0Y0Z0\nG92X10\n')

    def test_comments_are_not_instructions_or_motion(self):
        row,moves=self.parse('G21\nG0X0Y0Z5\n(G1 X999; run a command)\nG1X1F100 ; X900\n')
        self.assertEqual(moves[-1].end,[1,0,5])
        self.assertEqual(row['bounds_mm']['X'],[0,1])

    def test_changed_feed_breaks_equivalence(self):
        _,a=self.parse('G21\nG0X0Y0Z0\nG1X1F100\n')
        _,b=self.parse('G21\nG0X0Y0Z0\nG1X1F200\n')
        self.assertFalse(compare(a,b)['identical_multiset'])

    def test_partial_axis_runs_preserve_unknown_bounds(self):
        row,moves=self.parse('G21\nG90\nG94\nG1Z-1F100\nZ-2\n')
        self.assertEqual(row['feed_runs'][0]['xy_bounds'],[None,None])
        self.assertEqual(row['feed_runs'][0]['z_min'],-2)
        self.assertIsNone(moves[-1].length)
        row,_=self.parse('G21\nG1X1F100\nX2\n')
        self.assertEqual(row['feed_runs'][0]['xy_bounds'],[[1,2],None])
        self.assertIsNone(row['feed_runs'][0]['z_min'])

    def test_repeated_words_modal_conflicts_and_unmodelled_axes_rejected(self):
        for block in ('G0X1X2','G0G1X1F100','G20G21','G90G91',
                      'G1X1F100F200','M3M5','G0X1A5','G1X1F-1','M6'):
            with self.subTest(block=block),self.assertRaises(ValueError):
                self.parse('G21\nG90\nG94\nG0X0Y0Z0\n'+block+'\n')

    def test_modes_declared_after_motion_do_not_erase_prior_assumptions(self):
        row,_=self.parse('G21\nG0X0Y0Z0\nG1X1F100\nG90G94\nX2\n')
        self.assertEqual(len(row['assumptions']),2)


if __name__=='__main__':unittest.main()
