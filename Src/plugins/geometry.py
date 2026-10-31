# -*- coding: utf-8 -*-
"""TI TIDA-010971E2.0 Gerber-derived dual-winding PCB Rogowski geometry.

Pure standard Python: unit-testable without pcbnew/wx.
Reference N=32 uses the EXACT GTL/GBL D132 conductor centrelines and
all 66 T01 plated drill centres. Circular source arcs are faceted to
<=0.06mm segment chord before coordinate transforms.
"""
import json
import math
import os

REF_RADII = (2.235, 2.90185, 4.880, 5.265)
REF_STEP = 360.0/34.0
DEFAULTS = dict(cx=100.0,cy=100.0,turns=32,hole=3.0,
                ri1=2.235,ri2=2.90185,ro1=4.880,ro2=5.265,
                width=0.100, via=0.450, drill=0.200, rotation=0.0,
                clearance=0.10, outline=False, board_margin=0.9)

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

def _source_edges(model,param):
    tracks=[]
    for component in model['components']:
        for path in component['paths']:
            tp=[_transform_point(q,param) for q in path]
            for a,b in zip(tp,tp[1:]):
                if math.dist(a,b)>0.000005:
                    tracks.append(dict(a=a,b=b,layer=component['layer'],net=component['net']))
    vias=[]
    for v in model['vias']:
        q=_transform_point((v['x'],v['y']),param)
        vias.append(dict(p=q,net=v['net'],id=v['id']))
    return tracks,vias

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
    x,y=_xy(r,j*360.0/(n+2)+param['rotation'])
    return (param['cx']+x,param['cy']+y)

