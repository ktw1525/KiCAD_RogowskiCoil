# -*- coding: utf-8 -*-
"""TI TIDA-010971E2.0 Gerber-derived dual-winding PCB Rogowski geometry.

Pure standard Python: unit-testable without pcbnew/wx.
Reference N=32 starts from GTL/GBL D132 centrelines and all 66 T01
drill centres. Optional circular bends modify the source geometry.
"""
import json
import math
import os

REF_RADII = (2.235, 2.90185, 4.880, 5.265)
REF_STEP = 360.0/34.0
DEFAULTS = dict(cx=100.0,cy=100.0,turns=32,hole=3.0,
                ri1=2.235,ri2=2.90185,ro1=4.880,ro2=5.265,
                width=0.100, via=0.450, drill=0.200, rotation=0.0,
                clearance=0.10, outline=False, board_margin=0.9,
                bend_radius=0.385,net_a='ROGOWSKI_A',net_b='ROGOWSKI_B',
                layer_f='F.Cu',layer_b='B.Cu')


def copper_layers(count):
    return ['F.Cu']+['In%d.Cu'%i for i in range(1,count-1)]+['B.Cu']


def selected_layers(p):
    return {'F':p.get('layer_f','F.Cu'),'B':p.get('layer_b','B.Cu')}


def layer_color(name):
    if name=='F.Cu': return '#ff7979'
    if name=='B.Cu': return '#63a9ff'
    colors=('#83c575','#db992e','#d55de6','#59c7c7')
    return colors[(int(name[2:-3])-1)%len(colors)]

def source_model():
    with open(os.path.join(os.path.dirname(__file__), 'coil_model.json'),
              encoding='utf-8') as f:
        return json.load(f)

def _signed_step(j,k,slots):
    d=(k-j)%slots
    return d-slots if d>slots/2 else d

def _xy(r,theta):
    a=math.radians(theta)
    return r*math.cos(a),r*math.sin(a)

def _angle(p):
    return math.degrees(math.atan2(p[1],p[0]))

def _normalize(a):
    return (a+180.0)%360.0 - 180.0

def _radial(r, param):
    anchors=(0.0,1.5,*REF_RADII)
    targets=(0.0,param['hole']/2,param['ri1'],param['ri2'],param['ro1'],param['ro2'])
    for n in range(1,len(anchors)):
        if r <= anchors[n]+1e-9:
            ratio=(r-anchors[n-1])/(anchors[n]-anchors[n-1])
            return targets[n-1]+ratio*(targets[n]-targets[n-1])
    return targets[-1]+(r-anchors[-1])*(targets[-1]/anchors[-1])

def _transform_point(point,param, extra_rotate=0.0, angular_scale=1.0, anchor=None):
    r=math.hypot(*point)
    theta=_angle(point)
    if anchor is None:
        angle=theta+param['rotation']+extra_rotate
    else:
        angle=anchor[1]+_normalize(theta-anchor[0])*angular_scale+param['rotation']
    x,y=_xy(_radial(r,param),angle)
    return (param['cx']+x,param['cy']+y)

def _is_breakout(component):
    return any(port.startswith('L') for port in component['ports']) or len(component['ports'])==1


def _breakout_paths(component,model):
    # Snap shared source joins before scaling, rather than stretching tiny gaps.
    joints=[(v['x'],v['y']) for v in model['vias'] if v['id'] in component['ports']]
    paths=[]
    for source in component['paths']:
        path=[tuple(q) for q in source]
        for index in (0,-1):
            close=[q for q in joints if math.dist(q,path[index])<0.05]
            if close: path[index]=min(close,key=lambda q:math.dist(q,path[index]))
            else: joints.append(path[index])
        paths.append(path)
    return paths


