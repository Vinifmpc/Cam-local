"""Import/catalogue contracts and a complete persisted setup -> native CAM run."""
from contextlib import redirect_stdout,redirect_stderr
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
import numpy as np

from cam_tools import Tool,ToolLibrary
from mesh_geometry import read_stl,place_stl,topology_report
from cam_project import RoughingSettings,create_project,load_project,calculate_project
from cam_setup import main


def binary(path,triangles,header=b''):
    data=header[:80].ljust(80,b'\0')+struct.pack('<I',len(triangles))
    for triangle in triangles:
        data+=struct.pack('<12fH',0,0,1,*np.asarray(triangle).ravel(),0)
    Path(path).write_bytes(data)


def ascii_stl(path,triangles):
    lines=['solid example']
    for triangle in triangles:
        lines.extend(['facet normal 0 0 1','outer loop'])
        lines.extend('vertex '+' '.join(str(float(v)) for v in p) for p in triangle)
        lines.extend(['endloop','endfacet'])
    lines.append('endsolid example')
    Path(path).write_text('\n'.join(lines),encoding='utf8')


def plane(z=-2):
    return np.array([[[-5,-5,z],[5,-5,z],[5,5,z]],[[-5,-5,z],[5,5,z],[-5,5,z]]],float)


class CAMSetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.stl=self.root/'part.stl'
        binary(self.stl,plane())
        self.tool=Tool(id='flat-1',name='Topo 1 mm',diameter_mm=1,cutting_length_mm=5)
        self.settings=RoughingSettings(stepdown_mm=1,stepover_mm=.8,stock_top_mm=0,bottom_mm=-2,
            boundaries_mm=[[[-2,-1],[2,-1],[2,1],[-2,1]]])

    def tearDown(self):
        self.tmp.cleanup()

    def test_ascii_binary_equivalence_and_solid_binary_header(self):
        text=self.root/'text.stl';ascii_stl(text,plane())
        binary(self.stl,plane(),header=b'solid misleading binary header')
        a=read_stl(text,units='mm');b=read_stl(self.stl,units='mm')
        np.testing.assert_array_equal(a.triangles,b.triangles)
        self.assertEqual(a.source_format,'ascii');self.assertEqual(b.source_format,'binary')

    def test_unit_conversion_does_not_scale_mm_translation(self):
        mesh=read_stl(self.stl,units='inch',translation=[1,2,3])
        np.testing.assert_allclose(mesh.triangles,plane()*25.4+[1,2,3])
        tool=Tool.from_units(id='inch',name='1/8',units='inch',diameter=.125,
                            cutting_length=1,feed=10,spindle_rpm=8000)
        self.assertAlmostEqual(tool.diameter_mm,3.175)
        self.assertAlmostEqual(tool.cutting_length_mm,25.4)
        self.assertEqual(tool.feed_mm_min,254)
        self.assertEqual(tool.spindle_rpm,8000)

    def test_rotate_anchor_and_translate_order(self):
        mesh=place_stl(self.stl,units='mm',rotation=[[1,0,0],[0,-1,0],[0,0,-1]],
                       xy_origin='minimum',z_origin='top',translation_mm=[10,20,-3])
        low=mesh.triangles.reshape(-1,3).min(axis=0)
        high=mesh.triangles.reshape(-1,3).max(axis=0)
        np.testing.assert_allclose(low,[10,20,-3]);np.testing.assert_allclose(high,[20,30,-3])
        reloaded=read_stl(self.stl,units='mm',rotation=mesh.rotation,translation=mesh.translation)
        np.testing.assert_array_equal(mesh.triangles,reloaded.triangles)

    def test_reject_reflection_scaling_or_unknown_units(self):
        for options in ({'rotation':[[1,0,0],[0,1,0],[0,0,-1]]},
                        {'rotation':[[2,0,0],[0,1,0],[0,0,1]]}, {'translation':[float('nan'),0,0]}):
            with self.subTest(options=options),self.assertRaises(ValueError):
                read_stl(self.stl,units='mm',**options)
        with self.assertRaises(ValueError):read_stl(self.stl,units='auto')

    def test_malformed_ascii_binary_nan_degenerate(self):
        cases=[b'solid x\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\n',
               self.stl.read_bytes()[:-1],b'solid x\nendsolid x\n']
        for data in cases:
            with self.subTest(data=data[:10]):
                self.stl.write_bytes(data)
                with self.assertRaises(ValueError):read_stl(self.stl,units='mm')
        for triangle in ([[[0,0,0],[1,1,1],[2,2,2]]],[[[0,0,0],[1,0,0],[0,float('nan'),0]]]):
            binary(self.stl,triangle)
            with self.assertRaises(ValueError):read_stl(self.stl,units='mm')

    def test_topology_distinguishes_open_closed_and_bad_winding(self):
        report=topology_report(read_stl(self.stl,units='mm'))
        self.assertEqual(report['boundary_edges'],4)
        self.assertFalse(report['closed_consistent_edges'])
        vertices=np.array([[0,0,0],[1,0,0],[0,1,0],[0,0,1]],float)
        faces=vertices[[[0,2,1],[0,1,3],[1,2,3],[2,0,3]]]
        binary(self.stl,faces)
        report=topology_report(read_stl(self.stl,units='mm'))
        self.assertTrue(report['closed_consistent_edges'])
        faces[0]=faces[0,::-1];binary(self.stl,faces)
        report=topology_report(read_stl(self.stl,units='mm'))
        self.assertEqual(report['inconsistent_winding_edges'],3)

    def test_catalogue_roundtrip_replace_and_duplicate_detection(self):
        library=ToolLibrary([self.tool]);path=self.root/'tools.json';library.save(path)
        loaded=ToolLibrary.load(path)
        self.assertEqual(loaded.get(self.tool.id),self.tool)
        with self.assertRaises(ValueError):loaded.add(self.tool)
        other=Tool(id=self.tool.id,name='Nova',diameter_mm=2,cutting_length_mm=10)
        loaded.add(other,replace=True);loaded.save(path)
        self.assertEqual(ToolLibrary.load(path).get(self.tool.id),other)
        data=loaded.as_dict();data['tools'].append(other.as_dict());path.write_text(json.dumps(data))
        with self.assertRaises(ValueError):ToolLibrary.load(path)

    def test_catalogue_invalid_dimensions_or_unimplemented_tip_rejected(self):
        for overrides in ({'diameter_mm':0},{'cutting_length_mm':-1},{'diameter_mm':True},
                          {'overall_length_mm':2},{'kind':'ball_end_mill'},
                          {'flutes':2.5},{'feed_mm_min':float('inf')}):
            with self.subTest(overrides=overrides),self.assertRaises(ValueError):
                Tool.from_dict({**self.tool.as_dict(),**overrides})

    def test_invalid_library_version_or_units_rejected(self):
        path=self.root/'tools.json';record=ToolLibrary([self.tool]).as_dict()
        for changes in ({'schema_version':2},{'units':'inch'}):
            path.write_text(json.dumps({**record,**changes}))
            with self.assertRaises(ValueError):ToolLibrary.load(path)

    def test_saved_project_relocation_snapshot_and_exact_geometry(self):
        project=self.root/'part.cam.json'
        create_project(self.stl,project,units='mm',tool=self.tool,settings=self.settings)
        moved=self.root/'moved';moved.mkdir()
        project.rename(moved/project.name);self.stl.rename(moved/self.stl.name)
        record,mesh,tool,settings,inspection=load_project(moved/project.name)
        np.testing.assert_array_equal(mesh.triangles,plane())
        self.assertEqual(tool,self.tool);self.assertEqual(settings,self.settings)
        self.assertEqual(record['source']['path'],'part.stl')
        self.assertEqual(inspection['limits']['stepover_percent'],80)

    def test_changed_stl_hash_rejected(self):
        project=self.root/'part.cam.json'
        create_project(self.stl,project,units='mm',tool=self.tool,settings=self.settings)
        binary(self.stl,plane(-1))
        with self.assertRaisesRegex(ValueError,'STL mudou'):load_project(project)

    def test_setup_checks_tool_reach_top_bottom_and_stepover(self):
        for overrides in ({'stock_top_mm':4},{'stock_top_mm':-3,'bottom_mm':-4},
                          {'bottom_mm':-3},{'stepover_mm':1.1}):
            with self.subTest(overrides=overrides),self.assertRaises(ValueError):
                settings=RoughingSettings.from_dict({**self.settings.__dict__,**overrides})
                create_project(self.stl,self.root/'bad.json',units='mm',tool=self.tool,settings=settings)
        self.assertFalse((self.root/'bad.json').exists())

    def test_settings_reject_bad_polygon_and_nan(self):
        for changes in ({'boundaries_mm':[[[0,0],[3,3],[0,2],[2,0]]]},
                        {'exclusions_mm':[[[0,0],[1,1],[2,2]]]},
                        {'sampling_mm':float('nan')},{'approach_gap_mm':10}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                RoughingSettings.from_dict({**self.settings.__dict__,**changes})

    def test_empty_boundaries_mean_no_cuts_not_unbounded(self):
        project=self.root/'none.json'
        settings=RoughingSettings.from_dict({**self.settings.__dict__,'boundaries_mm':[]})
        create_project(self.stl,project,units='mm',tool=self.tool,settings=settings)
        result=calculate_project(project,include_motion=True)
        self.assertEqual(result['roughing']['cutting_edges'],0)
        self.assertEqual(result['motion']['moves'],[])

    def test_persisted_setup_drives_real_native_contact_and_validated_ramps(self):
        project=self.root/'part.cam.json'
        create_project(self.stl,project,units='mm',tool=self.tool,settings=self.settings)
        result=calculate_project(project,include_motion=True)
        job=result['roughing'];motion=result['motion']
        self.assertGreater(job['cutting_edges'],0)
        self.assertEqual(job['tool']['diameter'],self.tool.diameter_mm)
        self.assertEqual(job['tool']['length'],self.tool.cutting_length_mm)
        self.assertEqual(job['tool_profile']['feed_mm_min'],None)
        self.assertAlmostEqual(job['contact_diameter'],1.2)
        self.assertEqual(motion['validation']['status'],'passed')
        self.assertEqual(motion['validation']['source_edges_preserved'],job['cutting_edges'])
        self.assertFalse(result['gcode_emitted'])

    def test_cli_create_list_inspect_prepare_check_calculate_and_protect_inputs(self):
        library=self.root/'tools.json';settings=self.root/'settings.json'
        settings.write_text(json.dumps(self.settings.__dict__))
        project=self.root/'cli.cam.json';result=self.root/'result.json'
        def call(args):
            with redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
                return main(args)
        self.assertEqual(call(['tool-add','--library',str(library),'--id','a','--name','A',
            '--units','mm','--diameter','1','--cutting-length','5']),0)
        self.assertEqual(call(['tool-list','--library',str(library)]),0)
        inspect=['inspect','--stl',str(self.stl),'--units','mm']
        original=self.stl.read_bytes()
        self.assertEqual(call(inspect+['--out',str(self.stl)]),2)
        self.assertEqual(self.stl.read_bytes(),original)
        prepare=['prepare','--stl',str(self.stl),'--units','mm','--library',str(library),
                 '--tool','a','--settings',str(settings)]
        self.assertEqual(call(prepare+['--out',str(library)]),2)
        self.assertEqual(call(prepare+['--out',str(project)]),0)
        self.assertEqual(call(['check','--project',str(project)]),0)
        self.assertEqual(call(['calculate','--project',str(project),'--out',str(self.stl)]),2)
        self.assertEqual(call(['calculate','--project',str(project),'--out',str(result),'--motion']),0)
        self.assertTrue(json.loads(result.read_text())['motion'])


if __name__=='__main__':unittest.main()
