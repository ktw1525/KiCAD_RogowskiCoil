# -*- coding: utf-8 -*-
"""KiCad 10 PCB Editor ActionPlugin for TI Gerber-derived Rogowski coil."""
import math
import os
import traceback

import pcbnew
import wx

from . import geometry


VALUES = [
    ('cx','배치 중심 X (mm)'),
    ('cy','배치 중심 Y (mm)'),
    ('turns','총 권선 위치 수 (4의 배수)'),
    ('hole','중앙 관통홀 직경 (mm)'),
    ('ri1','내측 비아 1열 반경 (mm)'),
    ('ri2','내측 비아 2열 반경 (mm)'),
    ('ro1','외측 비아 1열 반경 (mm)'),
    ('ro2','외측 비아 2열 반경 (mm)'),
    ('width','동박 트랙 폭 (mm)'),
    ('via','비아 패드 외경 (mm)'),
    ('drill','비아 드릴 직경 (mm)'),
    ('rotation','전체 패턴 회전 (°)'),
    ('clearance','비아 최소 이격 요구치 (mm)'),
    ('board_margin','옵션 외곽 여유 (mm)'),
]


class Parameters(wx.Dialog):
    def __init__(self, parent, copper_layers):
        super().__init__(parent, title='Rogowski TI Gerber Coil Generator v0.5.0',
                         size=(610,690), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.SetMinSize((490,410))
        root=wx.BoxSizer(wx.VERTICAL)
        heading=wx.StaticText(self,label='TI TIDA-010971 · 원본 2개 독립 권선 · 4열 교차 비아')
        root.Add(heading,0,wx.ALL,12)
        note=wx.StaticText(self,label='32위치: 원본 거버 배선 좌표 복원  |  그 외: 원본 곡선 변형 · 좌측 인출선 생략')
        note.Wrap(550)
        root.Add(note,0,wx.LEFT|wx.RIGHT|wx.BOTTOM,12)
        scroll=wx.ScrolledWindow(self,style=wx.VSCROLL|wx.TAB_TRAVERSAL)
        scroll.SetScrollRate(0,12)
        contents=wx.BoxSizer(wx.VERTICAL)
        fg=wx.FlexGridSizer(cols=2,vgap=7,hgap=12)
        fg.AddGrowableCol(1)
        self.entries={}
        for key,title in VALUES:
            fg.Add(wx.StaticText(scroll,label=title),0,wx.ALIGN_CENTER_VERTICAL)
            default=geometry.DEFAULTS[key]
            ent=wx.TextCtrl(scroll,value=str(default))
            self.entries[key]=ent
            fg.Add(ent,1,wx.EXPAND)
        contents.Add(fg,0,wx.ALL|wx.EXPAND,14)
        self.center_hole=wx.CheckBox(scroll,label='중앙 관통홀 생성 (Edge.Cuts, 비도금 개구부)')
        self.center_hole.SetValue(True)
        contents.Add(self.center_hole,0,wx.LEFT|wx.RIGHT|wx.BOTTOM,14)
        self.outline=wx.CheckBox(scroll,label='독립 시험 PCB 원형 외곽선 생성 (Edge.Cuts)')
        contents.Add(self.outline,0,wx.LEFT|wx.RIGHT|wx.BOTTOM,14)
        txt=wx.StaticText(scroll,label=('현재 PCB: %d층 구리 / 생성 배선: F.Cu 및 B.Cu만 사용\n'
                                        '원본 32: 좌측 두 권선의 인출 형상 포함, 패드는 직접 연결\n'
                                        '가변 N: 권선만 생성, A_IN/A_OUT/B_IN/B_OUT 비아에서 인출\n'
                                        '※ 2개 권선은 서로 다른 네트이며, 외부 차폐 및 보상 리턴은 미구현\n'
                                        '※ 원본의 가는 트랙/간격은 제조사 DRC 요구와 다를 수 있음')%copper_layers)
        contents.Add(txt,0,wx.LEFT|wx.RIGHT|wx.BOTTOM,14)
        scroll.SetSizer(contents)
        scroll.FitInside()
        root.Add(scroll,1,wx.EXPAND)
        root.Add(wx.StaticLine(self),0,wx.EXPAND)
        footer=wx.BoxSizer(wx.HORIZONTAL)
        footer.AddStretchSpacer(1)
        footer.Add(wx.Button(self,wx.ID_OK,'로고스키 코일 생성'),0,wx.RIGHT,8)
        footer.Add(wx.Button(self,wx.ID_CANCEL,'취소'))
        root.Add(footer,0,wx.ALL|wx.EXPAND,11)
        self.SetSizer(root)
        self.SetAffirmativeId(wx.ID_OK)
        self.SetEscapeId(wx.ID_CANCEL)
        self.Layout()

    def get_values(self):
        p={}
        for key,_ in VALUES:
            raw=self.entries[key].GetValue().strip()
            p[key]=int(raw) if key=='turns' else float(raw)
        p['outline']=bool(self.outline.GetValue())
        p['center_hole']=bool(self.center_hole.GetValue())
        if not all(math.isfinite(float(v)) for k,v in p.items() if isinstance(v,(int,float))):
            raise ValueError('숫자 필드에 무한대 또는 NaN 값이 포함되어 있습니다.')
        return p


def mm(value):
    return pcbnew.FromMM(float(value))


def vec(p):
    return pcbnew.VECTOR2I(mm(p[0]),mm(p[1]))


def get_net(board,name):
    net=board.FindNet(name)
    if net is None:
        net=pcbnew.NETINFO_ITEM(board,name)
        board.Add(net)
    return net


def apply_geometry(board,g):
    p=g['settings']
    nets={'A':get_net(board,'ROGOWSKI_A'),
          'B':get_net(board,'ROGOWSKI_B')}
    items=[]
    # Create all board objects in memory first. Add only after construction.
    for t in g['tracks']:
        line=pcbnew.PCB_TRACK(board)
        line.SetStart(vec(t['a']))
        line.SetEnd(vec(t['b']))
        line.SetWidth(mm(p['width']))
        line.SetLayer(pcbnew.F_Cu if t['layer']=='F' else pcbnew.B_Cu)
        line.SetNet(nets[t['net']])
        items.append(line)
    for v in g['vias']:
        obj=pcbnew.PCB_VIA(board)
        obj.SetPosition(vec(v['p']))
        obj.SetWidth(mm(p['via']))
        obj.SetDrill(mm(p['drill']))
        obj.SetViaType(pcbnew.VIATYPE_THROUGH)
        obj.SetLayerPair(pcbnew.F_Cu,pcbnew.B_Cu)
        obj.SetNet(nets[v['net']])
        items.append(obj)
    if p['outline'] or p['center_hole']:
        # Outline must encompass left breakout in reference mode.
        c=(p['cx'],p['cy'])
        circle_radii=[]
        if p['outline']:
            radius=max([math.dist(c,v['p'])+p['via']/2 for v in g['vias']]+[
                       math.dist(c,t[end])+p['width']/2
                       for t in g['tracks'] for end in ('a','b')]) +p['board_margin']
            circle_radii.append(radius)
        if p['center_hole']:circle_radii.append(p['hole']/2)
        for radius1 in circle_radii:
            sh=pcbnew.PCB_SHAPE(board)
            sh.SetShape(pcbnew.SHAPE_T_CIRCLE)
            sh.SetCenter(vec(c))
            sh.SetEnd(vec((c[0]+radius1,c[1])))
            sh.SetLayer(pcbnew.Edge_Cuts)
            sh.SetWidth(mm(0.05))
            items.append(sh)
    inserted=[]
    try:
        for item in items:
            board.Add(item)
            inserted.append(item)
    except Exception:
        for item in reversed(inserted):
            try: board.Remove(item)
            except Exception: pass
        raise
    return len(items)


class RogowskiAction(pcbnew.ActionPlugin):
    def defaults(self):
        self.name='Rogowski TI Gerber Coil Generator'
        self.category='PCB Generator'
        self.description='TI TIDA-010971 E2.0 reference GTL/GBL pattern + 2 nets, 2/4-layer'
        self.show_toolbar_button=True
        self.icon_file_name=os.path.join(os.path.dirname(__file__),'toolbar.png')

    def Run(self):
        board=pcbnew.GetBoard()
        if board is None:
            wx.MessageBox('PCB 파일을 먼저 여세요.','Rogowski',wx.OK|wx.ICON_ERROR)
            return
        if board.GetCopperLayerCount() not in (2,4):
            wx.MessageBox('2층 또는 4층 PCB에서 실행해야 합니다.','Rogowski',wx.OK|wx.ICON_ERROR)
            return
        dlg=Parameters(None,board.GetCopperLayerCount())
        try:
            if dlg.ShowModal()!=wx.ID_OK:return
            p=dlg.get_values()
            g=geometry.build(p)
            if p['outline']:
                if any(s.GetLayer()==pcbnew.Edge_Cuts for s in board.GetDrawings()):
                    raise ValueError('기존 Edge.Cuts 외곽선이 있습니다. 외곽선 생성 옵션을 끄고 실행하세요.')
            count=apply_geometry(board,g)
            pcbnew.Refresh()
            label='원본 Gerber 좌표 복원' if g['mode']=='source-exact' else '가변 권선 재배열'
            wx.MessageBox(
                '%s 완료\n배선: %d개 / 비아: %d개 / 네트: 2개\n'
                'F.Cu + B.Cu에서 생성했습니다.\n\n'
                '제작 전 DRC 및 두 권선의 연결성/절연을 확인하세요.\n'
                '원본은 매우 가는 트랙을 포함하므로 제조 가능 여부를 확인하세요.'%
                (label,len(g['tracks']),len(g['vias'])),
                'Rogowski',wx.OK|wx.ICON_INFORMATION)
        except Exception as exc:
            traceback.print_exc()
            wx.MessageBox('%s\n\n자세한 오류는 KiPython 콘솔에 출력됩니다.'%exc,
                          '생성 오류',wx.OK|wx.ICON_ERROR)
        finally:
            dlg.Destroy()
