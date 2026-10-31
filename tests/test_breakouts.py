"""Run with: python -m unittest discover -s tests"""
import importlib.util
import math
from pathlib import Path
import unittest

SPEC=importlib.util.spec_from_file_location('geometry',Path(__file__).resolve().parents[1]/'Src/plugins/geometry.py')
geometry=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(geometry)


class BreakoutTests(unittest.TestCase):
    def expected_point(self,source,p):
        scale=p['ro2']/geometry.REF_RADII[-1]
        a=math.radians(p['rotation'])
        return (p['cx']+scale*(source[0]*math.cos(a)-source[1]*math.sin(a)),
                p['cy']+scale*(source[0]*math.sin(a)+source[1]*math.cos(a)))

    def test_upper_breakout_anchors_remain_stable(self):
        for n in (12,24,32,36,40,64,80,96):
            for angle in (0,37):
                p=dict(geometry.DEFAULTS,turns=n,rotation=angle,cx=123,cy=89,
                       hole=6,ri1=7,ri2=8,ro1=11,ro2=12)
                for source in ((-6.905,0.1416),(-6.0227,-0.3847),(-6.035,0)):
                    self.assertLess(math.dist(geometry._breakout_point(source,p),
                                             self.expected_point(source,p)),1e-9)

    def test_lower_breakout_tracks_winding_row_and_rotates_together(self):
        for changes in ({},{'turns':24},{'turns':36,'ri1':2.4},{'turns':40,'ri1':2.7,'ri2':3.2},
                        dict(turns=64,hole=6,ri1=7,ri2=8,ro1=11,ro2=12),
                        dict(turns=64,hole=18,ri1=10,ri2=11,ro1=14,ro2=15,rotation=37),
                        dict(turns=80,ri1=13,ri2=14,ro1=23,ro2=24)):
            with self.subTest(changes=changes):
                p=dict(geometry.DEFAULTS,**changes)
                result=geometry.build(p)
                self.assertEqual(len(result['vias']),2*p['turns']+2)
                self.assertGreaterEqual(result['min_cross_net_gap_mm'],0)
                angle=math.radians(p['rotation'])
                def local(q):
                    x,y=q[0]-p['cx'],q[1]-p['cy']
                    return (x*math.cos(angle)+y*math.sin(angle),
                            -x*math.sin(angle)+y*math.cos(angle))
                via=next(v['p'] for v in result['vias'] if v['id']=='L16')
                vertical=[t for t in result['tracks'] if t['net']=='B' and t['layer']=='B'
                          and math.dist(t['a'],via)<1e-8]
                self.assertEqual(len(vertical),1)
                elbow=vertical[0]['b']
                self.assertAlmostEqual(local(via)[0],local(elbow)[0],places=8)
                self.assertGreater(local(via)[1],local(elbow)[1])
                row=geometry._base_breakout_point((-5.212,0.7455),p)
                self.assertAlmostEqual(local(elbow)[1],local(row)[1],places=8)
                for net,layer in (('A','F'),('B','B')):
                    horizontal=[t for t in result['tracks'] if t['net']==net and t['layer']==layer
                                and math.dist(t['a'],elbow)<1e-8 and math.dist(t['b'],row)<1e-8]
                    self.assertEqual(len(horizontal),1)
                lower_tip=[t['a'] for t in result['tracks'] if t['net']=='B' and t['layer']=='F'
                           and math.dist(t['b'],via)<1e-8]
                self.assertEqual(len(lower_tip),1)
                scale=p['ro2']/geometry.REF_RADII[-1]
                self.assertAlmostEqual(local(lower_tip[0])[0],-6.905*scale,places=8)
                self.assertAlmostEqual(local(via)[1]-local(lower_tip[0])[1],
                                       (1.2658-0.9916)*scale,places=8)

    def test_lower_via_moves_when_position_count_changes(self):
        p=dict(geometry.DEFAULTS,ri1=7,ri2=8,ro1=11,ro2=12)
        a=geometry._breakout_point((-5.9008,1.2658),dict(p,turns=32))
        b=geometry._breakout_point((-5.9008,1.2658),dict(p,turns=64))
        self.assertNotAlmostEqual(a[1],b[1])
        self.assertAlmostEqual(a[0],b[0])

    def test_36_position_turnaround_keeps_full_reference_cell(self):
        p=dict(geometry.DEFAULTS,turns=36,ri1=2.4)
        result=geometry.build(p)
        cells={}
        for t in result['tracks']:
            if 'cell_ports' in t: cells.setdefault(t['cell_ports'],[]).append(t)
        self.assertEqual(len(cells),34)
        turnarounds=[(ports,tracks) for ports,tracks in cells.items()
                     if abs(geometry._signed_step(*ports,38))==1]
        self.assertEqual(len(turnarounds),2)
        for (outer,inner),tracks in turnarounds:
            self.assertGreater(len(tracks),4)
            endpoints=[t[k] for t in tracks for k in ('a','b')]
            for slot,kind in ((outer,'O'),(inner,'I')):
                expected=geometry._target_via(slot,kind,36,p)
                self.assertLess(min(math.dist(q,expected) for q in endpoints),0.002)
        radial=[t for t in result['tracks'] if 'radial_cell' in t]
        self.assertEqual(len(radial),36)
        for t in radial:
            a=(t['a'][0]-p['cx'],t['a'][1]-p['cy'])
            b=(t['b'][0]-p['cx'],t['b'][1]-p['cy'])
            self.assertAlmostEqual(a[0]*b[1]-a[1]*b[0],0,places=7)

    def test_reference_breakout_is_preserved(self):
        result=geometry.build({})
        self.assertEqual(len(result['vias']),66)
        vias={v['id']:v['p'] for v in result['vias']}
        self.assertEqual(result['terminals']['A_IN'],vias['L17'])
        self.assertEqual(result['terminals']['B_IN'],vias['L16'])


if __name__=='__main__':
    unittest.main()
