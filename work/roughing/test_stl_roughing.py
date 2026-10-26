"""Real OpenCAMLib/Clipper2 integration checked against analytic geometry."""
import math
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import subprocess
import numpy as np

from mesh_geometry import read_binary_stl
from stl_roughing import generate_stl_roughing,contact_paths
from region_core import offset


def rect(x0,y0,x1,y1):return [[x0,y0],[x1,y0],[x1,y1],[x0,y1]]


def plane(z_function=lambda x,y:-5,x0=-20,x1=20,y0=-20,y1=20):
    points=[[x0,y0,z_function(x0,y0)],[x1,y0,z_function(x1,y0)],
            [x1,y1,z_function(x1,y1)],[x0,y1,z_function(x0,y1)]]
    return np.array([[points[0],points[1],points[2]],[points[0],points[2],points[3]]],float)


def box():
    top=plane(lambda x,y:0,x0=-10,x1=10,y0=-10,y1=10)
    bottom=plane(lambda x,y:-4,x0=-10,x1=10,y0=-10,y1=10)[:,::-1]
    side=[]
    for i in range(4):
        xy=rect(-10,-10,10,10);a=xy[i];b=xy[(i+1)%4]
        side.extend([[[*a,-4],[*b,-4],[*b,0]],[[*a,-4],[*b,0],[*a,0]]])
    return np.concatenate([top,bottom,np.array(side)])


def all_edges(result):
    for layer in result['layers']:
        for poly in layer['polylines']:
            for a,b in zip(poly['points'],poly['points'][1:]):
                yield layer,a,b


class STLRoughingTests(unittest.TestCase):
    def job(self,triangles,**kwargs):
        options=dict(diameter=1,tool_length=10,stepdown=2,stepover=.8,
                     sampling=.2,z_top=0,z_bottom=-5,
                     boundaries=[rect(-5,-3,5,3)])
        options.update(kwargs)
        return generate_stl_roughing(triangles,**options)

    def test_flat_plane_depths_and_contact(self):
        result=self.job(plane())
        expected=[-5/3,-10/3,-5]
        self.assertEqual(result['layer_count'],3)
        self.assertEqual(result['active_layer_count'],3)
        self.assertGreater(result['cutting_edges'],0)
        for layer,a,b in all_edges(result):
            self.assertAlmostEqual(a[2],expected[layer['index']])
            self.assertAlmostEqual(b[2],expected[layer['index']])
            self.assertGreaterEqual(a[2],-5)

    def test_sloped_plane_whole_edges_clear_analytic_tool_envelope(self):
        result=self.job(plane(lambda x,y:-5+.2*x),z_bottom=-8,radial_allowance=.2,axial_allowance=.1)
        self.assertEqual(result['active_layer_count'],3)
        saw_variable_z=False
        for layer,a,b in all_edges(result):
            saw_variable_z|=abs(a[2]-b[2])>1e-8
            self.assertLessEqual(abs(a[2]-layer['upper_z']),2+1e-8)
            # For an infinite plane z=.2x-5, a flat circular cutter's exact
            # contact height is .2x-5 + effective_radius*.2.
            for fraction in (0,.25,.5,.75,1):
                p=np.array(a)*(1-fraction)+np.array(b)*fraction
                required=.2*p[0]-5+(1/2+.2)*.2+.1
                self.assertGreaterEqual(p[2]+1e-8,required)
        self.assertTrue(saw_variable_z)

    def test_thin_ridge_between_probes_is_not_missed(self):
        triangles=np.concatenate([plane(lambda x,y:-4),
                                  plane(lambda x,y:-.1,x0=.45,x1=.55,y0=-3,y1=3)])
        result=self.job(triangles,diameter=.2,sampling=1,stepover=.5,z_bottom=-4,
                        boundaries=[rect(0,-1,1,1)])
        self.assertEqual(result['active_layer_count'],1)
        self.assertGreater(result['cutting_edges'],0)
        for _,a,b in all_edges(result):
            self.assertGreaterEqual(min(a[2],b[2]),-.10000001)

    def test_existing_top_surface_generates_no_air_cut(self):
        result=self.job(box(),z_bottom=-4)
        self.assertGreater(result['contact_samples'],0)
        self.assertEqual(result['cutting_edges'],0)

    def test_physical_keepout_holds_in_every_generated_layer(self):
        result=self.job(plane(),exclusions=[rect(-1,-1,1,1)])
        self.assertGreater(result['cutting_edges'],0)
        for _,a,b in all_edges(result):
            self.assertAlmostEqual(a[1],b[1])
            left,right=sorted([a[0],b[0]])
            dx=max(-1-right,left-1,0);dy=max(-1-a[1],a[1]-1,0)
            self.assertGreaterEqual(math.hypot(dx,dy),.5)

    def test_full_exclusion_skips_native_contact(self):
        result=self.job(plane(),exclusions=[rect(-100,-100,100,100)])
        self.assertEqual(result['contact_samples'],0)
        self.assertEqual(result['polyline_count'],0)

    def test_contact_timeout_has_actionable_error(self):
        segments=[{'start':[0,0],'end':[1,0]}]
        with patch('stl_roughing.subprocess.run',side_effect=subprocess.TimeoutExpired('node',60)):
            with self.assertRaisesRegex(RuntimeError,'contato.*60 segundos'):
                contact_paths(plane(),segments,diameter=1,length=10,sampling=.2,floor=-10)

    def test_contact_rejects_empty_or_incomplete_bridge_output(self):
        segments=[{'start':[0,0],'end':[1,0]}]
        for output in (b'',b'{}',b'{"paths":[],"samples":0}'):
            with self.subTest(output=output),patch('stl_roughing.subprocess.run',
                    return_value=subprocess.CompletedProcess('node',0,stdout=output,stderr=b'')):
                with self.assertRaisesRegex(RuntimeError,'resposta de contato inv'):
                    contact_paths(plane(),segments,diameter=1,length=10,sampling=.2,floor=-10)

    def test_axial_allowance_stops_above_plane(self):
        result=self.job(plane(),axial_allowance=.3)
        last=result['layers'][-1]
        self.assertTrue(last['polylines'])
        for poly in last['polylines']:
            for p in poly['points']:self.assertAlmostEqual(p[2],-4.7)

    def test_binary_stl_alignment_and_corrupt_size(self):
        triangles=plane()
        data=bytes(80)+struct.pack('<I',len(triangles))
        for triangle in triangles:
            data+=struct.pack('<12fH',0,0,1,*triangle.ravel(),0)
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'plane.stl';file.write_bytes(data)
            mesh=read_binary_stl(file,rotation=[[1,0,0],[0,-1,0],[0,0,-1]],translation=[1,2,3])
            np.testing.assert_allclose(mesh.triangles,triangles*[1,-1,-1]+[1,2,3])
            file.write_bytes(data[:-1])
            with self.assertRaises(ValueError):read_binary_stl(file)

    def test_round_offset_resolution_is_in_millimeters(self):
        rounded=offset([np.array(rect(0,0,10,10),float)],1)[0]
        self.assertLess(len(rounded),500)
        midpoints=(rounded+np.roll(rounded,-1,axis=0))/2
        quadrant=midpoints[(midpoints[:,0]>=10)&(midpoints[:,1]>=10)]
        self.assertGreater(len(quadrant),0)
        radii=np.linalg.norm(quadrant-[10,10],axis=1)
        self.assertGreaterEqual(float(radii.min()),1-.00101)
        self.assertLessEqual(float(radii.max()),1.000002)


if __name__=='__main__':unittest.main()
