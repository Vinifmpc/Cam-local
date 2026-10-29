import copy
import json
import math
from pathlib import Path
import unittest
import numpy as np
from drill import detect_circular_holes,generate_drill,inspect_drill_compatibility,validate_drill_motion


def plate(*,hole_radius=2.,outer_radius=10.,bottom=-5.,floor=None,vertices=64,center=(0,0)):
    """Closed annular cylinder, with an optional blind floor (analytic fixture)."""
    xy=lambda r,i:[center[0]+r*math.cos(2*math.pi*i/vertices),center[1]+r*math.sin(2*math.pi*i/vertices)]
    p=lambda r,i,z:[*xy(r,i),z]
    triangles=[]
    for i in range(vertices):
        j=(i+1)%vertices
        triangles.extend([[p(outer_radius,i,0),p(outer_radius,j,0),p(hole_radius,j,0)],
            [p(outer_radius,i,0),p(hole_radius,j,0),p(hole_radius,i,0)]])
        wall_floor=bottom if floor is None else floor
        for r,z0,z1 in ((outer_radius,bottom,0),(hole_radius,wall_floor,0)):
            triangles.extend([[p(r,i,z0),p(r,j,z0),p(r,j,z1)],[p(r,i,z0),p(r,j,z1),p(r,i,z1)]])
        if floor is None:
            triangles.extend([[p(outer_radius,i,bottom),p(hole_radius,i,bottom),p(hole_radius,j,bottom)],
                [p(outer_radius,i,bottom),p(hole_radius,j,bottom),p(outer_radius,j,bottom)]])
        else:
            triangles.append([[*center,bottom],p(outer_radius,j,bottom),p(outer_radius,i,bottom)])
            triangles.append([[*center,floor],p(hole_radius,i,floor),p(hole_radius,j,floor)])
    return np.asarray(triangles,float)


