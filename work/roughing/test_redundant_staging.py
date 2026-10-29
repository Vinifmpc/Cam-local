import copy
import unittest
from depth_staging import stage_paths


def line(x0,x1,z=-1,y=0,kind='cleanup'):
    return {'kind':kind,'points':[[x0,y,z],[x1,y,z]],'closed':False}


class RedundantStagingTests(unittest.TestCase):
    def stage(self,paths,**kwargs):
        layers=[{'polylines':copy.deepcopy(paths)}];stats={}
        count=stage_paths(layers,diameter=1,stock_top=0,stepdown=1,
            prune_redundant=True,trim_redundant=True,stats=stats,**kwargs)
        return layers[0]['polylines'],stats,count

    def test_partial_auxiliary_removes_only_completed_identical_sweep(self):
        old=line(1,3)
        auxiliary={'kind':'preclear','points':[[0,0,-1],[1,0,-1],[3,0,-1],[4,0,-1]],'closed':False}
        paths,stats,_=self.stage([old,auxiliary])
        self.assertEqual([p['points'] for p in paths],[old['points'],[[0,0,-1],[1,0,-1]],[[3,0,-1],[4,0,-1]]])
        self.assertEqual(stats['redundant_edges_removed'],1)
        self.assertEqual(stats['redundant_cutting_length_mm'],2)
        self.assertEqual(stats['trimmed_preclear_paths'],1)
        self.assertEqual(stats['preclear_fragments_added'],1)

    def test_whole_cleanup_can_be_skipped_only_after_its_sweep_exists(self):
        original=line(0,4)
        paths,stats,_=self.stage([original,line(4,0)])
        self.assertEqual(len(paths),1)
        self.assertEqual(stats['redundant_paths_removed'],1)
        self.assertEqual(stats['redundant_raster_paths_removed'],0)
        self.assertEqual(paths[0],original)

    def test_deeper_and_offset_edges_are_not_removed(self):
        for auxiliary in [line(0,4,z=-1.5,kind='preclear'),line(0,4,y=.01,kind='preclear')]:
            paths,stats,_=self.stage([line(0,4),auxiliary])
            self.assertEqual(paths[-1],auxiliary)
            self.assertEqual(stats['redundant_edges_removed'],0)

    def test_partial_height_overlap_cannot_remove_a_whole_sloped_edge(self):
        auxiliary={'kind':'preclear','points':[[0,0,-1],[4,0,-1.5]],'closed':False}
        paths,stats,_=self.stage([line(0,4),auxiliary])
        self.assertEqual(paths[-1],auxiliary)
        self.assertEqual(stats['redundant_edges_removed'],0)

    def test_closed_loop_fragments_are_joined_only_at_original_common_vertex(self):
        original=line(1,3)
        auxiliary={'kind':'preclear','points':[[0,0,-1],[1,0,-1],[3,0,-1],[4,0,-1],[4,2,-1],[0,2,-1],[0,0,-1]],'closed':True}
        paths,stats,_=self.stage([original,auxiliary])
        self.assertEqual(len(paths),2)
        self.assertEqual(paths[-1]['points'],[[3,0,-1],[4,0,-1],[4,2,-1],[0,2,-1],[0,0,-1],[1,0,-1]])
        self.assertFalse(paths[-1]['closed'])
        self.assertEqual(stats['preclear_fragments_added'],0)

    def test_no_future_or_intra_path_edge_is_credited(self):
        auxiliary={'kind':'preclear','points':[[0,0,-1],[4,0,-1],[0,0,-1]],'closed':True}
        paths,stats,_=self.stage([auxiliary])
        self.assertEqual(paths,[auxiliary])
        self.assertEqual(stats['redundant_edges_removed'],0)

    def test_preparation_and_entry_bridge_provenance_are_preserved(self):
        for protected in [line(0,4,kind='preparation'),{**line(0,4,kind='preclear'),'entry_bridge':{'proof':'opaque'}}]:
            paths,stats,_=self.stage([line(0,4),protected])
            self.assertEqual(paths[-1],protected)
            self.assertEqual(stats['redundant_edges_removed'],0)

    def test_splitting_is_opt_in_and_does_not_mutate_inputs(self):
        auxiliary={'kind':'preclear','points':[[0,0,-1],[1,0,-1],[3,0,-1],[4,0,-1]],'closed':False}
        layers=[{'polylines':[line(1,3),auxiliary]}];before=copy.deepcopy(layers)
        stage_paths(layers,diameter=1,stock_top=0,stepdown=1,prune_redundant=True)
        self.assertEqual(layers,before)


if __name__=='__main__':unittest.main()
