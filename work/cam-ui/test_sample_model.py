import tempfile
from pathlib import Path
import unittest
import numpy as np

from sample_model import pocket_plate_stl
from server import App
from mesh_geometry import place_stl,topology_report


class SampleModelTests(unittest.TestCase):
    def test_generated_plate_is_closed_and_has_the_expected_pocket_volume(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'sample.stl';path.write_bytes(pocket_plate_stl())
            mesh=place_stl(path,units='mm');triangles=mesh.triangles
            self.assertEqual(mesh.summary()['bounds_mm']['size'],[20,20,5])
            self.assertTrue(topology_report(mesh)['closed_consistent_edges'])
            volume=np.sum(np.einsum('ij,ij->i',triangles[:,0],np.cross(triangles[:,1],triangles[:,2])))/6
            self.assertAlmostEqual(volume,1800)
            self.assertEqual(path.read_bytes(),pocket_plate_stl())

    def test_optional_demo_uses_no_saved_user_model_and_requires_calculation(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary);app=App(folder/'uploads',folder/'projects')
            try:
                scene=app.demo()
                self.assertEqual(scene['mesh']['bounds_mm']['size'],[20,20,5])
                self.assertIsNone(scene['motion']);self.assertFalse(scene['approximate_regions'])
                self.assertNotIn('project_id',scene);self.assertEqual(app.saved,{})
                request={key:scene[key] for key in ('asset','placement','tool','settings','operations','notes')}
                identifier,path=app.prepare(request)
                from cam_project import calculate_project
                from grbl_post import export_grbl
                result=calculate_project(path,include_motion=True)
                self.assertGreater(len(result['operations']['roughing']['moves']),0)
                self.assertGreater(len(result['operations']['cutout']['moves']),0)
                self.assertEqual(export_grbl(result,path,folder/'sample.nc')['status'],'passed')
            finally:app.shutdown()


if __name__=='__main__':unittest.main()