class DrillTests(unittest.TestCase):
    def generate(self,mesh=None,**kwargs):
        options=dict(diameter=1.,tool_length=10.,stock_top=0.,peck=.7,
            tolerance=.03,center_cutting=True,allow_helix=True)
        options.update(kwargs)
        return generate_drill(plate() if mesh is None else mesh,**options)

    def test_detects_through_circle_and_inscribed_diameter(self):
        report=detect_circular_holes(plate())
        self.assertEqual(len(report['holes']),1)
        hole=report['holes'][0]
        self.assertTrue(hole['through']);self.assertAlmostEqual(hole['bottom_z'],-5.)
        self.assertAlmostEqual(hole['opening_z'],0.)
        self.assertAlmostEqual(hole['diameter_mm'],4.,places=5)
        self.assertAlmostEqual(hole['safe_diameter_mm'],4.*math.cos(math.pi/64),places=5)
        json.dumps(report,allow_nan=False)

    def test_blind_floor_is_preserved_and_overdrill_rejected(self):
        mesh=plate(floor=-3.)
        report=detect_circular_holes(mesh);hole=report['holes'][0]
        self.assertFalse(hole['through']);self.assertEqual(hole['bottom_z'],-3.)
        job,plan=self.generate(mesh)
        self.assertGreaterEqual(min(m['end'][2] for m in plan['moves']),-3.)
        with self.assertRaisesRegex(ValueError,'cego'):self.generate(mesh,bottom=-3.1)
        self.assertEqual(job['holes'][0]['target_z'],-3.)

    def test_coplanar_floor_at_mesh_minimum_never_permits_breakthrough(self):
        # An STL can contain a zero-thickness bottom floor. It is still final
        # material, even though touching that plane is allowed for machining.
        mesh=plate(floor=-5.)
        hole=detect_circular_holes(mesh)['holes'][0]
        self.assertEqual(hole['bottom_z'],-5.);self.assertFalse(hole['through'])
        self.generate(mesh,bottom=-5.)
        with self.assertRaisesRegex(ValueError,'cego'):self.generate(mesh,bottom=-5.1)

    def test_real_through_hole_allows_breakthrough_below_model_bottom(self):
        job,plan=self.generate(bottom=-5.1)
        self.assertTrue(job['holes'][0]['through'])
        self.assertAlmostEqual(min(m['end'][2] for m in plan['moves']),-5.1)

    def test_plunge_matching_fit_pecks_and_reentry(self):
        # Tool must fit the faceted STL, while matching within size tolerance.
        job,plan=self.generate(diameter=3.99,allow_helix=False,peck=.7)
        self.assertEqual(job['holes'][0]['strategy'],'plunge')
        cuts=[m for m in plan['moves'] if m['kind']=='cut']
        self.assertEqual(len(cuts),8)
        for m in cuts:
            self.assertEqual(m['start'][:2],m['end'][:2])
            self.assertLessEqual(m['start'][2]-m['end'][2],.7+1e-9)
        for a,b in zip(plan['moves'],plan['moves'][1:]):self.assertEqual(a['end'],b['start'])
        self.assertEqual(plan['final_position'][2],plan['safe_z'])

    def test_fast_reentry_uses_only_this_holes_previously_cut_depth(self):
        job,fast=self.generate(diameter=3.99,allow_helix=False,peck=.7,reentry_gap=.25)
        _,slow=self.generate(diameter=3.99,allow_helix=False,peck=.7,rapid_reentry=False)
        cuts=lambda plan:[(m['start'],m['end']) for m in plan['moves'] if m['kind']=='cut']
        self.assertEqual(cuts(fast),cuts(slow))
        floor=0.;rapid_count=0
        for move in fast['moves']:
            if move['kind']=='cut':floor=move['end'][2]
            if move['proof'].get('drill_phase')=='cleared_reentry':
                rapid_count+=1
                self.assertEqual(move['start'][:2],move['end'][:2])
                self.assertAlmostEqual(move['proof']['cleared_to_z'],floor)
                self.assertGreaterEqual(move['end'][2],floor+.25-1e-9)
        self.assertEqual(rapid_count,len(cuts(fast))-1)
        distance=lambda plan:sum(math.dist(m['start'],m['end']) for m in plan['moves'] if m['kind']=='approach')
        self.assertLess(distance(fast),distance(slow)/3)
        self.assertEqual(validate_drill_motion(fast,job,plate())['status'],'passed')
        forged=copy.deepcopy(fast)
        move=next(m for m in forged['moves'] if m['proof'].get('drill_phase')=='cleared_reentry')
        move['end'][2]=move['proof']['cleared_to_z']-.1
        with self.assertRaises(ValueError):validate_drill_motion(forged,job,plate())

    def test_short_retract_stays_vertical_but_leaves_every_hole_at_safe_height(self):
        first=plate();second=plate().copy();second[:,:,0]+=20
        mesh=np.concatenate([first,second])
        job,plan=self.generate(mesh,diameter=3.99,allow_helix=False,peck=.7,
            retract_mode='chip_break',retract_mm=.4,reentry_gap=.1)
        self.assertEqual(len(job['holes']),2)
        short=0
        for move in plan['moves']:
            if move['kind']=='retract' and move['end'][2]<plan['safe_z']-1e-9:
                short+=1;self.assertAlmostEqual(move['end'][2]-move['start'][2],.4)
                self.assertEqual(move['start'][:2],move['end'][:2])
            if move['kind']=='travel' and math.dist(move['start'][:2],move['end'][:2])>1e-9:
                self.assertGreaterEqual(min(move['start'][2],move['end'][2]),plan['safe_z'])
        self.assertEqual(short,14)
        self.assertEqual(plan['final_position'][2],plan['safe_z'])
        self.assertEqual(validate_drill_motion(plan,job,mesh)['status'],'passed')

    def test_retract_and_reentry_parameters_reject_invalid_values(self):
        for kwargs in ({'retract_mode':'auto'},{'retract_mm':0},{'reentry_gap':0},
                       {'reentry_gap':float('nan')},{'rapid_reentry':1},{'retract_mm':True}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):self.generate(**kwargs)

    def test_nominal_cutter_larger_than_stl_inradius_rejected(self):
        with self.assertRaisesRegex(ValueError,'mínimo'):self.generate(diameter=4.)
        with self.assertRaisesRegex(ValueError,'mínimo'):self.generate(diameter=5.)

    def test_facet_compensation_is_explicit_bounded_and_preserves_real_tool(self):
        with self.assertRaisesRegex(ValueError,'mínimo'):self.generate(diameter=4.,allow_helix=False)
        job,plan=self.generate(diameter=4.,allow_helix=False,compensate_facets=True)
        self.assertEqual(job['tool']['diameter'],4.)
        self.assertEqual(job['holes'][0]['basis'],'fitted_circle')
        self.assertLessEqual(job['holes'][0]['facet_allowance_mm'],.03)
        self.assertAlmostEqual(job['holes'][0]['machining_diameter_mm'],4.,places=6)
        self.assertEqual(job['holes'][0]['strategy'],'plunge')
        self.assertEqual(validate_drill_motion(plan,job,plate())['status'],'passed')
        # Even an oversize much smaller than .03 geometry tolerance is refused.
        with self.assertRaisesRegex(ValueError,'reconstruído'):
            self.generate(diameter=4.0001,compensate_facets=True)
        changed=copy.deepcopy(job);changed['parameters']['compensate_facets']=False
        with self.assertRaises(ValueError):validate_drill_motion(plan,changed,plate())
        report=inspect_drill_compatibility(plate(),diameter=4.,tool_length=10.,stock_top=0.,
            center_cutting=True,compensate_facets=True)
        self.assertEqual(report['eligible_count'],1)

    def test_facet_compensation_never_accepts_non_circular_or_excessive_facets(self):
        for n in (4,12):
            with self.assertRaisesRegex(ValueError,'nenhum furo'):
                self.generate(plate(vertices=n),compensate_facets=True)
        # Tiny float32 nominal roundoff has an explicit one-micron-of-a-mm
        # diameter allowance, independent of the much larger fit tolerance.
        self.generate(diameter=4.0000005,compensate_facets=True)
        with self.assertRaises(ValueError):self.generate(diameter=4.000002,compensate_facets=True)

    def test_compensated_helix_stays_within_fitted_radius(self):
        job,plan=self.generate(compensate_facets=True)
        fitted=job['holes'][0]['machining_diameter_mm']/2
        for move in plan['moves']:
            if move['kind']=='cut':
                for point in (move['start'],move['end']):
                    self.assertLessEqual(math.hypot(*point[:2])+.5,fitted+1e-8)

    def test_helix_opt_in_and_center_cutting_confirmation(self):
        with self.assertRaisesRegex(ValueError,'helicoidal'):self.generate(allow_helix=False)
        with self.assertRaisesRegex(ValueError,'central'):self.generate(center_cutting=False)
        report=inspect_drill_compatibility(plate(),diameter=1.,tool_length=10.,stock_top=0.,
            allow_helix=True,center_cutting=False)
        self.assertEqual(report['detected_count'],1);self.assertEqual(report['eligible_count'],0)
        self.assertIn('central',report['holes'][0]['reason'])

    def test_helix_clears_core_and_radial_layers_with_bounded_angle(self):
        job,plan=self.generate(diameter=1.,peck=.7)
        self.assertEqual(job['holes'][0]['strategy'],'helix')
        cut=[m for m in plan['moves'] if m['kind']=='cut']
        self.assertTrue(any(m['proof'].get('strategy')=='overlapping_radial_step' for m in cut))
        self.assertTrue(any(m['proof'].get('strategy')=='cleared_disk_return' for m in cut))
        radius=.5
        for move in cut:
            for p in (move['start'],move['end']):
                self.assertLessEqual(math.hypot(*p[:2])+radius,job['holes'][0]['safe_diameter_mm']/2+1e-8)
            if move['end'][2]<move['start'][2]-1e-10:
                angle=math.degrees(math.atan2(move['start'][2]-move['end'][2],math.dist(move['start'][:2],move['end'][:2])))
                self.assertLessEqual(angle,3.+1e-8)
        # Sample the bottom disk conservatively inside the tessellation error:
        # some cutter footprint of a full-depth edge must cover every point.
        bottom_edges=[m for m in cut if max(m['start'][2],m['end'][2])<-5.+1e-8]
        for x in np.linspace(-1.9,1.9,19):
            for y in np.linspace(-1.9,1.9,19):
                if math.hypot(x,y)>1.95:continue
                point=np.array([x,y]);distance=math.inf
                for move in bottom_edges:
                    a=np.array(move['start'][:2]);b=np.array(move['end'][:2]);d=b-a
                    t=float(np.clip((point-a)@d/(d@d),0,1)) if d@d else 0.
                    distance=min(distance,float(np.linalg.norm(point-(a+t*d))))
                self.assertLessEqual(distance,radius+1e-7)

    def test_external_initial_position_and_obstacle_clearance(self):
        _,plan=self.generate(obstacle_top=5.,initial_position=[-20.,10.,9.])
        self.assertEqual(plan['safe_z'],7.54)
        self.assertEqual(plan['moves'][0]['kind'],'clearance_adjust')
        for m in plan['moves']:
            if m['kind']=='travel':self.assertEqual(m['start'][2],7.54);self.assertEqual(m['end'][2],7.54)
        with self.assertRaisesRegex(ValueError,'segurança'):self.generate(initial_position=[0.,0.,1.])
        with self.assertRaisesRegex(ValueError,'comprimento'):self.generate(tool_length=2.)

    def test_export_replay_rejects_geometry_and_source_tampering(self):
        mesh=plate();job,plan=self.generate(mesh)
        self.assertEqual(validate_drill_motion(plan,job,mesh)['status'],'passed')
        for mutation in ('cut','safe','missing','source','tool'):
            other=copy.deepcopy(plan);source=copy.deepcopy(job)
            if mutation=='cut':next(m for m in other['moves'] if m['kind']=='cut')['end'][0]+=.01
            elif mutation=='safe':other['safe_z']-=.1
            elif mutation=='missing':other['moves'].pop()
            elif mutation=='source':source['holes'][0]['safe_diameter_mm']+=1.
            elif mutation=='tool':other['tool']['diameter']+=.1
            with self.assertRaises(ValueError,msg=mutation):validate_drill_motion(other,source,mesh)
        with self.assertRaises(ValueError):validate_drill_motion(plan,job,plate(floor=-2.))

    def test_square_and_coarse_polygon_are_not_circles(self):
        self.assertEqual(detect_circular_holes(plate(vertices=4))['holes'],[])
        self.assertEqual(detect_circular_holes(plate(vertices=12))['holes'],[])

    def test_material_island_inside_circular_shadow_blocks_deeper_drilling(self):
        # A floating horizontal obstruction creates an island nested in the
        # outer empty loop, not another negative loop. It must bound the floor.
        obstruction=[]
        for i in range(32):
            a=2*math.pi*i/32;b=2*math.pi*(i+1)/32
            obstruction.append([[0.,0.,-2.],[.4*math.cos(a),.4*math.sin(a),-2.],
                [.4*math.cos(b),.4*math.sin(b),-2.]])
        mesh=np.concatenate((plate(),np.asarray(obstruction)))
        holes=detect_circular_holes(mesh)['holes']
        self.assertEqual(len(holes),1)
        self.assertEqual(holes[0]['bottom_z'],-2.)
        self.assertFalse(holes[0]['through'])
        with self.assertRaisesRegex(ValueError,'cego'):self.generate(mesh,bottom=-5.)

    def test_material_island_tangent_to_hole_wall_is_never_missed(self):
        # Clipper keeps this triangle as a positive island whose first vertex
        # is exactly on the negative circular loop. Strict first-point tests
        # wrongly label the hole through despite the Z=-2 obstruction.
        triangle=np.asarray([[[2.,0.,-2.],[.5,.3,-2.],[.5,-.3,-2.]]])
        mesh=np.concatenate((plate(),triangle))
        holes=detect_circular_holes(mesh)['holes']
        self.assertEqual(len(holes),1);self.assertEqual(holes[0]['bottom_z'],-2.)
        self.assertFalse(holes[0]['through'])
        with self.assertRaisesRegex(ValueError,'cego'):self.generate(mesh,bottom=-5.)

    def test_island_with_all_vertices_on_wall_still_blocks_circular_disk(self):
        angles=[0,math.pi/2,math.pi]
        triangle=np.asarray([[[2*math.cos(a),2*math.sin(a),-2.] for a in angles]])
        mesh=np.concatenate((plate(),triangle))
        holes=detect_circular_holes(mesh)['holes']
        self.assertEqual(len(holes),1);self.assertEqual(holes[0]['bottom_z'],-2.)

    def test_translation_does_not_change_circle_fit(self):
        hole=detect_circular_holes(plate(center=(10000.,-20000.)))['holes'][0]
        np.testing.assert_allclose(hole['center'],[10000.,-20000.],atol=1e-6)

    def test_resource_and_numeric_guards(self):
        for kwargs in ({'peck':0},{'max_moves':20},{'tolerance':2.},{'diameter':True},
                       {'stock_top':-1.},{'entry_angle_deg':45.}):
            with self.assertRaises(ValueError,msg=kwargs):self.generate(**kwargs)
        with self.assertRaises(ValueError):detect_circular_holes(np.full((1,3,3),math.nan))


if __name__=='__main__':unittest.main()
