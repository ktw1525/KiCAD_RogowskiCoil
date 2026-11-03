"""Regression checks; run with KiCad's Python to include native wx rendering."""
import importlib
import math
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock


ROOT=Path(__file__).resolve().parents[1]
# Load the modules without __init__.py registering a KiCad action plugin.
package=types.ModuleType('coil_test_plugins')
package.__path__=[str(ROOT/'Src'/'plugins')]
sys.modules[package.__name__]=package
geometry=importlib.import_module(package.__name__+'.geometry')
try:
    import wx
    preview=importlib.import_module(package.__name__+'.preview')
except ImportError:
    wx=None
try:
    import pcbnew
    action=importlib.import_module(package.__name__+'.rogowski_action')
except ImportError:
    pcbnew=None


class GeometryTests(unittest.TestCase):
    def test_split_outer_bend_and_connector_become_circles(self):
        model=geometry.source_model()
        component=next(c for c in model['components']
                       if c['layer']=='F' and set(c['ports'])=={'O29','I33'})
        sources=geometry._merge_split_arcs(component['paths'])
        self.assertEqual(len(sources),5)
        # The single remaining straight is the radial spoke, not the detour.
        self.assertEqual(sum(len(path)==2 for path in sources),1)
        p=dict(geometry.DEFAULTS,cx=0,cy=0)
        records=geometry._component_paths(component,model,p,
            lambda q:geometry._transform_point(q,p),
            lambda v:geometry._target_via(int(v['id'][1:]),v['id'][0],32,p))
        bends=[(points,meta) for points,meta in records if 'bend_radius' in meta]
        self.assertEqual(sorted(round(abs(math.degrees(meta['bend_sweep'])))
                                for _,meta in bends),[90,180])
        for points,meta in bends:
            for q in points:
                self.assertAlmostEqual(math.dist(q,meta['bend_center']),p['bend_radius'],places=8)
        # Every join in this winding is still connected after moving endpoints.
        nodes={}
        for points,_ in records:
            for q in (points[0],points[-1]):
                key=tuple(round(x,6) for x in q)
                nodes[key]=nodes.get(key,0)+1
        self.assertEqual(sorted(nodes.values()).count(1),2)
        self.assertTrue(all(degree in (1,2) for degree in nodes.values()))

    def test_compatibility_mode_keeps_source_detour(self):
        model=geometry.source_model()
        component=next(c for c in model['components']
                       if c['layer']=='F' and set(c['ports'])=={'O29','I33'})
        p=dict(geometry.DEFAULTS,bend_radius=0)
        records=geometry._component_paths(component,model,p,
            lambda q:geometry._transform_point(q,p),
            lambda v:geometry._target_via(int(v['id'][1:]),v['id'][0],32,p))
        self.assertEqual(len(records),len(component['paths']))
        self.assertFalse(any('bend_radius' in meta for _,meta in records))

    def test_counts_rotation_and_copper_isolation(self):
        for n,scale in ((24,1),(32,1),(40,1.5)):
            for rotation in (0,37):
                with self.subTest(turns=n,rotation=rotation):
                    p=dict(geometry.DEFAULTS,turns=n,rotation=rotation)
                    for key in ('ri1','ri2','ro1','ro2'): p[key]*=scale
                    result=geometry.build(p)
                    self.assertEqual(len(result['vias']),2*n+2)
                    self.assertGreater(result['min_cross_net_gap_mm'],0)
                    self.assert_connected(result)

    def assert_connected(self,result):
        # Through vias connect layers; track joins connect within each layer.
        for net in ('A','B'):
            graph={}
            def key(q,layer): return (round(q[0],6),round(q[1],6),layer)
            def edge(a,b):
                graph.setdefault(a,set()).add(b);graph.setdefault(b,set()).add(a)
            for t in result['tracks']:
                if t['net']==net: edge(key(t['a'],t['layer']),key(t['b'],t['layer']))
            for v in result['vias']:
                if v['net']==net: edge(key(v['p'],'F'),key(v['p'],'B'))
            seen=set();pending=[next(iter(graph))]
            while pending:
                q=pending.pop()
                if q in seen: continue
                seen.add(q);pending.extend(graph[q]-seen)
            self.assertEqual(len(seen),len(graph),'Disconnected winding '+net)


