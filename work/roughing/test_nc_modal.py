"""Modal NC compaction preserves each mapped, independently replayed move."""
from pathlib import Path
import tempfile
import unittest

from audit_gcode import WORD,audit
from grbl_post import COORD_ERROR,render,verify_readback


class ModalRenderTests(unittest.TestCase):
    def motion(self,steps,initial=(0.,0.,5.),safe_z=5.):
        position=list(initial);moves=[]
        for kind,end,feed,operation in steps:
            end=list(end)
            moves.append({'kind':kind,'start':position,'end':end,
                          'feed_mm_min':feed,'operation':operation})
            position=end
        return {'initial_position':list(initial),'final_position':position,
                'safe_z':safe_z,'moves':moves}

    def replay(self,motion,spindle=8000.):
        program,mapping=render(motion,spindle,'roughing_then_cutout')
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'modal.nc';path.write_text(program,encoding='ascii')
            report=verify_readback(path,motion,mapping,spindle)
            summary,parsed=audit(path)
        rows=program.splitlines()
        blocks=[dict(WORD.findall(rows[line-1])) for line in mapping]
        self.assertEqual(report['status'],'passed')
        self.assertEqual(len(mapping),len(motion['moves']))
        self.assertEqual(len(parsed),len(mapping)+2)
        self.assertEqual(mapping,sorted(set(mapping)))
        self.assertLessEqual(report['maximum_coordinate_error_mm'],COORD_ERROR)
        self.assertLessEqual(max(map(len,rows)),79)
        self.assertFalse(summary['assumptions'])
        self.assertTrue(all(set(block)&set('XYZ') for block in blocks))
        replayed={move.line:move for move in parsed}
        for source,line in zip(motion['moves'],mapping):
            move=replayed[line]
            self.assertEqual(move.end,[float(f'{value:.5f}') for value in source['end']])
            self.assertEqual(move.spindle,round(spindle,5))
        return program,blocks,summary,[replayed[line] for line in mapping],report

    def test_modal_axes_modes_feeds_and_operation_boundaries_replay(self):
        motion=self.motion([
            ('clearance_adjust',(0,0,6),None,'roughing'),
            ('travel',(2,0,6),None,'roughing'),
            ('approach_rapid',(2,0,1),None,'roughing'),
            ('plunge',(2,0,-1),120,'roughing'),
            ('cut',(3,0,-1),600,'roughing'),
            ('cut',(3,2,-1),600,'roughing'),
            ('cut',(5,2,-1),700,'roughing'),
            ('cut',(5,3,-1),700,'cutout'),
            ('retract',(5,3,6),None,'cutout'),
            ('travel',(6,3,6),None,'cutout'),
            ('plunge',(6,3,-1),700,'cutout'),
            ('retract',(6,3,6),None,'cutout'),
        ])
        program,blocks,summary,moves,report=self.replay(motion)
        self.assertEqual([set(block)&set('XYZ') for block in blocks],
                         [{'Z'},{'X'},{'Z'},{'Z'},{'X'},{'Y'},
                          {'X'},{'Y'},{'Z'},{'X'},{'Z'},{'Z'}])
        self.assertEqual([index for index,block in enumerate(blocks) if 'G' in block],
                         [0,3,7,8,10,11])
        self.assertEqual([index for index,block in enumerate(blocks) if 'F' in block],[3,4,6])
        self.assertEqual([move.mode for move in moves],[0,0,0,1,1,1,1,1,0,0,1,0])
        self.assertEqual(summary['feedrates_mm_min'],[120,600,700])
        self.assertEqual(report['center_plunge_moves_replayed'],2)
        self.assertEqual([comment['text'] for comment in summary['comments']
                          if comment['text'].startswith('OP ')],['OP ROUGHING','OP CUTOUT'])
        # Startup positioning remains explicit before the spindle is enabled.
        startup=program.split('(OP ROUGHING)',1)[0].splitlines()
        self.assertEqual(startup[4:],['G21','G90','G94','G17','G40','G49','G54','M5',
                                     'G0 Z5.00000','G0 X0.00000 Y0.00000','S8000.00000 M3'])
        self.assertEqual([event['code'] for event in summary['events']],['M5','M3','M5','M2'])

    def test_rounded_zero_length_moves_keep_mapping_and_feed_changes(self):
        motion=self.motion([
            ('cut',(1.000001,-.000001,5),600.000001,'roughing'),
            ('cut',(1.000002,-.000002,5),600.000004,'roughing'),
            ('cut',(1.000004,-.000004,5),600.000006,'roughing'),
            ('cut',(1.000006,-.000006,5),600.000007,'roughing'),
            ('travel',(1.000008,-.000008,5),None,'roughing'),
            ('cut',(1.000009,-.000009,5),600.000014,'roughing'),
            ('cut',(1.000011,-.000011,5),600.000016,'cutout'),
        ])
        program,blocks,_,moves,report=self.replay(motion,spindle=8000.000004)
        self.assertEqual([index for index,block in enumerate(blocks) if 'F' in block],[0,2,6])
        self.assertEqual([move.feed for move in moves],
                         [600,600,600.00001,600.00001,600.00001,600.00001,600.00002])
        self.assertEqual([move.length for move in moves][1:3],[0,0])
        self.assertEqual(moves[4].length,0)
        self.assertEqual(moves[5].length,0)
        self.assertEqual(blocks[-1]['G'],'1')
        self.assertNotIn('-0.00000',program)
        self.assertLessEqual(report['maximum_feed_error_mm_min'],.0000050001)

    def test_invalid_modal_feed_is_still_rejected(self):
        for feed in (0.,1e-9,float('nan'),float('inf')):
            with self.subTest(feed=feed),self.assertRaises(ValueError):
                render(self.motion([('cut',(1,0,5),feed,'roughing')]),8000,'roughing_then_cutout')

    def test_line_limit_is_still_enforced(self):
        # Each axis changes, so all three words must fit on the emitted block.
        motion=self.motion([('cut',(1e25,2e25,3e25),600,'roughing')])
        with self.assertRaisesRegex(ValueError,'79 caracteres'):
            render(motion,8000,'roughing_then_cutout')


if __name__=='__main__':unittest.main()