def _template_long(model,layer,d,parity):
    matches=[]
    for c in model['components']:
        if c['layer']!=layer or len(c['ports'])!=2:continue
        ops=[s for s in c['ports'] if s.startswith('O')]
        ins=[s for s in c['ports'] if s.startswith('I')]
        if not ops or not ins:continue
        o=int(ops[0][1:]);i=int(ins[0][1:])
        if _signed_step(o,i,34)==d and o%2==parity:
            matches.append((c,o,i))
    if not matches:
        raise ValueError('거버 템플릿이 부족합니다: %s delta=%s parity=%s'%(layer,d,parity))
    # Prefer patterns in the less crowded middle of the ring
    return matches[len(matches)//2]

def _warp_template(c, srcO, srcI, tgtO, tgtI, n, param):
    # O/I may be ±4 slots apart. Source radii do not change their ordering.
    src_anchor=srcO*REF_STEP
    tgt_anchor=tgtO*360.0/(n+2)
    # Arc angular extent scales with the number of turns.
    srcdelta=_signed_step(srcO,srcI,34)
    tgtdelta=_signed_step(tgtO,tgtI,n+2)
    assert srcdelta==tgtdelta
    scale=34.0/(n+2)
    tracks=[]
    for path in c['paths']:
        tp=[_transform_point(q,param,angular_scale=scale,anchor=(src_anchor,tgt_anchor)) for q in path]
        for a,b in zip(tp,tp[1:]):
            if math.dist(a,b)>0.000005:
                tracks.append(dict(a=a,b=b,layer=c['layer'],net=c['net']))
    return tracks

def _lead_component(model,net,layer,via_id):
    for c in model['components']:
        if c['layer']==layer and c['net']==net and via_id in c['ports']:
            if via_id.startswith('L') or len(c['ports'])==1 or any(u.startswith('L') for u in c['ports']):return c
    raise ValueError('레퍼런스 리드 경로를 찾지 못했습니다: %s %s %s'%(net,layer,via_id))

def _lead_pair(model,net,first_slot,last_slot,n,param):
    # Rotate the original four lead shapes along with the start/end slots.
    src_first={'A':16,'B':13}[net]
    src_last={'A':15,'B':14}[net]
    desired_first=first_slot*360/(n+2)
    desired_last=last_slot*360/(n+2)
    tracks=[];vias=[]
    first_rotation=desired_first-src_first*REF_STEP
    last_rotation=desired_last-src_last*REF_STEP
    if net=='A':
        lead_components=[('F','L17',first_rotation),('B','L17',first_rotation),('F','O15',last_rotation)]
        lead_id='L17'
    else:
        lead_components=[('B','L16',first_rotation),('F','L16',first_rotation),('B','I14',last_rotation)]
        lead_id='L16'
    for layer,port,rot in lead_components:
        # Find component by unique single-via endpoint.
        c=_lead_component(model,net,layer,port)
        for path in c['paths']:
            tp=[_transform_point(q,param,extra_rotate=rot) for q in path]
            for a,b in zip(tp,tp[1:]):
                if math.dist(a,b)>0.000005:tracks.append(dict(a=a,b=b,layer=layer,net=net))
    source=next(v for v in model['vias'] if v['id']==lead_id)
    via_pos=_transform_point((source['x'],source['y']),param,extra_rotate=first_rotation)
    vias.append(dict(p=via_pos,net=net,id=lead_id))
    return tracks,vias

def _variable_edges(model,param):
    n=param['turns'];tracks=[];vias=[]
    seqs={'A':_sequence_A(n),'B':_sequence_B(n)}
    assert len(set(seqs['A']+seqs['B']))==n
    for net,seq in seqs.items():
        local='B' if net=='A' else 'F'
        long_layer='F' if net=='A' else 'B'
        for j in seq:
            inner=_target_via(j,'I',n,param);outer=_target_via(j,'O',n,param)
            tracks.append(dict(a=inner,b=outer,layer=local,net=net))
            vias.extend([dict(p=inner,net=net,id='I'+str(j)),dict(p=outer,net=net,id='O'+str(j))])
        for j,k in zip(seq,seq[1:]):
            if net=='A':O,I=j,k
            else:O,I=k,j
            d=_signed_step(O,I,n+2)
            tpl,sO,sI=_template_long(model,long_layer,d,O%2)
            for t in _warp_template(tpl,sO,sI,O,I,n,param):
                # Template source net assignment corresponds to the same A/B.
                t['net']=net
                tracks.append(t)
        # For non-reference slot counts keep four ring terminal vias exposed.
        # Reusing the 32-position left breakout causes copper shorts after
        # angular re-spacing, so users must route terminal breakout manually.
        # A: first I / last O; B: first O / last I.
        pass
    return tracks,vias

def validate(p):
    n=p['turns']
    if not isinstance(n,int) or n<12 or n>96 or n%4:
        raise ValueError('권선 위치 수는 12~96, 4의 배수여야 합니다. TI 원본은 32입니다.')
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

def build(p):
    q=dict(DEFAULTS);q.update(p);q['turns']=int(q['turns']);validate(q)
    model=source_model()
    if q['turns']==32:tracks,vias=_source_edges(model,q)
    else:tracks,vias=_variable_edges(model,q)
    min_gap=check_shorts(tracks,vias,q['width'],q['via'])
    seqA=_sequence_A(q['turns']);seqB=_sequence_B(q['turns']);n=q['turns']
    terminals=({'A_IN':_target_via(seqA[0],'I',n,q), 'A_OUT':_target_via(seqA[-1],'O',n,q),
                'B_IN':_target_via(seqB[0],'O',n,q), 'B_OUT':_target_via(seqB[-1],'I',n,q)})
    if n==32:
        vdict={v['id']:v['p'] for v in vias}
        terminals['A_IN']=vdict['L17'];terminals['B_IN']=vdict['L16']
    return {'tracks':tracks,'vias':vias,'terminals':terminals,'settings':q,
            'mode':'source-exact' if n==32 else 'parametric',
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

def check_shorts(tracks,vias,track_width,via_diameter):
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
        for square in cells(s):grids[s[4]].setdefault(square,[]).append(k)
    seen=set();min_clearance=float('inf')
    for k,s in enumerate(shapes):
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
    return min_clearance