class MouseEvent:
    def __init__(self,x,y,rotation=120,left=True):
        self.position=(x,y);self.rotation=rotation;self.left=left;self.skipped=False
    def GetPosition(self): return self.position
    def GetWheelRotation(self): return self.rotation
    def GetWheelDelta(self): return 120
    def GetWheelAxis(self): return wx.MOUSE_WHEEL_VERTICAL
    def LeftIsDown(self): return self.left
    def Skip(self): self.skipped=True


@unittest.skipIf(wx is None,'Requires wxPython (included with KiCad)')
class PreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=wx.App(False)

    def setUp(self):
        self.frame=wx.Frame(None,size=(700,700))
        self.panel=preview.CoilPreview(self.frame)
        self.frame.Show();self.app.Yield()
        self.panel.update(dict(geometry.DEFAULTS,center_hole=True))

    def tearDown(self):
        self.panel.end_drag();self.frame.Destroy();self.app.Yield()

    def test_cursor_anchor_zoom_limits_and_reset(self):
        cursor=(470,180)
        def model_point():
            scale,origin,_=self.panel.view_transform()
            return tuple((cursor[i]-origin[i])/scale for i in (0,1))
        initial=model_point()
        self.panel.on_wheel(MouseEvent(*cursor))
        self.assertAlmostEqual(self.panel.zoom,1.2)
        for a,b in zip(initial,model_point()): self.assertAlmostEqual(a,b)
        self.panel.on_wheel(MouseEvent(*cursor,rotation=-120))
        self.assertAlmostEqual(self.panel.zoom,1)
        for x in self.panel.pan: self.assertAlmostEqual(x,0)
        for rotation,limit in ((120,64),(-120,0.25)):
            for _ in range(60): self.panel.on_wheel(MouseEvent(*cursor,rotation=rotation))
            self.assertAlmostEqual(self.panel.zoom,limit)
        self.panel.reset_view()
        self.assertEqual((self.panel.zoom,self.panel.pan),(1,(0,0)))

    def test_drag_capture_release_and_scene_updates(self):
        self.panel.on_left_down(MouseEvent(100,100))
        self.assertTrue(self.panel.HasCapture())
        self.panel.on_motion(MouseEvent(160,125))
        self.assertEqual(self.panel.pan,(60,25))
        self.panel.on_left_up(MouseEvent(160,125))
        self.assertFalse(self.panel.HasCapture())
        self.assertIsNone(self.panel.drag_position)
        self.panel.on_wheel(MouseEvent(220,180))
        before=(self.panel.zoom,self.panel.pan)
        self.panel.update(dict(geometry.DEFAULTS,center_hole=True,rotation=37))
        self.assertEqual((self.panel.zoom,self.panel.pan),before)
        self.panel.on_left_down(MouseEvent(10,10))
        self.panel.clear()
        self.assertFalse(self.panel.HasCapture())
        event=MouseEvent(20,20)
        self.panel.on_wheel(event)
        self.assertTrue(event.skipped)

    def test_native_render_with_zoom_pan_and_highlights(self):
        self.panel.zoom=2
        self.panel.pan=(30,-15)
        bitmap=wx.Bitmap(700,700)
        dc=wx.MemoryDC(bitmap)
        for key in (None,'bend_radius','width','via','drill','clearance','board_margin','rotation'):
            self.panel.highlight(key)
            self.panel.draw(dc)
        dc.SelectObject(wx.NullBitmap)

    def test_pick_direction_uses_visible_center_after_zoom_and_pan(self):
        self.panel.zoom=2.5;self.panel.pan=(71,-34)
        self.panel.highlight('bend_radius')
        _,origin,_=self.panel.view_transform()
        selected=[];self.panel.on_direction_selected=selected.append
        before=(self.panel.zoom,self.panel.pan)
        for dx,dy,expected in ((-100,0,0),(0,-100,90),(100,0,180),(0,100,270),(100,100,225)):
            self.panel.set_direction_selection(True)
            event=MouseEvent(origin[0]+dx,origin[1]+dy)
            self.panel.on_motion(event)
            self.panel.on_left_down(event)
            self.assertAlmostEqual(selected[-1],expected)
            self.assertFalse(self.panel.direction_selection)
            self.assertFalse(self.panel.HasCapture())
            self.assertEqual((self.panel.zoom,self.panel.pan),before)

    def test_direction_center_click_is_ignored_and_standalone_preview_rotates(self):
        _,origin,_=self.panel.view_transform()
        self.panel.set_direction_selection(True)
        self.panel.on_left_down(MouseEvent(*origin))
        self.assertTrue(self.panel.direction_selection)
        self.assertEqual(self.panel.settings['rotation'],0)
        bitmap=wx.Bitmap(700,700);dc=wx.MemoryDC(bitmap)
        self.panel.on_motion(MouseEvent(origin[0]+100,origin[1]))
        self.panel.draw(dc);dc.SelectObject(wx.NullBitmap)
        self.panel.on_left_down(MouseEvent(origin[0]+100,origin[1]))
        self.assertEqual(self.panel.settings['rotation'],180)
        self.panel.set_direction_selection(True);self.panel.clear()
        self.assertFalse(self.panel.direction_selection)
        self.assertIsNone(self.panel.direction_at(origin))


