# -*- coding: utf-8 -*-
"""Lightweight live preview; does not modify the board or run the DRC check."""
import math
import wx

from . import geometry


HIGHLIGHT_HELP={
    'cx':'배치 중심 X: 코일 전체를 PCB의 가로 방향으로 이동합니다. 그림은 중심을 따라 자동 확대됩니다.',
    'cy':'배치 중심 Y: 코일 전체를 PCB의 세로 방향으로 이동합니다. 그림은 중심을 따라 자동 확대됩니다.',
    'turns':'권선 위치 수: 원주를 따라 배치되는 방사형 위치와 비아 개수를 조정합니다.',
    'hole':'중앙 홀 직경: 중앙 개구부 크기입니다. 홀 생성 옵션을 끄면 가이드만 표시합니다.',
    'ri1':'내측 1열 반경: 중심에서 안쪽 첫 번째 비아 열까지의 거리입니다.',
    'ri2':'내측 2열 반경: 중심에서 안쪽 두 번째 비아 열까지의 거리입니다.',
    'ro1':'외측 1열 반경: 중심에서 바깥쪽 첫 번째 비아 열까지의 거리입니다.',
    'ro2':'외측 2열 반경: 중심에서 바깥쪽 두 번째 비아 열까지의 거리입니다.',
    'width':'트랙 폭: 구리 배선의 굵기입니다. 위쪽에 배선 단면의 확대 개념도를 표시합니다.',
    'via':'비아 외경: 비아 구리 패드의 바깥 지름입니다. 확대도에서 바깥 원을 강조합니다.',
    'drill':'비아 드릴 직경: 비아 가운데 뚫는 구멍 크기입니다. 확대도에서 안쪽 원을 강조합니다.',
    'rotation':'회전: 배치 중심을 기준으로 패턴 전체를 회전합니다. 노란 선은 회전 방향입니다.',
    'bend_radius':'공통 반경: 비아 주변의 반원(180°)과 사분원(90°)에 같은 반경을 적용합니다. 직선 접속부도 함께 조정합니다. 공간 부족 시 검증 오류로 표시합니다.',
    'clearance':'비아 최소 이격: 비아 구리 가장자리 사이의 요구 간격입니다. 전체 배선 DRC 규칙과는 별도입니다.',
    'board_margin':'외곽 여유: 가장 바깥 구리에서 원형 보드 외곽까지의 여유입니다. 외곽선 옵션을 끄면 가이드만 표시합니다.',
}


def highlighted_vias(key,settings,vias):
    if key in ('turns','via','drill'): return vias
    if key not in ('ri1','ri2','ro1','ro2'): return []
    center=(settings['cx'],settings['cy'])
    return [v for v in vias if abs(math.dist(center,v['p'])-settings[key])<0.002]


def bend_sample(tracks):
    candidates=[]
    for a,b in zip(tracks,tracks[1:]):
        if a['net']!=b['net'] or a['layer']!=b['layer'] or math.dist(a['b'],b['a'])>1e-6: continue
        u=(a['b'][0]-a['a'][0],a['b'][1]-a['a'][1])
        v=(b['b'][0]-b['a'][0],b['b'][1]-b['a'][1])
        length=math.hypot(*u);other=math.hypot(*v)
        if not (1e-6<length<0.08 and 1e-6<other<0.08): continue
        angle=math.acos(max(-1,min(1,(u[0]*v[0]+u[1]*v[1])/(length*other))))
        if 0.001<angle<1: candidates.append((angle/(length+other),a))
    return max(candidates,key=lambda item:item[0])[1] if candidates else tracks[0]


def make_scene(settings, model):
    geometry.validate(settings)
    if settings['turns']==32:
        tracks,vias=geometry._source_edges(model,settings)
    else:
        tracks,vias=geometry._variable_edges(model,settings)
    radius=geometry.copper_radius(tracks,vias,settings,geometry.breakout_pads(settings))
    if settings['outline']: radius+=settings['board_margin']
    return tracks,vias,radius


