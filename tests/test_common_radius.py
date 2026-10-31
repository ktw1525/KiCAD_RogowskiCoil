import importlib.util
import math
from pathlib import Path
import unittest

SPEC=importlib.util.spec_from_file_location('radius_geometry',Path(__file__).resolve().parents[1]/'Src/plugins/geometry.py')
geometry=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(geometry)


class CommonRadiusTests(unittest.TestCase):
    def assert_series(self,result):
        for net in ('A','B'):
            graph={}
            def node(p,layer): return (round(p[0],6),round(p[1],6),layer)
            def edge(a,b):
                graph.setdefault(a,set()).add(b)
                graph.setdefault(b,set()).add(a)
            for t in result['tracks']:
                if t['net']==net: edge(node(t['a'],t['layer']),node(t['b'],t['layer']))
            for v in result['vias']:
                if v['net']==net: edge(node(v['p'],'F'),node(v['p'],'B'))
            self.assertEqual(sum(len(q)==1 for q in graph.values()),2)
            self.assertTrue(all(len(q)<=2 for q in graph.values()))
            seen=set();pending=[next(iter(graph))]
            while pending:
                p=pending.pop()
                if p in seen: continue
                seen.add(p);pending.extend(graph[p]-seen)
            self.assertEqual(len(seen),len(graph))

    def test_actual_half_and_quarter_circles_share_requested_radius(self):
        for p in ({},dict(turns=36,ri1=2.4),
                  dict(turns=64,hole=6,ri1=7,ri2=8,ro1=11,ro2=12,bend_radius=.45,rotation=37),
                  dict(turns=80,ri1=13,ri2=14,ro1=23,ro2=24,bend_radius=.55)):
            with self.subTest(p=p):
                result=geometry.build(p)
                requested=result['settings']['bend_radius'];groups={}
                for t in result['tracks']:
                    if 'bend_radius' not in t: continue
                    self.assertEqual(t['bend_radius'],requested)
                    for point in (t['a'],t['b']):
                        self.assertAlmostEqual(math.dist(point,t['bend_center']),requested,places=8)
                    key=(t['net'],t['layer'],t['bend_center'],t['bend_start'],t['bend_sweep'])
                    groups.setdefault(key,[]).append(t)
                self.assertTrue(groups)
                angles=set()
                for key,tracks in groups.items():
                    center=key[2]
                    sweep=0
                    for t in tracks:
                        a=math.atan2(t['a'][1]-center[1],t['a'][0]-center[0])
                        b=math.atan2(t['b'][1]-center[1],t['b'][0]-center[0])
                        sweep+=(b-a+math.pi)%(2*math.pi)-math.pi
                    self.assertAlmostEqual(sweep,key[-1],places=8)
                    angles.add(round(abs(math.degrees(sweep))))
                self.assertEqual(angles,{90,180})
                self.assert_series(result)

    def test_infeasible_radius_is_rejected_without_resizing(self):
        for p in (dict(bend_radius=.3),dict(turns=36),dict(bend_radius=1)):
            with self.subTest(p=p):
                with self.assertRaisesRegex(ValueError,'반경'):
                    geometry.build(p)

    def test_blue_inner_lead_has_horizontal_then_vertical_steps(self):
        for changes in ({},dict(turns=36,ri1=2.4),
                        dict(turns=64,hole=6,ri1=7,ri2=8,ro1=11,ro2=12,bend_radius=.45,rotation=37)):
            with self.subTest(changes=changes):
                p=dict(geometry.DEFAULTS,**changes)
                result=geometry.build(p)
                angle=math.radians(p['rotation'])
                def local(q):
                    x,y=q[0]-p['cx'],q[1]-p['cy']
                    return (x*math.cos(angle)+y*math.sin(angle),
                            -x*math.sin(angle)+y*math.cos(angle))
                top=[t for t in result['tracks'] if t.get('inner_lead_top')]
                half=[t for t in result['tracks'] if t.get('inner_lead_half')]
                bottom=[t for t in result['tracks'] if t.get('inner_lead_leg')=='lower']
                self.assertEqual(len(top),2)
                self.assertTrue(half)
                self.assertEqual(len(bottom),1)
                for t in top+half+bottom:
                    self.assertEqual((t['net'],t['layer']),('B','B'))
                self.assertAlmostEqual(local(top[0]['a'])[1],0,places=8)
                self.assertAlmostEqual(local(top[0]['b'])[1],0,places=8)
                self.assertAlmostEqual(local(top[1]['a'])[0],local(top[1]['b'])[0],places=8)
                self.assertEqual(top[0]['b'],top[1]['a'])
                self.assertEqual(top[1]['b'],half[0]['a'])
                self.assertEqual(half[-1]['b'],bottom[0]['a'])
                self.assertAlmostEqual(local(bottom[0]['a'])[0],local(bottom[0]['b'])[0],places=8)
                upper_length=math.dist(top[1]['a'],top[1]['b'])
                lower_length=math.dist(bottom[0]['a'],bottom[0]['b'])
                self.assertGreater(upper_length,0)
                self.assertAlmostEqual(upper_length,lower_length,places=8)
                self.assertAlmostEqual(local(half[0]['a'])[0],local(half[-1]['b'])[0],places=8)
                self.assertAlmostEqual(half[0]['bend_sweep'],math.pi)
                self.assert_series(result)

    def test_radius_zero_keeps_legacy_option(self):
        result=geometry.build(dict(bend_radius=0))
        self.assertFalse(any('bend_radius' in t for t in result['tracks']))


if __name__=='__main__':
    unittest.main()