@unittest.skipIf(pcbnew is None,'Requires KiCad Python')
class NativeBoardTests(unittest.TestCase):
    def test_preview_direction_updates_rotation_model_and_validation(self):
        app=wx.GetApp() or wx.App(False)
        board=pcbnew.CreateEmptyBoard();board.SetCopperLayerCount(4)
        dialog=action.Parameters(None,4,board)
        try:
            dialog.center_hole.SetValue(False)
            dialog.layer_entries['layer_f'].SetStringSelection('In1.Cu')
            dialog.layer_entries['layer_b'].SetStringSelection('In2.Cu')
            dialog.preview.SetSize((600,600));dialog.update_preview()
            p=dialog.get_values();old=geometry.build(p)
            dialog.validated_values=dict(p);dialog.validated_geometry=old;dialog.generate_button.Enable()
            dialog.preview.zoom=1.8;dialog.preview.pan=(25,-12)
            view=(dialog.preview.zoom,dialog.preview.pan)
            dialog.direction_button.SetValue(True);dialog.toggle_direction_selection()
            _,origin,_=dialog.preview.view_transform()
            dialog.preview.on_left_down(MouseEvent(origin[0],origin[1]-120))
            chosen=dialog.get_values()
            self.assertEqual(chosen,dict(p,rotation=90))
            self.assertIsNone(dialog.validated_geometry)
            self.assertFalse(dialog.generate_button.IsEnabled())
            self.assertFalse(dialog.direction_button.GetValue())
            self.assertEqual((dialog.preview.zoom,dialog.preview.pan),view)
            model=geometry.build(chosen)
            self.assertEqual(dialog.preview.scene[0],model['tracks'])
            self.assertEqual(dialog.preview.scene[1],model['vias'])
            action.apply_geometry(board,model)
            vias={v.m_Uuid.AsString():v for v in board.GetTracks() if isinstance(v,pcbnew.PCB_VIA)}
            actual={(v.GetPosition().x,v.GetPosition().y) for v in vias.values()}
            self.assertEqual(actual,{(action.vec(v['p']).x,action.vec(v['p']).y) for v in model['vias']})
            self.assertIn('0.6.2',dialog.GetTitle())
        finally:
            dialog.preview_timer.Stop();dialog.Destroy();app.Yield()

    def test_native_arcs_pads_and_save_reload(self):
        for n,scale,rotation,radius in ((32,1,0,0.385),(24,1,37,0.385),
                                       (40,1.5,37,0.385),(32,1,23,0)):
            with self.subTest(turns=n,rotation=rotation,bend_radius=radius):
                p=dict(geometry.DEFAULTS,turns=n,rotation=rotation,
                       bend_radius=radius,center_hole=True,outline=True)
                for key in ('ri1','ri2','ro1','ro2'):p[key]*=scale
                g=geometry.build(p)
                board=pcbnew.CreateEmptyBoard()
                action.apply_geometry(board,g)
                tracks=[t for t in board.GetTracks() if not isinstance(t,pcbnew.PCB_VIA)]
                self.assertEqual(len(tracks),len(g['primitives']))
                arcs=[t for t in tracks if isinstance(t,pcbnew.PCB_ARC)]
                self.assertEqual(len(arcs),sum(t['kind']=='arc' for t in g['primitives']))
                self.assertGreater(len(arcs),0)
                # Verify real 90/180 degree PCB_ARC objects with the requested radius.
                if radius:
                    bends=[t for t in arcs if abs(pcbnew.ToMM(t.GetRadius())-radius)<0.00001]
                    self.assertTrue(any(abs(abs(t.GetAngle().AsDegrees())-90)<0.002 for t in bends))
                    self.assertTrue(any(abs(abs(t.GetAngle().AsDegrees())-180)<0.002 for t in bends))
                self.assert_native_pads(board,g)
                group=board.ResolveItem(pcbnew.KIID(g['focus_uuid']),True)
                self.assertIsNotNone(group)
                native_group=next(group for group in board.Groups() if group.m_Uuid.AsString()==g['focus_uuid'])
                self.assertEqual(len(native_group.GetItems()),len(g['primitives'])+len(g['vias'])+4)
                with tempfile.TemporaryDirectory() as directory:
                    filename=str(Path(directory)/'coil.kicad_pcb')
                    self.assertTrue(pcbnew.SaveBoard(filename,board,True))
                    text=Path(filename).read_text(encoding='utf-8')
                    self.assertEqual(text.count('\n\t(arc\n'),len(arcs))
                    loaded=pcbnew.LoadBoard(filename)
                    self.assertEqual(sum(isinstance(t,pcbnew.PCB_ARC) for t in loaded.GetTracks()),len(arcs))
                    self.assert_native_pads(loaded,g)

    def assert_native_pads(self,board,g):
        pads=[pad for footprint in board.GetFootprints() for pad in footprint.Pads()]
        self.assertEqual(len(pads),4)
        self.assertEqual({p.GetNumber() for p in pads},{'1','2','3','4'})
        for spec in g['pads']:
            obj=next(p for p in pads if p.GetNumber()==spec['number'])
            layer=pcbnew.F_Cu if spec['layer']=='F' else pcbnew.B_Cu
            opposite=pcbnew.B_Cu if spec['layer']=='F' else pcbnew.F_Cu
            self.assertTrue(obj.IsOnLayer(layer));self.assertFalse(obj.IsOnLayer(opposite))
            self.assertEqual(obj.GetAttribute(),pcbnew.PAD_ATTRIB_SMD)
            self.assertEqual(obj.GetNetname(),g['settings']['net_a' if spec['net']=='A' else 'net_b'])
            self.assertLessEqual(math.dist((pcbnew.ToMM(obj.GetPosition().x),
                                          pcbnew.ToMM(obj.GetPosition().y)),spec['p']),0.000002)
            self.assertAlmostEqual(obj.GetSize().x,action.mm(spec['size']),delta=1)
            self.assertAlmostEqual(geometry._normalize(obj.GetOrientationDegrees()+spec['rotation']),0,places=5)
        for a,b in (('1','3'),('2','4')):
            self.assertEqual(next(p.GetPosition() for p in pads if p.GetNumber()==a),
                             next(p.GetPosition() for p in pads if p.GetNumber()==b))

    def test_focus_resolves_generated_group_after_canvas_rebuild(self):
        g=geometry.build(dict(geometry.DEFAULTS,center_hole=True))
        board=pcbnew.CreateEmptyBoard();action.apply_geometry(board,g)
        with mock.patch.object(pcbnew,'GetBoard',return_value=board), \
                mock.patch.object(pcbnew,'Refresh') as refresh, \
                mock.patch.object(pcbnew,'FocusOnItem') as focus:
            action.focus_generated_coil(g['focus_uuid'])
            refresh.assert_called_once()
            self.assertEqual(len(focus.call_args_list),2)
            self.assertEqual(focus.call_args_list[0].args[0].m_Uuid.AsString(),g['focus_uuid'])
            self.assertEqual(focus.call_args_list[0].args[1],pcbnew.F_Cu)
            self.assertIsNone(focus.call_args_list[1].args[0])
            focus.reset_mock()
            action.focus_generated_coil(pcbnew.KIID().AsString())
            focus.assert_not_called()


    def test_selected_nets_and_bottom_bridge_survive_reload(self):
        board=pcbnew.CreateEmptyBoard()
        existing=action.get_net(board,'SENSOR_P')
        unrelated=action.get_net(board,'OTHER')
        g=geometry.build(dict(geometry.DEFAULTS,center_hole=True,
                              net_a='SENSOR_P',net_b='SENSOR_N'))
        action.apply_geometry(board,g)
        self.assertEqual(board.FindNet('SENSOR_P').GetNetCode(),existing.GetNetCode())
        self.assertEqual(board.FindNet('OTHER').GetNetCode(),unrelated.GetNetCode())
        self.assertIsNone(board.FindNet('ROGOWSKI_A'))
        self.assertIsNone(board.FindNet('ROGOWSKI_B'))
        self.assertEqual({t.GetNetname() for t in board.GetTracks()},{'SENSOR_P','SENSOR_N'})
        with tempfile.TemporaryDirectory() as directory:
            filename=str(Path(directory)/'selected_nets.kicad_pcb')
            self.assertTrue(pcbnew.SaveBoard(filename,board,True))
            loaded=pcbnew.LoadBoard(filename)
            self.assert_native_pads(loaded,g)
            footprint=next(footprint for footprint in loaded.GetFootprints() if footprint.IsNetTie())
            self.assertTrue(footprint.IsNetTie())
            copper=list(footprint.GraphicalItems())
            self.assertEqual(len(copper),1)
            self.assertEqual(copper[0].GetLayer(),pcbnew.B_Cu)
            self.assertEqual(copper[0].GetShape(),pcbnew.SHAPE_T_SEGMENT)
            pads={p.GetNumber():p for p in footprint.Pads()}
            tied={p.GetNumber() for p in footprint.GetNetTiePads(pads['3'])}
            self.assertIn('4',tied);self.assertNotIn('1',tied);self.assertNotIn('2',tied)
            self.assertEqual(copper[0].GetStart(),pads['3'].GetPosition())
            self.assertEqual(copper[0].GetEnd(),pads['4'].GetPosition())
            self.assertGreater(copper[0].GetWidth(),0)
            self.assertEqual(footprint.GetLayer(),pcbnew.B_Cu)

    def test_net_controls_select_existing_and_invalidate_validation(self):
        app=wx.GetApp() or wx.App(False)
        board=pcbnew.CreateEmptyBoard()
        action.get_net(board,'SENSOR_P');action.get_net(board,'SENSOR_N')
        dialog=action.Parameters(None,2,board)
        try:
            self.assertIn('SENSOR_P',dialog.net_entries['net_a'].GetStrings())
            dialog.net_entries['net_a'].SetValue('SENSOR_P')
            dialog.net_entries['net_b'].SetValue('SENSOR_N')
            settings=dialog.get_values()
            self.assertEqual((settings['net_a'],settings['net_b']),('SENSOR_P','SENSOR_N'))
            g=geometry.build(settings)
            dialog.validated_values=dict(settings);dialog.validated_geometry=g
            self.assertIs(dialog.get_validated_geometry(),g)
            dialog.net_entries['net_b'].SetValue('NEW_SIGNAL')
            with self.assertRaises(ValueError):dialog.get_validated_geometry()
            self.assertIsNone(dialog.validated_geometry)
            dialog.net_entries['net_b'].SetValue(' ')
            with self.assertRaises(ValueError):dialog.get_values()
        finally:
            dialog.preview_timer.Stop();dialog.Destroy();app.Yield()


    def test_selected_layers_rectangles_and_vias_survive_reload(self):
        cases=((4,'In1.Cu','In2.Cu',pcbnew.VIATYPE_BURIED),
               (4,'F.Cu','In1.Cu',pcbnew.VIATYPE_BLIND),
               (4,'In2.Cu','B.Cu',pcbnew.VIATYPE_BLIND),
               (2,'B.Cu','F.Cu',pcbnew.VIATYPE_THROUGH),
               (6,'In2.Cu','In4.Cu',pcbnew.VIATYPE_BURIED))
        for count,first,second,via_type in cases:
            with self.subTest(layers=(first,second)):
                board=pcbnew.CreateEmptyBoard();board.SetCopperLayerCount(count)
                g=geometry.build(dict(geometry.DEFAULTS,center_hole=True,rotation=37,
                                      layer_f=first,layer_b=second))
                action.apply_geometry(board,g)
                with tempfile.TemporaryDirectory() as directory:
                    filename=str(Path(directory)/'layers.kicad_pcb')
                    self.assertTrue(pcbnew.SaveBoard(filename,board,True))
                    loaded=pcbnew.LoadBoard(filename)
                    mapping={key:getattr(pcbnew,name.replace('.','_')) for key,name in (('F',first),('B',second))}
                    tracks=list(loaded.GetTracks())
                    vias=[t for t in tracks if isinstance(t,pcbnew.PCB_VIA)]
                    self.assertEqual(len(vias),len(g['vias']))
                    stack=geometry.copper_layers(count)
                    ends=sorted((first,second),key=stack.index)
                    for via in vias:
                        self.assertEqual(via.GetViaType(),via_type)
                        self.assertEqual(via.TopLayer(),getattr(pcbnew,ends[0].replace('.','_')))
                        self.assertEqual(via.BottomLayer(),getattr(pcbnew,ends[1].replace('.','_')))
                    self.assertEqual({t.GetLayer() for t in tracks if not isinstance(t,pcbnew.PCB_VIA)},set(mapping.values()))
                    fps=list(loaded.GetFootprints())
                    pads=[pad for fp in fps for pad in fp.Pads()]
                    rectangles=[shape for shape in loaded.GetDrawings() if shape.GetShape()==pcbnew.SHAPE_T_POLY]
                    expected_inner=sum(spec['kind']=='rectangle' for spec in g['pads'])
                    self.assertEqual(len(rectangles),expected_inner)
                    self.assertEqual(len(pads),4-expected_inner)
                    for spec in g['pads']:
                        layer=mapping[spec['layer']]
                        if spec['kind']=='pad':
                            obj=next(pad for pad in pads if pad.GetNumber()==spec['number'])
                            self.assertTrue(obj.IsOnLayer(layer))
                            self.assertFalse(obj.IsOnLayer(pcbnew.B_Mask if layer==pcbnew.F_Cu else pcbnew.F_Mask))
                        else:
                            corners=geometry.pad_corners(spec)
                            x=min(q[0] for q in corners);y=min(q[1] for q in corners)
                            found=[r for r in rectangles if r.GetLayer()==layer and
                                   abs(pcbnew.ToMM(r.GetBoundingBox().GetX())-x)<0.000003 and
                                   abs(pcbnew.ToMM(r.GetBoundingBox().GetY())-y)<0.000003]
                            self.assertEqual(len(found),1)
                            self.assertTrue(found[0].IsSolidFill())
                            self.assertTrue(found[0].IsConnected())
                            self.assertEqual(found[0].GetWidth(),0)
                            self.assertEqual(found[0].GetNetname(),g['settings']['net_a' if spec['net']=='A' else 'net_b'])
                    bridge=[shape for fp in fps for shape in fp.GraphicalItems() if shape.GetShape()==pcbnew.SHAPE_T_SEGMENT]
                    bridge.extend(t for t in tracks if not isinstance(t,pcbnew.PCB_VIA) and
                                  t.GetStart()==action.vec(g['bridges'][0]['a']) and t.GetEnd()==action.vec(g['bridges'][0]['b']))
                    self.assertEqual(len(bridge),1)
                    self.assertEqual(bridge[0].GetLayer(),mapping['B'])
                    self.assertEqual(bridge[0].GetStart(),action.vec(g['bridges'][0]['a']))
                    self.assertEqual(bridge[0].GetEnd(),action.vec(g['bridges'][0]['b']))

    def test_layer_selection_rejects_same_or_unavailable_layers(self):
        app=wx.GetApp() or wx.App(False)
        board=pcbnew.CreateEmptyBoard();board.SetCopperLayerCount(4)
        dialog=action.Parameters(None,4,board)
        try:
            self.assertEqual(dialog.layer_entries['layer_f'].GetStrings(),['F.Cu','In1.Cu','In2.Cu','B.Cu'])
            dialog.layer_entries['layer_f'].SetStringSelection('In1.Cu')
            dialog.layer_entries['layer_b'].SetStringSelection('In2.Cu')
            p=dialog.get_values();g=geometry.build(p)
            dialog.validated_values=dict(p);dialog.validated_geometry=g
            dialog.layer_entries['layer_b'].SetStringSelection('B.Cu')
            with self.assertRaises(ValueError):dialog.get_validated_geometry()
            dialog.layer_entries['layer_b'].SetStringSelection('In1.Cu')
            with self.assertRaises(ValueError):dialog.get_values()
            with self.assertRaises(ValueError):geometry.build(dict(p,layer_b='In1.Cu'))
            board.SetCopperLayerCount(2)
            with self.assertRaises(ValueError):action.apply_geometry(board,g)
            self.assertEqual(len(list(board.GetTracks())),0)
            self.assertEqual(len(list(board.GetFootprints())),0)
        finally:
            dialog.preview_timer.Stop();dialog.Destroy();app.Yield()


if __name__=='__main__': unittest.main()
