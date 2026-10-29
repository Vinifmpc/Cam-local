"""An already released part can be recut inside without an outside pass."""
import copy
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from audit_gcode import audit
from cam_operations import OperationSettings
from cam_project import RoughingSettings,create_project,calculate_project
from cam_tools import Tool
from cutout import generate_cutout
from grbl_post import export_grbl
from test_cam_setup import binary
from test_cutout import ring
from test_internal_cutouts import closed_plate


class InternalOnlyTests(unittest.TestCase):
    def generate(self,mesh=None,**changes):
        values=dict(diameter=1,tool_length=10,top=0,bottom=-3.2,stepdown=1,
                    contours='internal')
        values.update(changes)
        return generate_cutout(closed_plate(outer_radius=10,hole_radius=6,bottom=-3,vertices=48)
                               if mesh is None else mesh,**values)

    def test_internal_tracks_and_layers_match_all_without_any_exterior(self):
        inside=self.generate();all_tracks=self.generate(contours='all')
        self.assertEqual(inside['contours_selection'],'internal')
        self.assertEqual(inside['internal_contours_total'],1)
        self.assertEqual(inside['skipped_internal_contours'],0)
        self.assertTrue(inside['layers'])
        self.assertEqual(inside['contours'],[c for c in all_tracks['contours'] if c['kind']=='internal'])
        self.assertEqual(inside['layers'],[l for l in all_tracks['layers'] if l['contour_kind']=='internal'])
        self.assertEqual(inside['depth_levels'][-1]['z'],-3.2)
        for direction in ('climb','conventional'):
            job=self.generate(direction=direction,smoothing_mm=.01)
            self.assertTrue(all(c['kind']=='internal' for c in job['contours']))
            xy=np.concatenate([c['points_xy'] for c in job['contours']])
            self.assertLess(np.linalg.norm(xy,axis=1).max(),6)

    def test_multiple_parts_keep_all_internal_profiles_and_no_exteriors(self):
        job=self.generate(np.concatenate([ring(),ring()+[30,0,0]]))
        self.assertEqual([c['kind'] for c in job['contours']],['internal','internal'])
        self.assertEqual(job['internal_contours_total'],2)
        self.assertTrue(all(l['contour_kind']=='internal' for l in job['layers']))

    def test_no_internal_never_falls_back_to_external_and_small_tool_fit_fails(self):
        for floor in (-2,-3):
            with self.subTest(floor=floor),self.assertRaisesRegex(ValueError,'não tem contorno interno passante'):
                self.generate(closed_plate(floor=floor,bottom=-3))
        with self.assertRaisesRegex(ValueError,'estreito demais'):
            self.generate(diameter=13)
        with self.assertRaisesRegex(ValueError,'sem contorno selecionado'):
            self.generate(internal_indices=[])

    def test_internal_setting_roundtrips_and_smart_keeps_its_release_policy(self):
        o=OperationSettings(roughing_enabled=False,cutout_enabled=True,cutout_contours='internal')
        self.assertEqual(OperationSettings.from_dict(json.loads(json.dumps(asdict(o)))),o)
        self.assertEqual(o.sequence(),['cutout'])
        self.assertEqual(OperationSettings(machining_mode='smart',cutout_contours='internal').cutout_contours,'external')

    def test_translated_project_and_export_contain_only_inside_cuts(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);stl=root/'ring.stl';project=root/'project.json'
            center=np.array([25,35,-7.])
            binary(stl,closed_plate(outer_radius=10,hole_radius=6,bottom=-3,vertices=48)+center)
            tool=Tool(id='flat',name='Flat',diameter_mm=1,cutting_length_mm=10,
                      feed_mm_min=600,plunge_mm_min=120,spindle_rpm=8000)
            settings=RoughingSettings(stock_top_mm=-7,bottom_mm=-10,obstacle_top_mm=-7,
                                     stepdown_mm=1,stepover_mm=.5)
            options=OperationSettings(roughing_enabled=False,drill_enabled=False,cutout_enabled=True,
                       cutout_contours='internal',cutout_bottom_mm=-10.2,cutout_stepdown_mm=1)
            create_project(stl,project,units='mm',tool=tool,settings=settings,operations=options,
                           xy_origin='keep',z_origin='keep')
            result=calculate_project(project,include_motion=True)
            self.assertEqual(list(result['operations']),['cutout'])
            self.assertEqual([c['kind'] for c in result['cutout']['contours']],['internal'])
            for m in result['motion']['moves']:
                self.assertEqual(m['operation'],'cutout')
                if m['kind'] in ('cut','ramp','plunge'):
                    self.assertLessEqual(max(np.linalg.norm(np.array(p[:2])-center[:2])
                                             for p in (m['start'],m['end'])),6)
            report=export_grbl(result,project,root/'inside.nc')
            self.assertEqual(report['status'],'passed')
            _,moves=audit(root/'inside.nc',diameter=tool.diameter_mm)
            feeds=[m for m in moves if m.mode==1]
            self.assertTrue(feeds)
            self.assertAlmostEqual(min(m.end[2] for m in feeds),-10.2)
            self.assertTrue(all(np.linalg.norm(np.array(m.end[:2])-center[:2])<6 for m in feeds))
            # Export recomputes contour selection from the saved model instead
            # of accepting an injected exterior or changed selection metadata.
            for mutate in (
                lambda r:r['cutout'].update(contours_selection='all'),
                lambda r:r['cutout']['contours'].append({'kind':'external','points_xy':[[0,0],[1,0],[0,1]],'index':1})):
                forged=copy.deepcopy(result);mutate(forged)
                with self.assertRaisesRegex(ValueError,'Contornos do Cutout'):
                    export_grbl(forged,project,root/'bad.nc')
                self.assertFalse((root/'bad.nc').exists())


if __name__=='__main__':unittest.main()
