# -*- coding: utf-8 -*-
"""KiCad 10 PCB Editor ActionPlugin for TI Gerber-derived Rogowski coil."""
import math
import os
import time
import traceback

import pcbnew
import wx

from . import geometry
from .preview import CoilPreview


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
    ('bend_radius','반원·사분원 공통 반경 (mm)'),
    ('clearance','비아 최소 이격 요구치 (mm)'),
    ('board_margin','옵션 외곽 여유 (mm)'),
]


class Parameters(wx.Dialog):
    def __init__(self, parent, copper_layers, board=None):
        super().__init__(parent, title='Rogowski TI Gerber Coil Generator v0.6.1',
                         size=(1180,800), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.board=board
        self.validated_values=None
        self.validated_geometry=None
        self.validating=False
        self.SetMinSize((1080,500))
        root=wx.BoxSizer(wx.VERTICAL)
        heading=wx.StaticText(self,label='TI TIDA-010971 · 2개 권선 · 바텀 패드 3–4 연결 · 4열 교차 비아')
        root.Add(heading,0,wx.ALL,12)
        note=wx.StaticText(self,label='기본 Top/Bottom 연결 유지  |  아래 인출 비아·꼭짓점은 권선 높이에 자동 연동')
        note.Wrap(550)
        root.Add(note,0,wx.LEFT|wx.RIGHT|wx.BOTTOM,12)
        scroll=wx.ScrolledWindow(self,style=wx.VSCROLL|wx.TAB_TRAVERSAL)
        scroll.SetMinSize((690,-1))
        scroll.SetScrollRate(0,12)
        contents=wx.BoxSizer(wx.VERTICAL)
        fg=wx.FlexGridSizer(cols=3,vgap=7,hgap=12)
        self.entries={}
        self.limit_labels={}
        for key,title in VALUES:
            fg.Add(wx.StaticText(scroll,label=title),0,wx.ALIGN_CENTER_VERTICAL)
            default=geometry.DEFAULTS[key]
            ent=wx.TextCtrl(scroll,value=str(default))
            ent.SetMinSize(self.FromDIP((110,-1)))
            self.entries[key]=ent
            fg.Add(ent,0,wx.ALIGN_CENTER_VERTICAL)
            limit=wx.StaticText(scroll,label='',style=wx.ST_NO_AUTORESIZE)
            limit.SetMinSize((230,36))
            self.limit_labels[key]=limit
            fg.Add(limit,0,wx.ALIGN_CENTER_VERTICAL)
        net_grid=wx.FlexGridSizer(cols=2,vgap=7,hgap=12)
        self.net_entries={}
        choices=sorted(str(name) for name in board.GetNetsByName() if str(name)) if board is not None else []
        for key,title in (('net_a','탑 패드 1 연결 네트'),('net_b','탑 패드 2 연결 네트')):
            net_grid.Add(wx.StaticText(scroll,label=title),0,wx.ALIGN_CENTER_VERTICAL)
            entry=wx.ComboBox(scroll,value=geometry.DEFAULTS[key],choices=choices,style=wx.CB_DROPDOWN)
            entry.SetMinSize((320,-1))
            self.net_entries[key]=entry
            net_grid.Add(entry,0,wx.EXPAND)
        contents.Add(net_grid,0,wx.ALL,14)
        contents.Add(wx.StaticText(scroll,label='기존 네트 선택 또는 새 이름 입력 · 1/3번은 같은 네트, 2/4번은 같은 네트\n바텀 3–4는 네트타이 구리 배선으로 연결됩니다.'),
                     0,wx.LEFT|wx.RIGHT|wx.BOTTOM,14)
        contents.Add(fg,0,wx.ALL|wx.EXPAND,14)
        contents.Add(wx.StaticText(scroll,label='오른쪽 범위는 현재 입력값 기준 · 길이 mm / 각도 °\n표시 범위 안에서도 생성 시 배선 간섭으로 제한될 수 있습니다.'),
                     0,wx.LEFT|wx.RIGHT|wx.BOTTOM,14)
        self.center_hole=wx.CheckBox(scroll,label='중앙 관통홀 생성 (Edge.Cuts, 비도금 개구부)')
        self.center_hole.SetValue(True)
        contents.Add(self.center_hole,0,wx.LEFT|wx.RIGHT|wx.BOTTOM,14)
        self.outline=wx.CheckBox(scroll,label='독립 시험 PCB 원형 외곽선 생성 (Edge.Cuts)')
        contents.Add(self.outline,0,wx.LEFT|wx.RIGHT|wx.BOTTOM,14)
        txt=wx.StaticText(scroll,label=('현재 PCB: %d층 구리 / 생성 배선: F.Cu 및 B.Cu만 사용\n'
                                        '원본 32: 좌측 인출부 및 앞·뒤 정렬 사각 패드 포함\n'
                                        '가변 N: 기본 인출부·비아 2개·앞뒤 패드 4개 포함\n'
                                        '※ 바텀 3–4 연결부에서 두 권선이 이어집니다. 외부 차폐 및 보상 리턴은 미구현\n'
                                        '※ 원본의 가는 트랙/간격은 제조사 DRC 요구와 다를 수 있음')%copper_layers)
        contents.Add(txt,0,wx.LEFT|wx.RIGHT|wx.BOTTOM,14)
        scroll.SetSizer(contents)
        scroll.FitInside()
        body=wx.BoxSizer(wx.HORIZONTAL)
        body.Add(scroll,0,wx.EXPAND)
        preview_panel=wx.Panel(self)
        preview_layout=wx.BoxSizer(wx.VERTICAL)
        preview_layout.Add(wx.StaticText(preview_panel,label='코일 미리보기'),0,wx.ALL,10)
        self.preview=CoilPreview(preview_panel)
        preview_layout.Add(self.preview,1,wx.EXPAND|wx.LEFT|wx.RIGHT,10)
        reset_view=wx.Button(preview_panel,label='전체 보기')
        reset_view.Bind(wx.EVT_BUTTON,self.preview.reset_view)
        preview_layout.Add(reset_view,0,wx.TOP|wx.LEFT,10)
        legend=wx.StaticText(preview_panel,label='빨강: F.Cu  /  파랑: B.Cu  /  노랑: 비아\n휠: 확대·축소 / 왼쪽 드래그: 이동\n더블 클릭: 전체 보기 · 위에서 본 모습 · DRC 검사 전')
        preview_layout.Add(legend,0,wx.ALL,10)
        self.focus_help=wx.StaticText(preview_panel,label='입력칸을 선택하면 해당 부분을 노란색으로 강조합니다.',
                                     style=wx.ST_NO_AUTORESIZE)
        self.focus_help.SetMinSize((300,60))
        self.focus_help.Wrap(300)
        preview_layout.Add(self.focus_help,0,wx.LEFT|wx.RIGHT|wx.BOTTOM,10)
        self.preview_status=wx.StaticText(preview_panel,label='')
        self.preview_status.Wrap(300)
        self.preview_status.SetMinSize((300,70))
        preview_layout.Add(self.preview_status,0,wx.ALL,10)
        preview_panel.SetSizer(preview_layout)
        body.Add(preview_panel,1,wx.EXPAND)
        root.Add(body,1,wx.EXPAND)
        root.Add(wx.StaticLine(self),0,wx.EXPAND)
        self.validation_status=wx.StaticText(self,label='치수 검증을 먼저 실행하세요. 검증 통과 후 생성할 수 있습니다.',
                                             style=wx.ST_NO_AUTORESIZE)
        self.validation_status.SetMinSize((600,40))
        root.Add(self.validation_status,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP,12)
        footer=wx.BoxSizer(wx.HORIZONTAL)
        footer.AddStretchSpacer(1)
        self.validate_button=wx.Button(self,label='치수 검증')
        self.validate_button.SetDefault()
        footer.Add(self.validate_button,0,wx.RIGHT,8)
        self.generate_button=wx.Button(self,wx.ID_OK,'로고스키 코일 생성')
        self.generate_button.Disable()
        footer.Add(self.generate_button,0,wx.RIGHT,8)
        footer.Add(wx.Button(self,wx.ID_CANCEL,'취소'))
        root.Add(footer,0,wx.ALL|wx.EXPAND,11)
        self.SetSizer(root)
        self.SetAffirmativeId(wx.ID_OK)
        self.SetEscapeId(wx.ID_CANCEL)
        self.Layout()
        self.preview_timer=wx.Timer(self)
        self.Bind(wx.EVT_TIMER,self.update_preview,self.preview_timer)
        for key,entry in self.entries.items():
            entry.Bind(wx.EVT_TEXT,self.schedule_preview)
            entry.Bind(wx.EVT_SET_FOCUS,lambda event,k=key:self.focus_parameter(event,k))
            entry.Bind(wx.EVT_KILL_FOCUS,self.blur_parameter)
        self.center_hole.Bind(wx.EVT_CHECKBOX,self.schedule_preview)
        self.outline.Bind(wx.EVT_CHECKBOX,self.schedule_preview)
        for entry in self.net_entries.values():
            entry.Bind(wx.EVT_TEXT,self.schedule_preview)
            entry.Bind(wx.EVT_COMBOBOX,self.schedule_preview)
        self.Bind(wx.EVT_WINDOW_DESTROY,self.on_destroy)
        self.validate_button.Bind(wx.EVT_BUTTON,self.validate_parameters)
        self.generate_button.Bind(wx.EVT_BUTTON,self.on_generate)
        self.update_preview()

    def schedule_preview(self,event):
        self.invalidate_validation()
        self.preview_timer.Start(200,oneShot=True)
        event.Skip()

    def set_validation_status(self,message,error=False,success=False):
        self.validation_status.SetLabel(message)
        self.validation_status.SetForegroundColour(
            wx.Colour('#d84a4a' if error else '#268349') if error or success else self.GetForegroundColour())
        self.validation_status.Wrap(max(300,self.GetClientSize().width-24))
        self.Layout()

    def invalidate_validation(self):
        self.validated_values=None
        self.validated_geometry=None
        self.generate_button.Disable()
        self.set_validation_status('입력값이 변경되었습니다. 치수 검증을 다시 실행하세요.')

    def check_board_options(self,p):
        if self.board is not None and p['outline']:
            if any(s.GetLayer()==pcbnew.Edge_Cuts for s in self.board.GetDrawings()):
                raise ValueError('기존 Edge.Cuts 외곽선이 있습니다. 외곽선 생성 옵션을 끄고 다시 검증하세요.')

    def validate_parameters(self,event=None):
        if self.validating: return
        self.preview_timer.Stop()
        self.invalidate_validation()
        self.validating=True
        self.validate_button.Disable()
        progress_dialog=None
        try:
            p=self.get_values()
            self.check_board_options(p)
            self.set_validation_status('치수와 두 권선의 구리 겹침을 검증하고 있습니다.')
            progress_dialog=wx.ProgressDialog(
                '로고스키 코일 치수 검증','0% · 검증 준비 중',maximum=100,parent=self,
                style=wx.PD_APP_MODAL|wx.PD_AUTO_HIDE|wx.PD_ELAPSED_TIME)
            last=[-1,0.0]
            def report(value,message):
                percent=max(last[0],min(100,int(value*100/55)))
                now=time.monotonic()
                if percent!=last[0] or now-last[1]>=0.1:
                    progress_dialog.Update(percent,'%d%% · %s'%(percent,message))
                    last[:]=[percent,now]
            g=geometry.build(p,report)
            if p!=self.get_values():
                raise ValueError('검증 중 입력값이 변경되었습니다. 다시 검증하세요.')
            self.validated_values=dict(p)
            self.validated_geometry=g
            self.set_validation_status(
                '검증 통과 · 배선 %d개 / 비아 %d개 · %s · 생성할 수 있습니다. (KiCad DRC는 별도 확인)'%
                (len(g['primitives']),len(g['vias']),
                 '공통 반경 %.4g mm'%p['bend_radius'] if p['bend_radius']>0 else '원본 원호 방식'),success=True)
        except Exception as exc:
            self.validated_values=None
            self.validated_geometry=None
            self.set_validation_status('검증 실패: %s'%exc,error=True)
        finally:
            if progress_dialog is not None: progress_dialog.Destroy()
            self.validating=False
            self.validate_button.Enable()
            self.generate_button.Enable(self.validated_geometry is not None)

    def get_validated_geometry(self):
        if self.validated_geometry is None:
            raise ValueError('치수 검증을 먼저 실행하세요.')
        try: current=self.get_values()
        except (ValueError,OverflowError):
            self.invalidate_validation()
            raise ValueError('입력값이 변경되었습니다. 다시 검증하세요.')
        if current!=self.validated_values:
            self.invalidate_validation()
            raise ValueError('입력값이 변경되었습니다. 다시 검증하세요.')
        return self.validated_geometry

    def on_generate(self,event):
        try:
            g=self.get_validated_geometry()
            self.check_board_options(g['settings'])
        except ValueError as exc:
            self.invalidate_validation()
            self.set_validation_status(str(exc),error=True)
            return
        self.EndModal(wx.ID_OK)

    def focus_parameter(self,event,key):
        self.preview.highlight(key)
        self.focus_help.SetLabel(self.preview.highlight_help())
        self.focus_help.Wrap(300)
        event.Skip()

    def blur_parameter(self,event):
        self.preview.highlight(None)
        self.focus_help.SetLabel('입력칸을 선택하면 해당 부분을 노란색으로 강조합니다.')
        self.focus_help.Wrap(300)
        event.Skip()

    def update_preview(self,event=None):
        for label in self.limit_labels.values():
            label.SetLabel('숫자 입력을 완료하면 범위 표시')
        try:
            p=self.get_values()
            for key,text in geometry.parameter_limits(p).items():
                self.limit_labels[key].SetLabel(text)
                self.limit_labels[key].Wrap(230)
            self.preview.update(p)
            self.preview_status.SetLabel('%d위치 · 비아 %d개\n중심 (%.2f, %.2f) mm · 회전 %.1f°\n%s'%
                (p['turns'],len(self.preview.scene[1]),p['cx'],p['cy'],p['rotation'],
                 '반원·사분원 공통 R %.4g mm'%p['bend_radius'] if p['bend_radius']>0 else '원본 원호 방식'))
        except (ValueError,OverflowError) as exc:
            self.preview.clear()
            self.preview_status.SetLabel('입력값을 확인하세요: %s'%exc)
        self.preview_status.Wrap(300)
        self.Layout()

    def on_destroy(self,event):
        if event.GetEventObject() is self: self.preview_timer.Stop()
        event.Skip()

    def get_values(self):
        p={}
        for key,_ in VALUES:
            raw=self.entries[key].GetValue().strip()
            p[key]=int(raw) if key=='turns' else float(raw)
        p['outline']=bool(self.outline.GetValue())
        p['center_hole']=bool(self.center_hole.GetValue())
        for key,entry in self.net_entries.items():
            p[key]=entry.GetValue().strip()
            if not p[key] or any(c in p[key] for c in '\r\n\x00'):
                raise ValueError('패드 1·2에 연결할 네트 이름을 입력하거나 선택하세요.')
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


def terminal_footprint(board,pads,nets,bridges,reference=None):
    footprint=pcbnew.FOOTPRINT(board)
    references={f.GetReference() for f in board.GetFootprints()}
    number=1
    while 'RC%d'%number in references or 'RC%dB'%number in references: number+=1
    footprint.SetReference(reference or 'RC%d'%number)
    footprint.SetValue('Rogowski bottom link' if bridges else 'Rogowski terminals')
    footprint.SetLayer(pcbnew.B_Cu if pads[0]['layer']=='B' else pcbnew.F_Cu)
    footprint.Reference().SetVisible(False);footprint.Value().SetVisible(False)
    footprint.SetAttributes(pcbnew.FP_SMD|pcbnew.FP_BOARD_ONLY|
                            pcbnew.FP_EXCLUDE_FROM_BOM|pcbnew.FP_EXCLUDE_FROM_POS_FILES)
    footprint.SetPosition(vec(pads[0]['p']))
    for pad in pads:
        obj=pcbnew.PAD(footprint)
        obj.SetNumber(pad['number'])
        obj.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
        obj.SetShape(pcbnew.PAD_SHAPE_ROUNDRECT)
        obj.SetRoundRectRadiusRatio(0.1)
        obj.SetSize(vec((pad['size'],pad['size'])))
        layers=pcbnew.LSET()
        layers.AddLayer(pcbnew.F_Cu if pad['layer']=='F' else pcbnew.B_Cu)
        layers.AddLayer(pcbnew.F_Mask if pad['layer']=='F' else pcbnew.B_Mask)
        obj.SetLayerSet(layers)
        obj.SetPosition(vec(pad['p']))
        # KiCad pad angles use the opposite sign to model coordinates (Y down).
        obj.SetOrientationDegrees(-pad['rotation'])
        obj.SetNet(nets[pad['net']])
        footprint.Add(obj)
    if bridges: footprint.AddNetTiePadGroup('3,4')
    for bridge in bridges:
        copper=pcbnew.PCB_SHAPE(footprint)
        copper.SetShape(pcbnew.SHAPE_T_SEGMENT)
        copper.SetStart(vec(bridge['a']));copper.SetEnd(vec(bridge['b']))
        copper.SetWidth(mm(bridge['width']))
        copper.SetLayer(pcbnew.B_Cu)
        footprint.Add(copper)
    return footprint


def focus_generated_coil(identifier):
    """Run after the plugin/dialog closes and KiCad rebuilds its canvas."""
    board=pcbnew.GetBoard()
    if board is None: return
    item=board.ResolveItem(pcbnew.KIID(identifier),True)
    if item is None: return
    pcbnew.Refresh()
    pcbnew.FocusOnItem(item,pcbnew.F_Cu)
    pcbnew.FocusOnItem(None)  # Leave the normal copper colours visible.


def apply_geometry(board,g,progress=None):
    def report(value, message):
        if progress is not None: progress(value, message)
    report(55, 'PCB 네트 준비 중')
    p=g['settings']
    nets={'A':get_net(board,p['net_a']),
          'B':get_net(board,p['net_b'])}
    items=[]
    # Create all board objects in memory first. Add only after construction.
    for index,t in enumerate(g['primitives']):
        if index%64==0:
            report(56+20*index/max(1,len(g['primitives'])),
                   'PCB 직선·원호 준비 중 (%d/%d)'%(index,len(g['primitives'])))
        line=pcbnew.PCB_ARC(board) if t['kind']=='arc' else pcbnew.PCB_TRACK(board)
        line.SetStart(vec(t['a']))
        line.SetEnd(vec(t['b']))
        if t['kind']=='arc': line.SetMid(vec(t['mid']))
        line.SetWidth(mm(p['width']))
        line.SetLayer(pcbnew.F_Cu if t['layer']=='F' else pcbnew.B_Cu)
        line.SetNet(nets[t['net']])
        items.append(line)
    for index,v in enumerate(g['vias']):
        if index%16==0:
            report(76+4*index/max(1,len(g['vias'])), 'PCB 비아 준비 중')
        obj=pcbnew.PCB_VIA(board)
        obj.SetPosition(vec(v['p']))
        obj.SetWidth(mm(p['via']))
        obj.SetDrill(mm(p['drill']))
        obj.SetViaType(pcbnew.VIATYPE_THROUGH)
        obj.SetLayerPair(pcbnew.F_Cu,pcbnew.B_Cu)
        obj.SetNet(nets[v['net']])
        items.append(obj)
    # Keep the bottom net tie separate: KiCad's net-tie cache can otherwise
    # associate its copper with the front pads at the identical XY positions.
    front=terminal_footprint(board,[pad for pad in g['pads'] if pad['layer']=='F'],nets,[])
    back=terminal_footprint(board,[pad for pad in g['pads'] if pad['layer']=='B'],nets,
                            g['bridges'],front.GetReference()+'B')
    items.extend((front,back))
    if p['outline'] or p['center_hole']:
        report(80, '중앙 홀 및 외곽선 준비 중')
        # Outline must encompass left breakout in reference mode.
        c=(p['cx'],p['cy'])
        circle_radii=[]
        if p['outline']:
            radius=geometry.copper_radius(g['tracks'],g['vias'],p,g['pads'])+p['board_margin']
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
    group=pcbnew.PCB_GROUP(board)
    group.SetName('Rogowski Coil')
    for item in items: group.AddItem(item)
    items.append(group)
    inserted=[]
    try:
        for index,item in enumerate(items):
            if index%64==0:
                report(82+15*index/max(1,len(items)),
                       'PCB에 패턴 추가 중 (%d/%d)'%(index,len(items)))
            board.Add(item)
            inserted.append(item)
    except Exception:
        for item in reversed(inserted):
            try: board.Remove(item)
            except Exception: pass
        raise
    g['focus_uuid']=group.m_Uuid.AsString()
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
        dlg=Parameters(None,board.GetCopperLayerCount(),board)
        progress_dialog=None
        focus_uuid=None
        try:
            if dlg.ShowModal()!=wx.ID_OK:return
            dlg.preview_timer.Stop()
            g=dlg.get_validated_geometry()
            dlg.check_board_options(g['settings'])
            progress_dialog=wx.ProgressDialog(
                '로고스키 코일 생성', '0% · 생성 준비 중', maximum=100,
                parent=dlg, style=wx.PD_APP_MODAL|wx.PD_AUTO_HIDE|wx.PD_ELAPSED_TIME)
            last_update=[-1,0.0]
            def progress(value,message):
                percent=max(last_update[0], min(100,int(value)))
                now=time.monotonic()
                if percent!=last_update[0] or now-last_update[1]>=0.1:
                    progress_dialog.Update(percent, '%d%% · %s'%(percent,message))
                    last_update[:]=[percent,now]
            progress(0,'검증된 코일 모델 준비 중')
            count=apply_geometry(board,g,lambda value,message:progress((value-55)*100/45,message))
            progress(98,'PCB 화면 갱신 중')
            pcbnew.Refresh()
            progress(100,'코일 생성 완료')
            progress_dialog.Destroy()
            progress_dialog=None
            focus_uuid=g['focus_uuid']
            label={'source-exact':'원본 Gerber 좌표 복원',
                   'circular-bends':'원형 굴곡 패턴 생성',
                   'parametric':'가변 권선 재배열'}[g['mode']]
            wx.MessageBox(
                '%s 완료\n직선·원호: %d개 / 비아: %d개 / 패드: 4개 / 네트: %d개\n'
                'F.Cu + B.Cu에서 생성했습니다.\n\n'
                '패드 1: %s / 패드 2: %s\n바텀 3–4 구리 배선 연결 완료\n'
                '확인을 누르면 생성한 코일 위치로 이동합니다.\n'
                '제작 전 DRC 및 두 권선의 연결성/절연을 확인하세요.\n'
                '원본은 매우 가는 트랙을 포함하므로 제조 가능 여부를 확인하세요.'%
                (label,len(g['primitives']),len(g['vias']),len({g['settings']['net_a'],g['settings']['net_b']}),
                 g['settings']['net_a'],g['settings']['net_b']),
                'Rogowski',wx.OK|wx.ICON_INFORMATION)
        except Exception as exc:
            if progress_dialog is not None:
                progress_dialog.Destroy()
                progress_dialog=None
            traceback.print_exc()
            wx.MessageBox('%s\n\n자세한 오류는 KiPython 콘솔에 출력됩니다.'%exc,
                          '생성 오류',wx.OK|wx.ICON_ERROR)
        finally:
            if progress_dialog is not None: progress_dialog.Destroy()
            dlg.Destroy()
            if focus_uuid is not None: wx.CallAfter(focus_generated_coil,focus_uuid)