def _fit_arc(points):
    if len(points)<3: return None
    a,b,c=points[0],points[len(points)//2],points[-1]
    bx,by=b[0]-a[0],b[1]-a[1];cx,cy=c[0]-a[0],c[1]-a[1]
    det=2*(bx*cy-by*cx)
    if abs(det)<1e-10: return None
    center=(((bx*bx+by*by)*cy-(cx*cx+cy*cy)*by)/det+a[0],
            ((cx*cx+cy*cy)*bx-(bx*bx+by*by)*cx)/det+a[1])
    radius=math.dist(a,center)
    if any(abs(math.dist(q,center)-radius)>0.002 for q in points): return None
    angles=[math.atan2(q[1]-center[1],q[0]-center[0]) for q in points]
    sweep=sum((v-u+math.pi)%(2*math.pi)-math.pi for u,v in zip(angles,angles[1:]))
    return center,radius,angles[0],sweep


def _circle_points(center,radius,start,sweep):
    steps=max(4,math.ceil(abs(sweep)*radius/0.02))
    return [(center[0]+radius*math.cos(start+sweep*i/steps),
             center[1]+radius*math.sin(start+sweep*i/steps)) for i in range(steps+1)]


def _arc_record(points,meta):
    """Keep one circular primitive, with samples used only by geometry checks."""
    if 'bend_center' in meta:
        arc=(meta['bend_center'],meta['bend_radius'],meta['bend_start'],meta['bend_sweep'])
    else:
        # Radius/angular edits can warp source samples. Define a real circle
        # through the transformed endpoints and midpoint instead of exporting
        # that warped polyline as hundreds of tiny tracks.
        arc=_fit_arc([points[0],points[len(points)//2],points[-1]])
    if arc is None: raise ValueError('원호의 세 점이 일직선입니다. 코일 치수를 확인하세요.')
    sampled=_circle_points(*arc)
    sampled[0]=points[0];sampled[-1]=points[-1]
    return sampled,dict(meta,arc=arc)


def copper_primitives(tracks):
    """Collapse each sampled circular run into one native start/mid/end arc."""
    result=[];index=0
    while index<len(tracks):
        first=tracks[index];index+=1
        if 'arc' not in first:
            result.append(dict(first,kind='line'))
            continue
        run=[first]
        while index<len(tracks):
            following=tracks[index]
            if (following.get('arc')!=first['arc'] or following['net']!=first['net'] or
                    following['layer']!=first['layer'] or math.dist(run[-1]['b'],following['a'])>1e-7): break
            run.append(following);index+=1
        center,radius,_,_=first['arc']
        def angle(q): return math.atan2(q[1]-center[1],q[0]-center[0])
        start=angle(first['a'])
        sweep=sum((angle(t['b'])-angle(t['a'])+math.pi)%(2*math.pi)-math.pi for t in run)
        mid=(center[0]+radius*math.cos(start+sweep/2),center[1]+radius*math.sin(start+sweep/2))
        result.append(dict(first,kind='arc',b=run[-1]['b'],mid=mid,arc=(center,radius,start,sweep)))
    return result


def _merge_split_arcs(sources):
    """Restore circular runs split by straight detours in the Gerber model.

    Only cross unbranched straight joins between arcs on the same circle.
    This restores both the split outer half bend and its outer ring connector
    before their endpoints move to accommodate the requested bend radius.
    """
    sources=list(sources)
    while True:
        nodes=[];joins={};ends=[]
        def node(q):
            for i,old in enumerate(nodes):
                if math.dist(q,old)<0.002: return i
            nodes.append(q)
            return len(nodes)-1
        for i,path in enumerate(sources):
            a,b=node(path[0]),node(path[-1]);ends.append((a,b))
            joins.setdefault(a,[]).append(i);joins.setdefault(b,[]).append(i)
        fits=[_fit_arc(path) for path in sources]
        merged=False
        for i,fit in enumerate(fits):
            if fit is None: continue
            for reverse in (False,True):
                current=ends[i][0 if reverse else 1]
                previous=i;bridges=[];visited={i}
                while len(joins[current])==2:
                    j=next(k for k in joins[current] if k!=previous)
                    if j in visited: break
                    visited.add(j)
                    backwards=ends[j][1]==current
                    other=ends[j][0 if backwards else 1]
                    candidate=fits[j]
                    if candidate is not None:
                        if not bridges: break
                        center,radius,start,sweep=fit
                        direction=-sweep if reverse else sweep
                        next_sweep=-candidate[3] if backwards else candidate[3]
                        if (math.dist(center,candidate[0])>0.003 or
                                abs(radius-candidate[1])>0.003 or direction*next_sweep<=0): break
                        first=sources[i][-1 if reverse else 0]
                        last=sources[j][0 if backwards else -1]
                        start=math.atan2(first[1]-center[1],first[0]-center[0])
                        end=math.atan2(last[1]-center[1],last[0]-center[0])
                        sign=1 if direction>0 else -1
                        span=sign*((end-start)*sign%(2*math.pi))
                        if abs(span)<abs(direction)+abs(next_sweep)-0.001: break
                        points=_circle_points(center,radius,start,span)
                        points[0]=first;points[-1]=last
                        removed={i,j,*bridges}
                        sources=[path for k,path in enumerate(sources) if k not in removed]+[points]
                        merged=True
                        break
                    if len(sources[j])!=2: break
                    bridges.append(j);previous=j;current=other
                if merged: break
            if merged: break
        if not merged: return sources


def _component_paths(component,model,p,mapper,via_mapper,sources=None):
    """Move shared endpoints together; all small 90/180 bends use one radius."""
    sources=component['paths'] if sources is None else sources
    sources=[[tuple(q) for q in path] for path in sources]
    if p['bend_radius']>0: sources=_merge_split_arcs(sources)
    # Some extracted arcs run past a junction lying inside the sampled arc.
    # Trim that overrun first, so the adjacent path shares the movable endpoint.
    if p['bend_radius']>0:
        for index,path in enumerate(sources):
            fit=_fit_arc(path)
            if fit is None or fit[1]>1 or math.hypot(*fit[0])<1: continue
            center,radius,start,sweep=fit
            other=[q for j,part in enumerate(sources) if j!=index for q in (part[0],part[-1])]
            sign=1 if sweep>0 else -1
            def along(q): return ((math.atan2(q[1]-center[1],q[0]-center[0])-start)*sign)%(2*math.pi)
            contacts=[q for q in other if abs(math.dist(q,center)-radius)<0.002
                      and 0.001<along(q)<abs(sweep)-0.001]
            low,high=0.0,abs(sweep);first,last=path[0],path[-1]
            if not any(math.dist(first,q)<0.05 for q in other):
                near=[q for q in contacts if along(q)<math.pi/6]
                if near: first=min(near,key=along);low=along(first)
            if not any(math.dist(last,q)<0.05 for q in other):
                near=[q for q in contacts if abs(sweep)-along(q)<math.pi/6]
                if near: last=max(near,key=along);high=along(last)
            if low>0 or high<abs(sweep):
                sources[index]=[first]+[q for q in path[1:-1] if low<along(q)<high]+[last]
    joints=[];positions=[]
    def joint(q):
        for i,old in enumerate(joints):
            if math.dist(q,old)<0.05: return i
        joints.append(tuple(q));positions.append(mapper(q));return len(joints)-1
    for v in model['vias']:
        if v['id'] in component['ports']:
            i=joint((v['x'],v['y']));positions[i]=via_mapper(v)
    entries=[]
    for source in sources:
        entries.append((source,joint(source[0]),joint(source[-1]),_fit_arc(source)))
    bends={};moved=set()
    orthogonal_inner=(component['net']=='B' and component['layer']=='B' and component['ports']==['I14'])
    red_inlet=(component['net']=='A' and component['layer']=='F' and set(component['ports'])=={'L17','I16'})
    inner_half=None
    requested=p['bend_radius']
    if requested>0:
        for index,(source,a,b,fit) in enumerate(entries):
            if fit is None: continue
            center,radius,start,sweep=fit
            if radius>1 or math.hypot(*center)<1 or min(math.hypot(*q) for q in source)>=5.90: continue
            degrees=abs(math.degrees(sweep))
            if 60<=degrees<=120: span=math.pi/2
            elif 150<=degrees<=220: span=math.pi
            else: continue
            nearest=min(model['vias'],key=lambda v:math.dist(center,(v['x'],v['y'])))
            target=via_mapper(nearest) if math.dist(center,(nearest['x'],nearest['y']))<0.002 else mapper(center)
            direction=math.atan2(target[1]-p['cy'],target[0]-p['cx'])
            relative=start-math.atan2(center[1],center[0])
            relative=round(relative/(math.pi/2))*math.pi/2
            span=math.copysign(span,sweep)
            angle=direction+relative
            special=orthogonal_inner and abs(span)==math.pi
            if special:
                # Use the winding's radial frame at the shared via. The red
                # quarter must end on the same radial line as the blue spoke.
                angle=direction-3*math.pi/2
                span=math.pi
            shared_quarter=(component['net']=='A' and component['layer']=='F' and
                            abs(span)==math.pi/2 and
                            math.dist(target,_target_via(p['turns']//2,'I',p['turns'],p))<1e-6)
            if shared_quarter:
                angle=direction-(math.pi/2 if span>0 else 0)
            points=_circle_points(target,requested,angle,span)
            bends[index]=(points,dict(bend_center=target,bend_radius=requested,bend_sweep=span,
                                      bend_start=angle,inner_lead_half=special,shared_inner_quarter=shared_quarter))
            for node,q in ((a,points[0]),(b,points[-1])):
                if node not in moved: positions[node]=q;moved.add(node)
            if special: inner_half=(target,a,b,points[-1])
    if inner_half is not None:
        center,top_node,bottom_node,bottom=inner_half
        rotation=math.radians(p['rotation'])
        vertical=(-math.sin(rotation),math.cos(rotation))
        center_y=(center[0]-p['cx'])*vertical[0]+(center[1]-p['cy'])*vertical[1]
        leg=max(0,center_y-requested)
        positions[bottom_node]=(bottom[0]+leg*vertical[0],bottom[1]+leg*vertical[1])
    records=[]
    for index,(source,a,b,fit) in enumerate(entries):
        if index in bends:
            points,meta=bends[index]
            if math.dist(positions[a],points[0])>1e-8: records.append(([positions[a],points[0]],{}))
            records.append(_arc_record(points,meta))
            if math.dist(points[-1],positions[b])>1e-8:
                records.append(([points[-1],positions[b]],
                                dict(inner_lead_leg='lower') if meta.get('inner_lead_half') else {}))
            continue
        points=[mapper(q) for q in source]
        points[0]=positions[a];points[-1]=positions[b]
        record_meta={}
        if red_inlet and min(math.hypot(*q) for q in source)<5.90:
            record_meta['red_inner_inlet']=True
        if inner_half is not None and len(source)==2 and b==inner_half[1]:
            angle=math.radians(p['rotation']);horizontal=(math.cos(angle),math.sin(angle))
            dx,dy=points[-1][0]-points[0][0],points[-1][1]-points[0][1]
            length=dx*horizontal[0]+dy*horizontal[1]
            corner=(points[0][0]+length*horizontal[0],points[0][1]+length*horizontal[1])
            points=[points[0],corner,points[-1]]
            record_meta['inner_lead_top']=True
        if inner_half is not None and fit is not None and math.hypot(*fit[0])<0.01 and b==inner_half[2]:
            record_meta['inner_lead_return']=True
        if requested>0 and fit is not None and math.hypot(*fit[0])<0.01:
            first,last=points[0],points[-1];dx,dy=last[0]-first[0],last[1]-first[1]
            length2=dx*dx+dy*dy
            if length2>1e-12:
                origin=(p['cx'],p['cy'])
                shift=(math.dist(last,origin)**2-math.dist(first,origin)**2)/(2*length2)
                center=(origin[0]+shift*dx,origin[1]+shift*dy)
                start=math.atan2(first[1]-center[1],first[0]-center[0])
                end=math.atan2(last[1]-center[1],last[0]-center[0])
                span=(end-start+math.pi)%(2*math.pi)-math.pi
                if span*fit[3]<-1e-8:
                    raise ValueError('공통 원호 반경이 연결 공간에 비해 큽니다. 반경을 줄이거나 비아 열 간격을 조정하세요.')
                points=_circle_points(center,math.dist(first,center),start,span)
                points[0]=first;points[-1]=last
        records.append(_arc_record(points,record_meta) if fit is not None else (points,record_meta))
    return records


def _align_inner_guides(tracks,vias,p):
    """Use identical centreline segments on Top/Bottom beside the inlet arc."""
    half=[t for t in tracks if t.get('inner_lead_half')]
    if not half: return tracks
    top=[t for t in tracks if t.get('inner_lead_top')]
    center=half[0]['bend_center'];upper=half[0]['a'];lower=half[-1]['b']
    # Find the existing red guide from this quarter-circle to the next half-circle.
    def key(q): return (round(q[0],7),round(q[1],7))
    graph={}
    for t in tracks:
        if t['layer']!='F' or t['net']!='A' or t.get('breakout') or 'bend_center' in t: continue
        for a,b in ((t['a'],t['b']),(t['b'],t['a'])):
            graph.setdefault(key(a),[]).append((a,b,t))
    path=[];current=key(lower);previous=None;seen=set()
    while current not in seen:
        seen.add(current)
        choices=[item for item in graph.get(current,()) if key(item[1])!=previous]
        if not choices: break
        if len(choices)!=1: raise ValueError('인출부 공통 경로의 연결을 확인할 수 없습니다.')
        a,b,t=choices[0];path.append((a,b,t));previous,current=current,key(b)
    endpoint=_target_via(p['turns']//2-2,'I',p['turns'],p)
    if not path or abs(math.dist(path[-1][1],endpoint)-p['bend_radius'])>1e-5:
        raise ValueError('인출부의 다음 권선 접속 경로를 확인할 수 없습니다.')
    result=[t for t in tracks if not (t.get('red_inner_inlet') or t.get('inner_lead_return') or
                                     t.get('inner_lead_leg')=='lower')]
    # Red follows precisely the same upper horizontal and vertical segments as blue.
    for t in top:
        t['shared_inner_guide']='upper'
        result.append(dict(a=t['a'],b=t['b'],layer='F',net='A',breakout=True,shared_inner_guide='upper'))
    result.append(dict(a=upper,b=center,layer='F',net='A',breakout=True))
    # Blue follows the actual red lower guide, instead of fitting a second curve.
    for a,b,t in path:
        t['shared_inner_guide']='lower'
        copied=dict(a=a,b=b,layer='B',net='B',breakout=True,
                    inner_lead_return=True,shared_inner_guide='lower')
        if 'arc' in t: copied['arc']=t['arc']
        result.append(copied)
    result.append(dict(a=path[-1][1],b=endpoint,layer='B',net='B',breakout=True,
                       inner_lead_return=True,inner_lead_terminal=True))
    return result


def _source_edges(model,param):
    tracks=[]
    def via_point(v):
        if v['id'].startswith('L'): return _breakout_point((v['x'],v['y']),param)
        return _target_via(int(v['id'][1:]),v['id'][0],32,param)
    for component in model['components']:
        lead=_is_breakout(component)
        paths=(_mapped_breakout_paths(component,model,param) if lead else
               _component_paths(component,model,param,lambda q:_transform_point(q,param),via_point))
        for points,meta in paths:
            for a,b in zip(points,points[1:]):
                if math.dist(a,b)>0.000005:
                    tracks.append(dict(a=a,b=b,layer=component['layer'],net=component['net'],breakout=lead,**meta))
    vias=[dict(p=via_point(v),net=v['net'],id=v['id']) for v in model['vias']]
    return _align_inner_guides(tracks,vias,param),vias


def _sequence_A(n):
    slots=n+2;half=n//2;k=n//4
    first=[(half-4*t)%slots for t in range(k)]
    second=[(first[-1]-1+4*t)%slots for t in range(k)]
    return first+second

def _sequence_B(n):
    slots=n+2;half=n//2;k=n//4
    first=[(half-3-4*t)%slots for t in range(k)]
    second=[(first[-1]+1+4*t)%slots for t in range(k)]
    return first+second

def _target_via(j,kind,n,param):
    # Two adjacent pitch rings, alternating every angular slot.
    r=(param['ri2'] if j%2 else param['ri1']) if kind=='I' else (param['ro2'] if j%2 else param['ro1'])
    angle=j*360.0/(n+2)
    x,y=_xy(r,angle+param['rotation'])
    return (param['cx']+x,param['cy']+y)

def _template_long(model,layer,d,parity):
    matches=[]
    for c in model['components']:
        if c['layer']!=layer or len(c['ports'])!=2: continue
        outer=[v for v in c['ports'] if v.startswith('O')]
        inner=[v for v in c['ports'] if v.startswith('I')]
        if not outer or not inner: continue
        o,i=int(outer[0][1:]),int(inner[0][1:])
        if _signed_step(o,i,34)==d and o%2==parity: matches.append((c,o,i))
    if not matches: raise ValueError('원본 연결 템플릿을 찾을 수 없습니다.')
    return matches[len(matches)//2]


def _warp_template(c,src_o,src_i,tgt_o,tgt_i,n,p,model):
    assert _signed_step(src_o,src_i,34)==_signed_step(tgt_o,tgt_i,n+2)
    def mapper(q):
        return _transform_point(q,p,angular_scale=34.0/(n+2),
                                anchor=(src_o*REF_STEP,tgt_o*360.0/(n+2)))
    def via_point(v):
        if v['id'].startswith('L'): return mapper((v['x'],v['y']))
        j=(tgt_o+_signed_step(src_o,int(v['id'][1:]),34))%(n+2)
        return _target_via(j,v['id'][0],n,p)
    tracks=[]
    for points,meta in _component_paths(c,model,p,mapper,via_point):
        for a,b in zip(points,points[1:]):
            if math.dist(a,b)>0.000005:
                tracks.append(dict(a=a,b=b,layer=c['layer'],net=c['net'],cell_ports=(tgt_o,tgt_i),**meta))
    return tracks


def _variable_edges(model,p,progress=None):
    """Extend the reference alternating Top/Bottom cells, not a new winding."""
    n=p['turns'];tracks=[];vias=[]
    for net,seq in (('A',_sequence_A(n)),('B',_sequence_B(n))):
        local,long_layer=('B','F') if net=='A' else ('F','B')
        for j in seq:
            inner=_target_via(j,'I',n,p);outer=_target_via(j,'O',n,p)
            tracks.append(dict(a=inner,b=outer,layer=local,net=net,radial_cell=j))
            vias.extend([dict(p=inner,net=net,id='I'+str(j)),dict(p=outer,net=net,id='O'+str(j))])
        for j,k in zip(seq,seq[1:]):
            o,i=(j,k) if net=='A' else (k,j)
            template,src_o,src_i=_template_long(model,long_layer,_signed_step(o,i,n+2),o%2)
            for track in _warp_template(template,src_o,src_i,o,i,n,p,model):
                track['net']=net
                tracks.append(track)
    if progress is not None: progress('기본 Top/Bottom 인출부 형상 생성 중')
    for c in model['components']:
        if not _is_breakout(c): continue
        for points,meta in _mapped_breakout_paths(c,model,p):
            for a,b in zip(points,points[1:]):
                if math.dist(a,b)>0.000005:
                    tracks.append(dict(a=a,b=b,layer=c['layer'],net=c['net'],breakout=True,**meta))
    for v in model['vias']:
        if v['id'].startswith('L'):
            vias.append(dict(p=_breakout_point((v['x'],v['y']),p),net=v['net'],id=v['id']))
    return _align_inner_guides(tracks,vias,p),vias


def _base_breakout_point(point,p):
    # Preserve the external diamond/viapair by a similarity transform only.
    # Blend angular pitch changes exclusively between the coil and that fixed
    # external shape. All layers use this ONE map, so shared joints stay shared.
    r=math.hypot(*point)
    blend=max(0.0,min(1.0,(r-5.90)/0.10))
    angular=34.0/(p['turns']+2)
    angular=angular+(1-angular)*blend
    return _transform_point(point,p,angular_scale=angular,anchor=(180.0,180.0))


def _breakout_layout(p):
    """Follow the adjacent winding row in the unrotated local frame."""
    local=dict(p,cx=0.0,cy=0.0,rotation=0.0)
    coil=_base_breakout_point((-5.212,0.7455),local)
    old_elbow=_base_breakout_point((-5.9695,0.8871),local)
    old_via=_base_breakout_point((-5.9008,1.2658),local)
    old_pad=_base_breakout_point((-6.905,0.9916),local)
    scale=p['ro2']/REF_RADII[-1]
    drop=max(0.3787*scale,(p['via']+p['width'])/2+max(0,p['clearance'])+0.03)
    elbow=(old_elbow[0],coil[1])
    via=(elbow[0],elbow[1]+drop)
    upper_pad=_base_breakout_point((-6.905,0.1416),local)
    # Keep a usable gap between square pads even when the winding pitch
    # moves the lower via upward. Only the free terminal endpoint moves.
    pitch=_terminal_pad_size(p)+max(0.15,p['clearance'])
    pad=(old_pad[0],max(old_pad[1]+via[1]-old_via[1],upper_pad[1]+pitch))
    angle=math.radians(p['rotation'])
    def world(q):
        return (p['cx']+q[0]*math.cos(angle)-q[1]*math.sin(angle),
                p['cy']+q[0]*math.sin(angle)+q[1]*math.cos(angle))
    return dict(coil=world(coil),elbow=world(elbow),via=world(via),pad=world(pad))


def _breakout_point(point,p):
    layout=_breakout_layout(p)
    for source,key in (((-5.9695,0.8871),'elbow'),
                       ((-5.9008,1.2658),'via'),((-6.905,0.9916),'pad')):
        if math.dist(point,source)<0.002: return layout[key]
    return _base_breakout_point(point,p)


def _terminal_pad_size(p):
    return max(0.7*p['ro2']/REF_RADII[-1],p['width']+0.2)


def breakout_pads(p):
    """Two aligned front/back SMD terminal pairs; no drill or layer bridge."""
    size=_terminal_pad_size(p)
    pads=[]
    for index,(net,source) in enumerate((('A',(-6.905,0.1416)),('B',(-6.905,0.9916)))):
        for layer in ('F','B'):
            target=selected_layers(p)[layer]
            pads.append(dict(p=_breakout_point(source,p),size=size,rotation=p['rotation'],
                             copper_layer=target,kind='pad' if target in ('F.Cu','B.Cu') else 'rectangle',
                             net=net,layer=layer,number=str(index+1+(2 if layer=='B' else 0))))
    return pads


def terminal_bridges(p):
    pads={pad['number']:pad for pad in breakout_pads(p)}
    return [dict(a=pads['3']['p'],b=pads['4']['p'],layer='B',width=p['width'],
                 net_tie=('3','4'))]


def check_terminal_bridges(tracks,vias,p):
    """Only the intended pad-end joins may touch the bottom copper bridge."""
    for bridge in terminal_bridges(p):
        for t in tracks:
            if t['layer']!=bridge['layer']: continue
            if any(math.dist(t[end],bridge[q])<1e-7 for end in ('a','b') for q in ('a','b')): continue
            if _segments_distance(t['a'],t['b'],bridge['a'],bridge['b'])<p['width']-0.001:
                raise ValueError('바텀 3·4 연결 배선이 인출부의 다른 배선과 겹칩니다. 치수를 조정하세요.')
        for via in vias:
            if _point_to_segment(via['p'],bridge['a'],bridge['b'])<(p['width']+p['via'])/2-0.001:
                raise ValueError('바텀 3·4 연결 배선이 비아와 겹칩니다. 치수를 조정하세요.')


def pad_corners(pad):
    angle=math.radians(pad['rotation']);c=math.cos(angle);s=math.sin(angle)
    h=pad['size']/2;x,y=pad['p']
    return [(x+u*c-v*s,y+u*s+v*c) for u,v in ((-h,-h),(h,-h),(h,h),(-h,h))]


def copper_radius(tracks,vias,p,pads):
    center=(p['cx'],p['cy'])
    return max([math.dist(center,v['p'])+p['via']/2 for v in vias]+
               [math.dist(center,t[end])+p['width']/2 for t in tracks for end in ('a','b')]+
               [math.dist(center,q) for pad in pads for q in pad_corners(pad)])


def _mapped_breakout_paths(component,model,p):
    sources=[]
    for source in _breakout_paths(component,model):
        lower_arc=(component['net']=='B' and component['layer']=='B' and len(source)>2 and
                   math.dist(source[0],(-5.9008,1.2658))<0.002 and
                   math.dist(source[-1],(-5.9695,0.8871))<0.002)
        sources.append([source[0],source[-1]] if lower_arc else source)
    def via_point(v):
        if v['id'].startswith('L'): return _breakout_point((v['x'],v['y']),p)
        j=(p['turns']//2+int(v['id'][1:])-16)%(p['turns']+2)
        return _target_via(j,v['id'][0],p['turns'],p)
    return _component_paths(component,model,p,lambda q:_breakout_point(q,p),via_point,sources)


def parameter_limits(p):
    """Necessary input bounds; full copper clearance still needs build()."""
    def num(value): return format(value,'.6g')
    def interval(low=None,high=None,closed_low=False,closed_high=False):
        parts=[]
        if low is not None: parts.append(num(low)+(' ≤ 값' if closed_low else ' < 값'))
        if high is not None: parts.append(('값 ≤ ' if closed_high else '값 < ')+num(high))
        return ' / '.join(parts) if parts else '유한한 수 · 범위 제한 없음'
    result={key:'유한한 수 · 범위 제한 없음' for key in ('cx','cy','rotation')}
    result['turns']='12~96 · 4의 배수\n비아 간격 조건 추가 적용'
    result['width']='0 < 값 · 배선 간섭 조건 추가 적용'
    minimum=(p['via']+p['width'])/2+max(0,p['clearance'])
    n=p['turns']
    maximum=min(p['ri1']*math.sin(2*math.pi/(n+2)),p['ri1']-p['hole']/2-p['width']/2-max(0,p['clearance'])) if isinstance(n,int) and 12<=n<=96 else None
    result['bend_radius']=('공통 반경 범위 없음 (0은 원본)\n내측 반경/위치 수/비아 크기 조정' if maximum is not None and maximum<=minimum else '0(원본) 또는 '+interval(minimum,maximum,True,False))
    result['hole']=interval(0,2*p['ri1'])+'\n값 ≤ '+num(2*p['ri1']-p['via']-2*p['clearance'])
    result['ri1']=interval(p['hole']/2,p['ri2'])+'\n값 ≥ '+num(p['hole']/2+p['via']/2+p['clearance'])
    result['ri2']=interval(p['ri1'],p['ro1'])
    result['ro1']=interval(p['ri2'],p['ro2'])
    result['ro2']=interval(p['ro1'])
    result['drill']=interval(0,p['via'],False,False)+'\n값 ≤ '+num(p['via']-0.20)
    via_max=min(2*(p['ri1']-p['hole']/2-p['clearance']),
                2*(p['board_margin']-p['clearance']))
    pitch=None
    if isinstance(n,int) and 12<=n<=96 and n%4==0:
        centers=[_target_via(j,kind,n,p) for j in set(_sequence_A(n)+_sequence_B(n))
                 for kind in ('I','O')]
        pitch=min(math.dist(a,b) for i,a in enumerate(centers) for b in centers[i+1:])
        via_max=min(via_max,pitch-p['clearance'])
    if p.get('bend_radius',0)>0:
        via_max=min(via_max,2*(p['bend_radius']-max(0,p['clearance']))-p['width'])
        result['width']=interval(0,2*(p['bend_radius']-max(0,p['clearance']))-p['via'],False,True)+'\n배선 간섭 조건 추가 적용'
        if isinstance(n,int) and 12<=n<=96:
            radius_min=max(p['hole']/2+p['via']/2+p['clearance'],
                           p['bend_radius']/math.sin(2*math.pi/(n+2)),
                           p['hole']/2+p['bend_radius']+p['width']/2+max(0,p['clearance']))
            result['ri1']=interval(radius_min,p['ri2'])
    result['via']=interval(p['drill']+0.20,via_max,True,True)+'\n배선 간섭 조건 추가 적용'
    gap_max=min(p['ri1']-p['hole']/2-p['via']/2,p['board_margin']-p['via']/2)
    if pitch is not None: gap_max=min(gap_max,pitch-p['via'])
    if p.get('bend_radius',0)>0: gap_max=min(gap_max,p['bend_radius']-(p['via']+p['width'])/2)
    result['clearance']=interval(high=gap_max,closed_high=True)+'\n0 이상 권장'
    result['board_margin']=interval(p['via']/2+p['clearance'],closed_low=True)
    return result

def validate(p):
    layers=selected_layers(p)
    if any(name not in copper_layers(64) for name in layers.values()) or layers['F']==layers['B']:
        raise ValueError('서로 다른 두 구리 레이어를 선택하세요.')
    for key in ('net_a','net_b'):
        name=p.get(key,DEFAULTS[key])
        if not isinstance(name,str) or not name.strip() or any(c in name for c in '\r\n\x00'):
            raise ValueError('패드 1·2에 연결할 네트 이름을 입력하거나 선택하세요.')
    if not math.isfinite(p.get('bend_radius',0.385)) or p.get('bend_radius',0.385)<0:
        raise ValueError('굴곡 원호 반경은 0 이상의 유한한 값이어야 합니다.')
    n=p['turns']
    if not isinstance(n,int) or n<12 or n>96 or n%4:
        raise ValueError('권선 위치 수는 12~96, 4의 배수여야 합니다. TI 원본은 32입니다.')
    radius=p.get('bend_radius',0.385)
    if radius>0:
        minimum=(p['via']+p['width'])/2+max(0,p['clearance'])
        maximum=min(p['ri1']*math.sin(2*math.pi/(n+2)),p['ri1']-p['hole']/2-p['width']/2-max(0,p['clearance']))
        if radius<minimum-1e-9:
            raise ValueError('반원·사분원 공통 반경은 %.4f mm 이상이어야 합니다. 비아 외경/트랙 폭/이격을 확인하세요.'%minimum)
        if radius>=maximum-1e-6:
            raise ValueError('공통 반경은 현재 각도에서 %.4f mm 미만이어야 합니다. 내측 1열 반경을 키우거나 공통 반경/위치 수를 줄이세요.'%maximum)
    if not (0<p['hole']/2<p['ri1']<p['ri2']<p['ro1']<p['ro2']):
        raise ValueError('반경: 관통홀/2 < 내측1 < 내측2 < 외측1 < 외측2 이어야 합니다.')
    if p['width']<=0 or p['via']<=0 or p['drill']<=0 or p['drill']>=p['via']:
        raise ValueError('트랙/비아/드릴 크기를 확인하세요.')
    if p['via']-p['drill']<0.20:
        raise ValueError('비아 지름 - 드릴 지름은 0.20mm 이상을 권장합니다.')
    if p['ri1']-p['hole']/2 < p['via']/2+p['clearance']:
        raise ValueError('중앙 구멍과 내측 비아 사이의 간격이 부족합니다.')
    if p['board_margin']<p['via']/2+p['clearance']:
        raise ValueError('PCB 외곽 여유가 비아/간격 요구치보다 작습니다.')
    # Check all 64 (or variable count) physical via centres for overlap.
    slots=n+2
    seq=set(_sequence_A(n)+_sequence_B(n))
    centers=[]
    for j in seq:
        for kind in ['I','O']:
            pt=_target_via(j,kind,n,p)
            for other in centers:
                if math.dist(pt,other)<p['via']+p['clearance']-1e-6:
                    raise ValueError('비아 간격 부족: 원형 간격에 비해 권선 수가 너무 많습니다.')
            centers.append(pt)

def build(p, progress=None):
    def report(value, message):
        if progress is not None: progress(value, message)
    report(0, '입력 치수 검사 중')
    q=dict(DEFAULTS);q.update(p);q['turns']=int(q['turns']);validate(q)
    report(3, '원본 코일 모델 읽는 중')
    model=source_model()
    report(6, '권선 트랙 및 비아 좌표 계산 중')
    if q['turns']==32:tracks,vias=_source_edges(model,q)
    else:tracks,vias=_variable_edges(model,q,lambda message: report(8,message))
    pads=breakout_pads(q)
    check_terminal_bridges(tracks,vias,q)
    min_gap=check_shorts(tracks,vias,q['width'],q['via'],
                         lambda value, message: report(10+value*0.44, message),pads=pads)
    seqA=_sequence_A(q['turns']);seqB=_sequence_B(q['turns']);n=q['turns']
    terminals=({'A_IN':_target_via(seqA[0],'I',n,q), 'A_OUT':_target_via(seqA[-1],'O',n,q),
                'B_IN':_target_via(seqB[0],'O',n,q), 'B_OUT':_target_via(seqB[-1],'I',n,q)})
    if n==32:
        vdict={v['id']:v['p'] for v in vias}
        terminals['A_IN']=vdict['L17'];terminals['B_IN']=vdict['L16']
    else:
        vdict={v['id']:v['p'] for v in vias}
        terminals['A_IN']=vdict['L17'];terminals['B_IN']=vdict['L16']
    report(55, '권선 모델 생성 완료')
    return {'tracks':tracks,'primitives':copper_primitives(tracks),'vias':vias,'pads':pads,
            'bridges':terminal_bridges(q),
            'terminals':terminals,'settings':q,
            'mode':('source-exact' if q['bend_radius']==0 else 'circular-bends') if n==32 else 'parametric',
            'counts':{'A':n//2,'B':n//2}, 'min_cross_net_gap_mm':min_gap}

# --- Fast collision check, using no external geometry package.  Both source
# nets must remain electrically isolated on both copper layers.  Pad-via
# annuli are accounted for.  This rejects geometry that accidentally shorts
# when dimensions change, without enforcing a fabrication clearance that is
# not available from source Gerber files.
def _point_to_segment(q,a,b):
    vx=b[0]-a[0];vy=b[1]-a[1]
    vv=vx*vx+vy*vy
    if vv<=1e-18:return math.dist(q,a)
    t=max(0.0,min(1.0,((q[0]-a[0])*vx+(q[1]-a[1])*vy)/vv))
    return math.hypot(q[0]-(a[0]+t*vx),q[1]-(a[1]+t*vy))

def _segments_distance(a,b,c,d):
    def orient(u,v,w):return (v[0]-u[0])*(w[1]-u[1])-(v[1]-u[1])*(w[0]-u[0])
    oa=orient(a,b,c);ob=orient(a,b,d);oc=orient(c,d,a);od=orient(c,d,b)
    if (oa*ob<0 and oc*od<0):return 0.0
    return min(_point_to_segment(a,c,d),_point_to_segment(b,c,d),
               _point_to_segment(c,a,b),_point_to_segment(d,a,b))

def _shape_distance(a,b):
    # (endpoint1,endpoint2,radius,net,layer)
    p1,p2,ar=a[:3];q1,q2,br=b[:3]
    if p1==p2 and q1==q2:dst=math.dist(p1,q1)
    elif p1==p2:dst=_point_to_segment(p1,q1,q2)
    elif q1==q2:dst=_point_to_segment(q1,p1,p2)
    else:dst=_segments_distance(p1,p2,q1,q2)
    return dst-ar-br

def _pad_shape_distance(pad,shape):
    # A square is a conservative envelope for the slightly rounded SMD pad.
    angle=math.radians(pad['rotation']);c=math.cos(angle);s=math.sin(angle)
    def local(q):
        x,y=q[0]-pad['p'][0],q[1]-pad['p'][1]
        return (x*c+y*s,-x*s+y*c)
    a,b=local(shape[0]),local(shape[1]);h=pad['size']/2
    if any(abs(q[0])<=h and abs(q[1])<=h for q in (a,b)): return -shape[2]
    corners=[(-h,-h),(h,-h),(h,h),(-h,h)]
    return min(_segments_distance(a,b,u,v) for u,v in zip(corners,corners[1:]+corners[:1]))-shape[2]


def check_shorts(tracks,vias,track_width,via_diameter,progress=None,pads=()):
    shapes=[]
    for t in tracks:
        shapes.append((t['a'],t['b'],track_width/2,t['net'],t['layer']))
    for v in vias:
        shapes.extend((v['p'],v['p'],via_diameter/2,v['net'],layer) for layer in ('F','B'))
    cell=1.0; grids={'F':{},'B':{}}
    def cells(shape):
        a,b,r=shape[:3]
        x0=math.floor((min(a[0],b[0])-r)/cell)
        x1=math.floor((max(a[0],b[0])+r)/cell)
        y0=math.floor((min(a[1],b[1])-r)/cell)
        y1=math.floor((max(a[1],b[1])+r)/cell)
        for i in range(x0,x1+1):
            for j in range(y0,y1+1):yield i,j
    for k,s in enumerate(shapes):
        if progress is not None and k%64==0:
            progress(20*k/max(1,len(shapes)), '구리 간섭 검사 준비 중')
        for square in cells(s):grids[s[4]].setdefault(square,[]).append(k)
    seen=set();min_clearance=float('inf')
    for k,s in enumerate(shapes):
        if progress is not None and k%32==0:
            progress(20+80*k/max(1,len(shapes)),
                     '두 권선 간섭 검사 중 (%d/%d)'%(k,len(shapes)))
        candidates=set()
        for square in cells(s):candidates.update(grids[s[4]][square])
        for other_idx in candidates:
            if other_idx<=k:continue
            q=shapes[other_idx]
            if s[3]==q[3]:continue
            dist=_shape_distance(s,q)
            min_clearance=min(min_clearance,dist)
            if dist < -0.001:
                raise ValueError('서로 다른 두 코일의 동박이 %.4fmm 겹칩니다. 치수/턴 수를 조정하세요.'%(-dist))
    for i,pad in enumerate(pads):
        for shape in shapes:
            if shape[3]==pad['net'] or shape[4]!=pad['layer']: continue
            gap=_pad_shape_distance(pad,shape)
            min_clearance=min(min_clearance,gap)
            if gap < -0.001: raise ValueError('인출 패드와 다른 권선의 동박이 겹칩니다. 치수를 조정하세요.')
        for other in pads[i+1:]:
            if other['net']==pad['net'] or other['layer']!=pad['layer']: continue
            corners=pad_corners(other)
            gap=min(_pad_shape_distance(pad,(a,b,0)) for a,b in zip(corners,corners[1:]+corners[:1]))
            min_clearance=min(min_clearance,gap)
            if gap<0.001: raise ValueError('두 인출 패드가 겹치거나 맞닿습니다. 치수를 조정하세요.')
    if progress is not None: progress(100, '두 권선 및 인출 패드 간섭 검사 완료')
    return min_clearance