class CoilPreview(wx.Panel):
    def __init__(self,parent,on_direction_selected=None):
        super().__init__(parent)
        self.SetMinSize((300,300))
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.scene=None
        self.primitives=[]
        self.pads=[]
        self.bridges=[]
        self.settings=None
        self.active_key=None
        self.zoom=1.0
        self.pan=(0.0,0.0)
        self.drag_position=None
        self.direction_selection=False
        self.direction_pointer=None
        self.on_direction_selected=on_direction_selected
        self.model=geometry.source_model()
        self.Bind(wx.EVT_PAINT,self.on_paint)
        self.Bind(wx.EVT_SIZE,self.on_size)
        self.Bind(wx.EVT_MOUSEWHEEL,self.on_wheel)
        self.Bind(wx.EVT_LEFT_DOWN,self.on_left_down)
        self.Bind(wx.EVT_LEFT_UP,self.on_left_up)
        self.Bind(wx.EVT_MOTION,self.on_motion)
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST,self.on_capture_lost)
        self.Bind(wx.EVT_LEFT_DCLICK,self.reset_view)
        self.SetToolTip('휠: 확대·축소 / 왼쪽 드래그: 이동 / 더블 클릭: 전체 보기\n인출 방향 선택 버튼을 누른 뒤 원하는 방향을 클릭하세요.')

    def set_direction_selection(self,enabled):
        self.end_drag()
        self.direction_selection=bool(enabled)
        self.direction_pointer=None
        self.SetCursor(wx.Cursor(wx.CURSOR_CROSS) if enabled else wx.NullCursor)
        self.Refresh()

    def direction_at(self,position):
        if self.scene is None: return None
        _,origin,_=self.view_transform()
        dx,dy=position[0]-origin[0],position[1]-origin[1]
        if math.hypot(dx,dy)<self.FromDIP(12): return None
        # Reference breakout points left. Screen/PCB Y increases downward.
        return (math.degrees(math.atan2(dy,dx))-180.0)%360.0

    def view_transform(self):
        width,height=self.GetClientSize()
        top=90 if self.active_key in ('width','via','drill','clearance','bend_radius') else 0
        extent=self.scene[2]
        if self.active_key=='board_margin' and not self.settings['outline']:
            extent+=self.settings['board_margin']
        scale=max(1,min(width,height-top)-32)/(2*extent)*self.zoom
        return scale,(width/2+self.pan[0],(height+top)/2+self.pan[1]),extent

    def reset_view(self,event=None):
        self.end_drag()
        self.zoom=1.0
        self.pan=(0.0,0.0)
        self.Refresh()

    def on_wheel(self,event):
        if self.scene is None or event.GetWheelAxis()!=wx.MOUSE_WHEEL_VERTICAL:
            event.Skip()
            return
        old_zoom=self.zoom
        self.zoom=max(0.25,min(64.0,old_zoom*1.2**(event.GetWheelRotation()/event.GetWheelDelta())))
        factor=self.zoom/old_zoom
        # Keep the model point under the cursor stationary while zooming.
        _,origin,_=self.view_transform()
        x,y=event.GetPosition()
        self.pan=(self.pan[0]+(x-origin[0])*(1-factor),
                  self.pan[1]+(y-origin[1])*(1-factor))
        self.Refresh()

    def on_left_down(self,event):
        if self.scene is None: return
        if self.direction_selection:
            angle=self.direction_at(event.GetPosition())
            if angle is None: return
            self.set_direction_selection(False)
            if self.on_direction_selected is not None:
                self.on_direction_selected(angle)
            else:
                self.update(dict(self.settings,rotation=angle))
            return
        self.drag_position=tuple(event.GetPosition())
        if not self.HasCapture(): self.CaptureMouse()
        self.SetCursor(wx.Cursor(wx.CURSOR_SIZING))

    def end_drag(self):
        self.drag_position=None
        if self.HasCapture(): self.ReleaseMouse()
        self.SetCursor(wx.Cursor(wx.CURSOR_CROSS) if self.direction_selection else wx.NullCursor)

    def on_left_up(self,event):
        self.end_drag()

    def on_capture_lost(self,event):
        self.drag_position=None
        self.SetCursor(wx.Cursor(wx.CURSOR_CROSS) if self.direction_selection else wx.NullCursor)

    def on_motion(self,event):
        if self.direction_selection:
            self.direction_pointer=tuple(event.GetPosition())
            self.Refresh()
            return
        if self.drag_position is None:
            event.Skip()
            return
        if not event.LeftIsDown():
            self.end_drag()
            return
        x,y=event.GetPosition()
        self.pan=(self.pan[0]+x-self.drag_position[0],self.pan[1]+y-self.drag_position[1])
        self.drag_position=(x,y)
        self.Refresh()

    def on_size(self,event):
        self.Refresh()
        event.Skip()

    def update(self,settings):
        # Drop stale geometry if the edited inputs are incomplete or invalid.
        self.scene=None
        self.Refresh()
        self.scene=make_scene(settings,self.model)
        self.settings=dict(settings)
        self.primitives=geometry.copper_primitives(self.scene[0])
        self.pads=geometry.breakout_pads(settings)
        self.bridges=geometry.terminal_bridges(settings)

    def clear(self):
        self.set_direction_selection(False)
        self.scene=None
        self.Refresh()

    def highlight(self,key):
        self.active_key=key
        self.Refresh()

    def highlight_help(self):
        return HIGHLIGHT_HELP.get(self.active_key,'')

    def on_paint(self,event):
        dc=wx.AutoBufferedPaintDC(self)
        self.draw(dc)

    def draw(self,dc):
        """Render to a window DC or a memory DC for visual verification."""
        dc.SetBackground(wx.Brush('#17212b'))
        dc.Clear()
        if self.scene is None: return
        gc=wx.GraphicsContext.Create(dc)
        if gc is None: return
        width,height=self.GetClientSize()
        tracks,vias,radius=self.scene
        p=self.settings
        key=self.active_key
        detail=key in ('width','via','drill','clearance','bend_radius')
        # Reserve space for the optional outline guide when the option is off.
        scale,origin,extent=self.view_transform()
        def point(q):
            return (origin[0]+(q[0]-p['cx'])*scale,
                    origin[1]+(q[1]-p['cy'])*scale)
        def circle(q,r):
            x,y=point(q)
            gc.DrawEllipse(x-r*scale,y-r*scale,2*r*scale,2*r*scale)
        center=(p['cx'],p['cy'])
        gc.SetBrush(wx.TRANSPARENT_BRUSH)
        if p['outline']:
            gc.SetPen(wx.Pen('#cbd5e1',1))
            circle(center,radius)
        for layer in ('B','F'):
            color=geometry.layer_color(geometry.selected_layers(p)[layer])
            gc.SetPen(wx.Pen(color,max(1,round(p['width']*scale))))
            path=gc.CreatePath()
            for t in self.primitives:
                if t['layer']!=layer: continue
                path.MoveToPoint(*point(t['a']))
                if t['kind']=='arc':
                    center1,r,start,sweep=t['arc']
                    x,y=point(center1)
                    path.AddArc(x,y,r*scale,start,start+sweep,sweep>0)
                else: path.AddLineToPoint(*point(t['b']))
            for bridge in self.bridges:
                if bridge['layer']!=layer: continue
                path.MoveToPoint(*point(bridge['a']));path.AddLineToPoint(*point(bridge['b']))
            gc.StrokePath(path)
            gc.SetBrush(wx.Brush(color))
            for pad in self.pads:
                if pad['layer']!=layer: continue
                corners=geometry.pad_corners(pad)
                path=gc.CreatePath();path.MoveToPoint(*point(corners[0]))
                for q in corners[1:]: path.AddLineToPoint(*point(q))
                path.CloseSubpath();gc.FillPath(path)
            gc.SetBrush(wx.TRANSPARENT_BRUSH)
        gc.SetPen(wx.Pen('#e8c56a',1))
        gc.SetBrush(wx.Brush('#e8c56a'))
        for v in vias: circle(v['p'],p['via']/2)
        gc.SetPen(wx.Pen('#17212b',1))
        gc.SetBrush(wx.Brush('#17212b'))
        for v in vias: circle(v['p'],p['drill']/2)
        if p['center_hole']:
            gc.SetPen(wx.Pen('#cbd5e1',1))
            gc.SetBrush(wx.Brush('#f1f5f9'))
            circle(center,p['hole']/2)
        if self.direction_selection:
            angle=self.direction_at(self.direction_pointer) if self.direction_pointer is not None else None
            if angle is None: angle=p['rotation']
            theta=math.radians(angle+180)
            a=point(center);length=extent*scale
            tip=(a[0]+length*math.cos(theta),a[1]+length*math.sin(theta))
            gc.SetBrush(wx.TRANSPARENT_BRUSH)
            gc.SetPen(wx.Pen('#ffe066',2,wx.PENSTYLE_SHORT_DASH))
            path=gc.CreatePath();path.MoveToPoint(*a);path.AddLineToPoint(*tip);gc.StrokePath(path)
            gc.SetPen(wx.Pen('#ffe066',2));gc.DrawEllipse(tip[0]-7,tip[1]-7,14,14)
        if key is None: return
        gold='#ffe066'
        gc.SetBrush(wx.TRANSPARENT_BRUSH)
        gc.SetPen(wx.Pen(gold,3))
        def line(a,b):
            path=gc.CreatePath();path.MoveToPoint(*a);path.AddLineToPoint(*b);gc.StrokePath(path)
        selected=highlighted_vias(key,p,vias)
        for v in selected:
            circle(v['p'],p['drill']/2 if key=='drill' else p['via']/2)
        if key in ('ri1','ri2','ro1','ro2','hole','board_margin'):
            if key=='hole': r=p['hole']/2
            elif key=='board_margin': r=extent
            else: r=p[key]
            gc.SetPen(wx.Pen(gold,2,wx.PENSTYLE_SHORT_DASH))
            circle(center,r)
            gc.SetPen(wx.Pen(gold,2))
            a=point(center)
            if key=='hole': line((a[0]-r*scale,a[1]),(a[0]+r*scale,a[1]))
            elif key=='board_margin':
                copper=radius-p['board_margin'] if p['outline'] else radius
                line((a[0],a[1]-copper*scale),(a[0],a[1]-r*scale))
            else: line(a,point(selected[0]['p']) if selected else (a[0]+r*scale,a[1]))
        if key in ('cx','cy','rotation'):
            a=point(center)
            if key=='rotation':
                theta=math.radians(p['rotation'])
                end=(a[0]+p['ro2']*scale*math.cos(theta),a[1]+p['ro2']*scale*math.sin(theta))
                line(a,end)
                gc.DrawEllipse(a[0]-10,a[1]-10,20,20)
            else:
                delta=(45,0) if key=='cx' else (0,45)
                line((a[0]-delta[0],a[1]-delta[1]),(a[0]+delta[0],a[1]+delta[1]))
                gc.DrawEllipse(a[0]-5,a[1]-5,10,10)
        if key in ('width','bend_radius'):
            chosen={}
            if key=='bend_radius':
                for t in tracks:
                    if 'bend_sweep' in t:
                        kind=round(abs(math.degrees(t['bend_sweep'])))
                        if kind not in chosen: chosen[kind]=t
            if chosen:
                for sample in chosen.values():
                    gc.SetPen(wx.Pen(gold,3))
                    for t in tracks:
                        if (t.get('bend_center'),t.get('bend_start'),t.get('bend_sweep'))==(
                                sample['bend_center'],sample['bend_start'],sample['bend_sweep']):
                            line(point(t['a']),point(t['b']))
                    gc.SetPen(wx.Pen(gold,2));line(point(sample['bend_center']),point(sample['a']))
            else:
                sample=max(tracks,key=lambda t:math.dist(t['a'],t['b'])) if key=='width' else bend_sample(tracks)
                a,b=point(sample['a']),point(sample['b'])
                gc.SetPen(wx.Pen(gold,5));line(a,b)
                gc.SetPen(wx.Pen(gold,2));gc.DrawEllipse(a[0]-10,a[1]-10,20,20)
        if key=='clearance':
            # Use the closest actual pair, rather than arbitrary vias.
            a,b=min(((a,b) for i,a in enumerate(vias) for b in vias[i+1:]),
                    key=lambda pair:math.dist(pair[0]['p'],pair[1]['p']))
            for v in (a,b): circle(v['p'],p['via']/2)
            line(point(a['p']),point(b['p']))
        if detail:
            # Dimension schematic, deliberately magnified independently of the coil.
            gc.SetPen(wx.Pen('#aab6c4',2))
            if key in ('via','drill'):
                x,y=width-50,42
                outer=25;inner=max(2,outer*p['drill']/p['via'])
                gc.SetPen(wx.Pen(gold if key=='via' else '#aab6c4',3))
                gc.DrawEllipse(x-outer,y-outer,2*outer,2*outer)
                gc.SetPen(wx.Pen(gold if key=='drill' else '#aab6c4',3))
                gc.DrawEllipse(x-inner,y-inner,2*inner,2*inner)
            elif key=='width':
                gc.SetPen(wx.Pen(gold,16));line((width-110,42),(width-20,42))
            elif key=='clearance':
                gc.SetPen(wx.Pen(gold,2))
                gc.DrawEllipse(width-115,22,40,40);gc.DrawEllipse(width-55,22,40,40)
                line((width-75,42),(width-55,42))
            else:
                gc.SetPen(wx.Pen(gold,3))
                path=gc.CreatePath();path.AddArc(width-55,55,30,-math.pi/2,0,True);gc.StrokePath(path)
                gc.SetPen(wx.Pen(gold,1));line((width-55,55),(width-55,25))
            gc.Flush()
            dc.SetTextForeground(wx.Colour(gold))
            dc.DrawText('확대 개념도 · %g mm'%p[key],12,16)
