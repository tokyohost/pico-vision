from __future__ import annotations
import math, os, csv, json, shutil, zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple, Dict, Optional

from shapely.geometry import Point, LineString, box
from shapely.ops import unary_union
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Circle

OUT = Path(__file__).resolve().parent / 'build'
GERBER_DIR = OUT / '01_JLCPCB_Order' / 'Gerber'
ORDER_DIR = OUT / '01_JLCPCB_Order'
SRC_DIR = OUT / '02_Source'
DOC_DIR = OUT / '03_Docs'
for d in [GERBER_DIR, ORDER_DIR, SRC_DIR, DOC_DIR]:
    d.mkdir(parents=True, exist_ok=True)

BOARD_W, BOARD_H = 20.0, 30.0
CLEARANCE = 0.20
EDGE_CLEARANCE = 0.25

NETS = {
    'GND': 1, 'LEDA': 2, 'LEDK': 3, 'SDO': 4, 'SDA': 5,
    'CS': 6, 'DC': 7, 'SCL': 8, 'RST': 9, 'VDD': 10,
    'PWM': 11, 'GATE': 12, 'LEDA_FPC': 13,
}

@dataclass
class Pad:
    ref: str
    num: str
    x: float
    y: float
    sx: float
    sy: float
    shape: str  # rect/circle
    net: Optional[str]
    kind: str   # smd/pth/npth/via
    drill: float = 0.0
    layers: Tuple[str, ...] = ('F.Cu',)
    paste: bool = False
    mask: bool = True

@dataclass
class Track:
    net: str
    layer: str
    width: float
    pts: List[Tuple[float,float]]

pads: List[Pad] = []
tracks: List[Track] = []

# ---- Board mechanical ----
# Fixed mechanical definition retained from V10.
HOLE_CENTERS = [(2.5,8.7),(17.5,8.7),(2.5,27.5),(17.5,27.5)]
for i,(x,y) in enumerate(HOLE_CENTERS,1):
    pads.append(Pad(f'H{i}','',x,y,2.2,2.2,'circle',None,'npth',2.2,('F.Cu','B.Cu'),False,True))

# ---- J1: 10P 1.0mm bottom-contact FPC ----
# Finished top view is explicitly left-to-right Pin 1 ... Pin 10.
fpc_nets = ['LEDK','LEDA_FPC','GND','SDO','SDA','CS','DC','SCL','RST','VDD']
for i,net in enumerate(fpc_nets):
    x = 5.5 + i
    pads.append(Pad('J1',str(i+1),x,5.20,0.45,2.30,'rect',net,'smd',0,('F.Cu',),True,True))
# Enlarged exposed copper anchor tabs for easier hand soldering.
# Copper/mask = 2.8 x 2.8 mm; paste is reduced separately to 2.2 x 2.2 mm.
pads.append(Pad('J1','MP1',3.45,4.00,2.80,2.80,'rect','GND','smd',0,('F.Cu',),True,True))
pads.append(Pad('J1','MP2',16.55,4.00,2.80,2.80,'rect',None,'smd',0,('F.Cu',),True,True))

# ---- J2: 2x5 2.54mm breakout ----
xs = [4.92,7.46,10.00,12.54,15.08]
for i,x in enumerate(xs,1):
    pads.append(Pad('J2',str(i),x,21.60,1.80,1.80,'rect' if i==1 else 'circle',
                    ['LEDK','LEDA','GND','SDO','SDA'][i-1],'pth',1.0,('F.Cu','B.Cu'),False,True))
for i,x in enumerate(xs,6):
    pads.append(Pad('J2',str(i),x,24.30,1.80,1.80,'circle',
                    ['CS','DC','SCL','RST','VDD'][i-6],'pth',1.0,('F.Cu','B.Cu'),False,True))

# ---- J3: independent PWM + GND input, using the right-side free area ----
pads.append(Pad('J3','1',17.30,14.00,1.80,1.80,'rect','PWM','pth',1.0,('F.Cu','B.Cu'),False,True))
pads.append(Pad('J3','2',17.30,17.00,1.80,1.80,'circle','GND','pth',1.0,('F.Cu','B.Cu'),False,True))

# ---- PWM and LED components, spread over the centre/right free area ----
# Q1 AO3400A: 1=G, 2=S/GND, 3=D/LED-.  V12 swaps the two
# same-side copper pads to match the verified physical device orientation.
pads.append(Pad('Q1','1',9.00,14.70,1.00,1.10,'rect','GATE','smd',0,('F.Cu',),True,True))
pads.append(Pad('Q1','2',11.00,14.70,1.00,1.10,'rect','GND','smd',0,('F.Cu',),True,True))
pads.append(Pad('Q1','3',10.00,12.70,1.10,1.20,'rect','LEDK','smd',0,('F.Cu',),True,True))
# R1 is separated from Q1 and J3, with a straight PWM path.
pads.append(Pad('R1','1',15.30,14.00,0.80,0.90,'rect','PWM','smd',0,('F.Cu',),True,True))
pads.append(Pad('R1','2',13.30,14.00,0.80,0.90,'rect','GATE','smd',0,('F.Cu',),True,True))
# R2 is vertical and clearly separated from R1/Q1.
pads.append(Pad('R2','1',13.30,16.30,0.90,0.80,'rect','GATE','smd',0,('F.Cu',),True,True))
pads.append(Pad('R2','2',13.30,18.30,0.90,0.80,'rect','GND','smd',0,('F.Cu',),True,True))
# R3=25R directly in the FPC Pin-2 LEDA path, using the left-centre corridor.
pads.append(Pad('R3','1',6.50,9.80,0.90,0.80,'rect','LEDA_FPC','smd',0,('F.Cu',),True,True))
pads.append(Pad('R3','2',6.50,11.80,0.90,0.80,'rect','LEDA','smd',0,('F.Cu',),True,True))

# ---- Vias ----
# LED- branch to Q1 drain goes on B.Cu, keeping it away from R3/GND routing.
pads.append(Pad('VL1','',5.50,8.20,0.80,0.80,'circle','LEDK','via',0.35,('F.Cu','B.Cu'),False,False))
pads.append(Pad('VL2','',8.80,11.00,0.80,0.80,'circle','LEDK','via',0.35,('F.Cu','B.Cu'),False,False))
# SDO changes layer near the right upper hole; SDA uses the far-right edge corridor.
pads.append(Pad('VSDO1','',15.80,9.20,0.70,0.70,'circle','SDO','via',0.30,('F.Cu','B.Cu'),False,False))
pads.append(Pad('VSDO2','',15.80,19.40,0.70,0.70,'circle','SDO','via',0.30,('F.Cu','B.Cu'),False,False))
pads.append(Pad('VSDA1','',9.50,7.00,0.70,0.70,'circle','SDA','via',0.30,('F.Cu','B.Cu'),False,False))
pads.append(Pad('VSDA2','',19.00,19.00,0.70,0.70,'circle','SDA','via',0.30,('F.Cu','B.Cu'),False,False))
pads.append(Pad('VGMP1','',3.45,6.00,0.70,0.70,'circle','GND','via',0.30,('F.Cu','B.Cu'),False,False))
pads.append(Pad('VGMP2','',7.50,7.00,0.70,0.70,'circle','GND','via',0.30,('F.Cu','B.Cu'),False,False))
# V12 source crossover: GATE stays entirely on F.Cu; a short local GND
# bridge on B.Cu lets Q1 pin 2 reach R2/J3 ground without crossing GATE.
pads.append(Pad('VQ1S1','',12.30,15.50,0.70,0.70,'circle','GND','via',0.30,('F.Cu','B.Cu'),False,False))
pads.append(Pad('VQ1S2','',12.30,17.20,0.70,0.70,'circle','GND','via',0.30,('F.Cu','B.Cu'),False,False))
# FPC pins 6..10 fan out to ordered bottom-layer corridors.
for idx, (x,net) in enumerate(zip([10.5,11.5,12.5,13.5,14.5], ['CS','DC','SCL','RST','VDD'])):
    pads.append(Pad(f'V{idx+1}','',x,7.00,0.70,0.70,'circle',net,'via',0.30,('F.Cu','B.Cu'),False,False))
    tracks.append(Track(net,'F.Cu',0.30,[(x,6.35),(x,7.00)]))

# ---- Top routing: power/backlight and local PWM ----
tracks += [
    # LED- main breakout path, with a short B.Cu branch to Q1 drain.
    Track('LEDK','F.Cu',0.60,[(5.50,6.35),(5.50,21.00),(4.92,21.60)]),
    Track('LEDK','F.Cu',0.60,[(5.50,6.35),(5.50,8.20)]),
    Track('LEDK','B.Cu',0.60,[(5.50,8.20),(6.10,8.80),(8.20,8.80),(8.80,9.40),(8.80,11.00)]),
    Track('LEDK','F.Cu',0.60,[(8.80,11.00),(10.00,12.70)]),

    # FPC Pin 2 -> R3 25R -> J2 Pin 2.
    Track('LEDA_FPC','F.Cu',0.30,[(6.50,6.35),(6.50,9.80)]),
    Track('LEDA','F.Cu',0.30,[(6.50,11.80),(6.50,19.80),(7.46,20.76),(7.46,21.60)]),

    # FPC Pin 3 GND, Q1 source, R2, J3 and J2 Pin 3.
    Track('GND','F.Cu',0.60,[(7.50,6.35),(7.50,18.00),(10.00,19.00),(10.00,21.60)]),
    Track('GND','F.Cu',0.60,[(10.00,19.00),(10.00,18.30),(13.30,18.30)]),
    Track('GND','F.Cu',0.30,[(11.00,14.70),(11.55,15.25),(12.30,15.50)]),
    Track('GND','B.Cu',0.30,[(12.30,15.50),(12.30,17.20)]),
    Track('GND','F.Cu',0.30,[(12.30,17.20),(12.30,17.30),(13.30,18.30)]),
    Track('GND','F.Cu',0.60,[(13.30,18.30),(16.00,18.30),(17.30,17.00)]),

    # Enlarged left FPC anchor is tied to GND through two small vias on B.Cu.
    Track('GND','F.Cu',0.60,[(3.45,4.00),(3.45,6.00)]),
    Track('GND','B.Cu',0.60,[(3.45,6.00),(3.45,7.00),(7.50,7.00)]),
    Track('GND','F.Cu',0.60,[(7.50,7.00),(7.50,6.35)]),

    # SDO top fanout to the right-side via; target approach returns to top near J2.
    Track('SDO','F.Cu',0.30,[(8.50,6.35),(8.50,7.80),(15.20,7.80),(15.80,8.40),(15.80,9.20)]),
    Track('SDO','B.Cu',0.25,[(15.80,9.20),(15.80,19.40)]),
    Track('SDO','F.Cu',0.30,[(15.80,19.40),(15.20,20.00),(13.20,20.00),(12.54,20.66),(12.54,21.60)]),

    # SDA uses the far-right B.Cu edge corridor, clear of the upper mounting hole.
    Track('SDA','F.Cu',0.30,[(9.50,6.35),(9.50,7.00)]),
    Track('SDA','B.Cu',0.25,[(9.50,7.00),(9.50,6.20),(19.00,6.20),(19.00,19.00)]),
    Track('SDA','F.Cu',0.30,[(19.00,19.00),(19.00,20.60),(16.00,20.60),(15.08,21.52),(15.08,21.60)]),

    # PWM local circuit, kept compact but with generous component spacing.
    Track('PWM','F.Cu',0.30,[(17.30,14.00),(15.30,14.00)]),
    Track('GATE','F.Cu',0.30,[(9.00,14.70),(9.00,16.30),(13.30,16.30)]),
    Track('GATE','F.Cu',0.30,[(13.30,14.00),(13.30,16.30)]),
]

# ---- Bottom routes pins 6..10 ----
# Vias first drop vertically below the SDA corridor, then fan out as five ordered,
# non-crossing 45-degree channels between the J2 columns.
source_xs = [10.5,11.5,12.5,13.5,14.5]
trunk_xs = [3.30,6.19,8.73,11.27,13.81]
target_xs = xs
for net, sx, tx, target in zip(['CS','DC','SCL','RST','VDD'],source_xs,trunk_xs,target_xs):
    fan_y = 11.00 + abs(sx-tx)
    approach_y = 24.30 - abs(target-tx)
    pts=[(sx,7.00),(sx,11.00),(tx,fan_y),(tx,approach_y),(target,24.30)]
    tracks.append(Track(net,'B.Cu',0.25,pts))

# ---- Geometry helpers ----
def pad_geom(p: Pad):
    if p.shape == 'circle':
        return Point(p.x,p.y).buffer(p.sx/2, resolution=48)
    return box(p.x-p.sx/2,p.y-p.sy/2,p.x+p.sx/2,p.y+p.sy/2)

def track_geoms(t: Track):
    geoms=[]
    for a,b in zip(t.pts,t.pts[1:]):
        geoms.append(LineString([a,b]).buffer(t.width/2, cap_style=1, join_style=1, resolution=16))
    return geoms

# ---- DRC ----
items_by_layer: Dict[str,List[Tuple[str,str,object]]] = {'F.Cu':[],'B.Cu':[]}
for p in pads:
    if p.kind == 'npth' or p.net is None:
        continue
    for layer in p.layers:
        if layer in items_by_layer:
            items_by_layer[layer].append((p.net,f'{p.ref}.{p.num}',pad_geom(p)))
for ti,t in enumerate(tracks):
    for si,g in enumerate(track_geoms(t)):
        items_by_layer[t.layer].append((t.net,f'T{ti}.{si}',g))

drc_errors=[]
for layer,items in items_by_layer.items():
    for i in range(len(items)):
        n1,name1,g1=items[i]
        for j in range(i+1,len(items)):
            n2,name2,g2=items[j]
            if n1==n2: continue
            dist=g1.distance(g2)
            if dist < CLEARANCE - 1e-6:
                drc_errors.append(f'{layer}: {name1}({n1}) to {name2}({n2}) clearance {dist:.3f}mm < {CLEARANCE:.2f}mm')

# edge checks for copper
board_inner = box(EDGE_CLEARANCE,EDGE_CLEARANCE,BOARD_W-EDGE_CLEARANCE,BOARD_H-EDGE_CLEARANCE)
for layer,items in items_by_layer.items():
    for net,name,g in items:
        if not board_inner.covers(g):
            drc_errors.append(f'{layer}: {name}({net}) violates {EDGE_CLEARANCE:.2f}mm copper-edge clearance')

# NPTH hole to copper clearance
holes=[p for p in pads if p.kind=='npth']
for h in holes:
    hg=Point(h.x,h.y).buffer(h.drill/2,resolution=48)
    for layer,items in items_by_layer.items():
        for net,name,g in items:
            dist=hg.distance(g)
            if dist < CLEARANCE - 1e-6:
                drc_errors.append(f'{layer}: {name}({net}) to {h.ref} NPTH clearance {dist:.3f}mm < {CLEARANCE:.2f}mm')

# connectivity graph per net across layers
# nodes are individual shapes; edges touch/overlap on same layer, plus via/PTH cross-layer bridges
from collections import defaultdict, deque
net_nodes=defaultdict(list)
for layer,items in items_by_layer.items():
    for net,name,g in items:
        net_nodes[net].append((layer,name,g))

connectivity_errors=[]
required_refs=defaultdict(list)
for p in pads:
    if p.net and p.kind!='via' and p.net is not None:
        required_refs[p.net].append(f'{p.ref}.{p.num}')

for net,nodes in net_nodes.items():
    adj=[set() for _ in nodes]
    for i in range(len(nodes)):
        li,ni,gi=nodes[i]
        for j in range(i+1,len(nodes)):
            lj,nj,gj=nodes[j]
            connected=False
            if li==lj and gi.distance(gj)<1e-5:
                connected=True
            # bridge the F/B representations of the same PTH/via pad
            if ni==nj and li!=lj:
                connected=True
            if connected:
                adj[i].add(j); adj[j].add(i)
    # start from first required terminal if present
    req=required_refs.get(net,[])
    if not req: continue
    start=None
    for i,(_,name,_) in enumerate(nodes):
        if name==req[0]: start=i; break
    if start is None:
        connectivity_errors.append(f'{net}: missing terminal {req[0]}')
        continue
    seen={start}; q=deque([start])
    while q:
        a=q.popleft()
        for b in adj[a]:
            if b not in seen:
                seen.add(b); q.append(b)
    for r in req[1:]:
        idxs=[i for i,(_,name,_) in enumerate(nodes) if name==r]
        if not idxs or not any(i in seen for i in idxs):
            connectivity_errors.append(f'{net}: terminal {r} not connected to {req[0]}')

# ---- Gerber generation ----
def fmt(v: float) -> str:
    return f'{int(round(v*1_000_000)):09d}'

# Convert board/KiCad +Y-down coordinates to CAM/Gerber +Y-up coordinates.
# Every manufacturing layer and drill file uses this same transform.
def gerber_y(y: float) -> float:
    return BOARD_H - y

def write_gerber(path: Path, title: str, layer: str, include_pads=True, include_tracks=True, mask=False, paste=False):
    # unique apertures
    apertures=[]; amap={}
    def add_ap(shape, sx, sy=None):
        key=(shape,round(sx,6),round(sy if sy is not None else sx,6))
        if key not in amap:
            code=10+len(apertures)
            amap[key]=code; apertures.append((code,*key))
        return amap[key]

    padlist=[]
    if include_pads:
        for p in pads:
            if p.kind=='npth' and not mask: continue
            if mask:
                if not p.mask or p.kind=='via': continue
                if p.kind=='npth':
                    sx=sy=p.drill+0.40
                else:
                    # all PTH openings on both masks; SMD only on own layer
                    if p.kind=='smd' and layer not in p.layers: continue
                    if p.kind=='pth' and layer not in p.layers: continue
                    ex=0.10
                    sx,sy=p.sx+ex,p.sy+ex
            elif paste:
                if not p.paste or layer not in p.layers: continue
                # controlled paste reduction for widened fine-pitch FPC pads
                if p.ref=='J1' and p.num in ('MP1','MP2'):
                    sx,sy=2.20,2.20
                else:
                    red=0.03 if p.ref=='J1' and p.num.isdigit() else 0.0
                    sx,sy=max(0.1,p.sx-red),max(0.1,p.sy-red)
            else:
                if layer not in p.layers: continue
                sx,sy=p.sx,p.sy
            shape='C' if p.shape=='circle' else 'R'
            code=add_ap(shape,sx,sy)
            padlist.append((code,p.x,p.y))
    tracklist=[]
    if include_tracks and not mask and not paste:
        for t in tracks:
            if t.layer!=layer: continue
            code=add_ap('C',t.width,t.width)
            tracklist.append((code,t.pts))

    with open(path,'w',encoding='ascii') as f:
        f.write(f'G04 {title}*\n%FSLAX36Y36*%\n%MOMM*%\n%LPD*%\n')
        for code,shape,sx,sy in apertures:
            if shape=='C': f.write(f'%ADD{code}C,{sx:.6f}*%\n')
            else: f.write(f'%ADD{code}R,{sx:.6f}X{sy:.6f}*%\n')
        f.write('G01*\n')
        for code,x,y in padlist:
            f.write(f'D{code}*\nX{fmt(x)}Y{fmt(gerber_y(y))}D03*\n')
        for code,pts in tracklist:
            f.write(f'D{code}*\nX{fmt(pts[0][0])}Y{fmt(gerber_y(pts[0][1]))}D02*\n')
            for x,y in pts[1:]: f.write(f'X{fmt(x)}Y{fmt(gerber_y(y))}D01*\n')
        f.write('M02*\n')

# Continuous single-line technical font for silkscreen.
# Unlike the V2 pixel font, every character uses long connected strokes, which
# stays legible after fab silkscreen expansion and anti-aliasing.
GLYPHS = {
'0': [[(0.15,0.0),(0.0,0.15),(0.0,0.85),(0.15,1.0),(0.55,1.0),(0.70,0.85),(0.70,0.15),(0.55,0.0),(0.15,0.0)]],
'1': [[(0.15,0.78),(0.35,1.0),(0.35,0.0)],[(0.12,0.0),(0.60,0.0)]],
'2': [[(0.0,0.80),(0.15,1.0),(0.55,1.0),(0.70,0.82),(0.70,0.62),(0.0,0.0),(0.70,0.0)]],
'3': [[(0.0,1.0),(0.55,1.0),(0.70,0.85),(0.70,0.62),(0.52,0.50),(0.70,0.38),(0.70,0.15),(0.55,0.0),(0.0,0.0)]],
'4': [[(0.58,0.0),(0.58,1.0)],[(0.58,0.48),(0.0,0.48),(0.42,1.0)]],
'5': [[(0.70,1.0),(0.0,1.0),(0.0,0.52),(0.55,0.52),(0.70,0.38),(0.70,0.15),(0.55,0.0),(0.0,0.0)]],
'6': [[(0.65,0.88),(0.55,1.0),(0.15,1.0),(0.0,0.82),(0.0,0.15),(0.15,0.0),(0.55,0.0),(0.70,0.15),(0.70,0.38),(0.55,0.52),(0.0,0.52)]],
'7': [[(0.0,1.0),(0.70,1.0),(0.18,0.0)]],
'8': [[(0.15,0.50),(0.0,0.65),(0.0,0.85),(0.15,1.0),(0.55,1.0),(0.70,0.85),(0.70,0.65),(0.55,0.50),(0.15,0.50),(0.0,0.35),(0.0,0.15),(0.15,0.0),(0.55,0.0),(0.70,0.15),(0.70,0.35),(0.55,0.50)]],
'9': [[(0.05,0.12),(0.15,0.0),(0.55,0.0),(0.70,0.18),(0.70,0.85),(0.55,1.0),(0.15,1.0),(0.0,0.85),(0.0,0.62),(0.15,0.48),(0.70,0.48)]],
'A': [[(0.0,0.0),(0.30,1.0),(0.60,0.0)],[(0.12,0.45),(0.48,0.45)]],
'C': [[(0.70,0.85),(0.55,1.0),(0.15,1.0),(0.0,0.85),(0.0,0.15),(0.15,0.0),(0.55,0.0),(0.70,0.15)]],
'D': [[(0.0,0.0),(0.0,1.0),(0.42,1.0),(0.65,0.78),(0.65,0.22),(0.42,0.0),(0.0,0.0)]],
'F': [[(0.0,0.0),(0.0,1.0),(0.70,1.0)],[(0.0,0.52),(0.52,0.52)]],
'G': [[(0.70,0.80),(0.55,1.0),(0.15,1.0),(0.0,0.82),(0.0,0.15),(0.15,0.0),(0.55,0.0),(0.70,0.15),(0.70,0.48),(0.38,0.48)]],
'I': [[(0.0,1.0),(0.60,1.0)],[(0.30,1.0),(0.30,0.0)],[(0.0,0.0),(0.60,0.0)]],
'M': [[(0.0,0.0),(0.0,1.0),(0.38,0.52),(0.76,1.0),(0.76,0.0)]],
'N': [[(0.0,0.0),(0.0,1.0),(0.70,0.0),(0.70,1.0)]],
'P': [[(0.0,0.0),(0.0,1.0),(0.52,1.0),(0.70,0.82),(0.70,0.62),(0.52,0.48),(0.0,0.48)]],
'Q': [[(0.15,0.0),(0.0,0.15),(0.0,0.85),(0.15,1.0),(0.55,1.0),(0.70,0.85),(0.70,0.15),(0.55,0.0),(0.15,0.0)],[(0.42,0.25),(0.75,-0.08)]],
'R': [[(0.0,0.0),(0.0,1.0),(0.52,1.0),(0.70,0.82),(0.70,0.62),(0.52,0.48),(0.0,0.48)],[(0.38,0.48),(0.72,0.0)]],
'V': [[(0.0,1.0),(0.34,0.0),(0.68,1.0)]],
'W': [[(0.0,1.0),(0.18,0.0),(0.45,0.55),(0.72,0.0),(0.90,1.0)]],
'-': [[(0.0,0.50),(0.60,0.50)]],
'/': [[(0.0,0.0),(0.65,1.0)]],
' ': [],
}
GLYPH_WIDTH = {'M':0.76,'W':0.90,' ':0.35}

def text_segments(text, x, y, h=0.75, align='left', tracking=0.22):
    text=text.upper()
    widths=[GLYPH_WIDTH.get(ch,0.70) for ch in text]
    total=(sum(widths) + tracking*max(0,len(widths)-1))*h
    if align=='center': x-=total/2
    elif align=='right': x-=total
    segs=[]
    cx=x
    for ch,w in zip(text,widths):
        for stroke in GLYPHS.get(ch,[]):
            if len(stroke)<2: continue
            for a,b in zip(stroke,stroke[1:]):
                segs.append(((cx+a[0]*h,y+(1-a[1])*h),(cx+b[0]*h,y+(1-b[1])*h)))
        cx+=(w+tracking)*h
    return segs

SILK_W = 0.12
silk=[]
silk += text_segments('FPC10 PWM V12',10.0,0.24,0.58,'center',0.17)
silk += text_segments('FPC IN',10.0,1.28,0.68,'center',0.18)
silk += text_segments('1',5.05,1.45,0.48,'center',0.14)
silk += text_segments('10',14.95,1.45,0.48,'center',0.14)
# Pin-1 marker and enlarged FPC body outline.
silk += [((4.90,6.72),(4.38,6.72)),((4.38,6.72),(4.38,7.22)),((4.38,7.22),(4.56,7.04))]
silk += [((1.90,2.35),(18.10,2.35)),((1.90,2.35),(1.90,6.55)),((18.10,2.35),(18.10,6.55)),
         ((1.90,6.55),(18.10,6.55)),((10.0,2.15),(10.0,1.86)),((10.0,1.86),(9.68,2.10)),((10.0,1.86),(10.32,2.10))]
# References are placed in dedicated empty areas outside component pads/bodies.
silk += text_segments('R3',4.35,10.45,0.56,'center',0.18)
silk += text_segments('Q1',9.95,15.75,0.58,'center',0.18)
silk += text_segments('R1',14.30,12.55,0.58,'center',0.18)
silk += text_segments('R2',11.75,16.95,0.58,'center',0.18)
silk += text_segments('PWM',17.00,11.35,0.50,'center',0.16)
silk += text_segments('G',18.65,16.45,0.48,'center',0.16)
# J2 numbering.
for i,x in enumerate(xs,1):
    silk += text_segments(str(i),x,22.73,0.40,'center',0.12)
for i,x in enumerate(xs,6):
    silk += text_segments(str(i),x,25.55,0.58,'center',0.14)
# No component body outlines: references remain fully readable after assembly.

# silk keepout against mask openings: drop line segments that intersect expanded pad masks
mask_keep=[]
for p in pads:
    if p.kind=='npth' or p.kind=='via' or not p.mask: continue
    g=pad_geom(Pad(p.ref,p.num,p.x,p.y,p.sx+0.20,p.sy+0.20,p.shape,p.net,p.kind,p.drill,p.layers,p.paste,p.mask))
    mask_keep.append(g)
mask_union=unary_union(mask_keep)
filtered_silk=[]
for a,b in silk:
    g=LineString([a,b]).buffer(SILK_W/2,cap_style=2)
    if not g.intersects(mask_union): filtered_silk.append((a,b))
silk=filtered_silk

def write_silk(path: Path, title: str):
    with open(path,'w',encoding='ascii') as f:
        f.write(f'G04 {title}*\n%FSLAX36Y36*%\n%MOMM*%\n%LPD*%\n%ADD10C,{SILK_W:.6f}*%\nG01*\nD10*\n')
        for a,b in silk:
            f.write(f'X{fmt(a[0])}Y{fmt(gerber_y(a[1]))}D02*\nX{fmt(b[0])}Y{fmt(gerber_y(b[1]))}D01*\n')
        f.write('M02*\n')

# Generate Gerber files
base='FPC10_PWM_20x30_V12'
write_gerber(GERBER_DIR/f'{base}-F_Cu.gtl',f'{base} Top Copper','F.Cu')
write_gerber(GERBER_DIR/f'{base}-B_Cu.gbl',f'{base} Bottom Copper','B.Cu')
write_gerber(GERBER_DIR/f'{base}-F_Mask.gts',f'{base} Top Mask','F.Cu',include_tracks=False,mask=True)
write_gerber(GERBER_DIR/f'{base}-B_Mask.gbs',f'{base} Bottom Mask','B.Cu',include_tracks=False,mask=True)
write_gerber(GERBER_DIR/f'{base}-F_Paste.gtp',f'{base} Top Paste','F.Cu',include_tracks=False,paste=True)
write_silk(GERBER_DIR/f'{base}-F_Silkscreen.gto',f'{base} Top Silkscreen')
# empty bottom silk
(GERBER_DIR/f'{base}-B_Silkscreen.gbo').write_text(f'G04 {base} Bottom Silkscreen*\n%FSLAX36Y36*%\n%MOMM*%\n%LPD*%\nG01*\nM02*\n',encoding='ascii')
# edge cuts
(GERBER_DIR/f'{base}-Edge_Cuts.gko').write_text(
    f'G04 {base} Board Outline 20x30mm*\n%FSLAX36Y36*%\n%MOMM*%\n%LPD*%\n%ADD10C,0.100000*%\nG01*\nD10*\n'
    f'X{fmt(0)}Y{fmt(gerber_y(0))}D02*\nX{fmt(20)}Y{fmt(gerber_y(0))}D01*\nX{fmt(20)}Y{fmt(gerber_y(30))}D01*\nX{fmt(0)}Y{fmt(gerber_y(30))}D01*\nX{fmt(0)}Y{fmt(gerber_y(0))}D01*\nM02*\n',encoding='ascii')

# drills
pth1=[p for p in pads if p.kind=='pth']
vias=[p for p in pads if p.kind=='via']
with open(GERBER_DIR/f'{base}-PTH.drl','w',encoding='ascii') as f:
    f.write(f'M48\n; PTH drill for {base}\nFMAT,2\nMETRIC,TZ\nG90\nT01C1.000\nT02C0.300\n%\nG05\nT01\n')
    for p in pth1: f.write(f'X{p.x:.3f}Y{gerber_y(p.y):.3f}\n')
    f.write('T02\n')
    for p in vias: f.write(f'X{p.x:.3f}Y{gerber_y(p.y):.3f}\n')
    f.write('T00\nM30\n')
with open(GERBER_DIR/f'{base}-NPTH.drl','w',encoding='ascii') as f:
    f.write(f'M48\n; NPTH drill for {base}\nFMAT,2\nMETRIC,TZ\nG90\nT01C2.200\n%\nG05\nT01\n')
    for p in holes: f.write(f'X{p.x:.3f}Y{gerber_y(p.y):.3f}\n')
    f.write('T00\nM30\n')

# ---- KiCad PCB source ----
def kpad(p: Pad) -> str:
    netstr = f' (net {NETS[p.net]} "{p.net}")' if p.net else ''
    if p.kind=='smd':
        
        if p.ref=='J1' and p.num in ('MP1','MP2'):
            aperture_margins = ' (solder_paste_margin -0.300) (solder_mask_margin 0.050)'
        elif p.ref=='J1' and p.num.isdigit():
            aperture_margins = ' (solder_paste_margin -0.015) (solder_mask_margin 0.050)'
        else:
            aperture_margins = ''
        return f'    (pad "{p.num}" smd {"circle" if p.shape=="circle" else "rect"} (at {p.x:.3f} {p.y:.3f}) (size {p.sx:.3f} {p.sy:.3f}) (layers "F.Cu" "F.Paste" "F.Mask"){aperture_margins}{netstr})\n'
    if p.kind=='pth':
        return f'    (pad "{p.num}" thru_hole {"circle" if p.shape=="circle" else "rect"} (at {p.x:.3f} {p.y:.3f}) (size {p.sx:.3f} {p.sy:.3f}) (drill {p.drill:.3f}) (layers "*.Cu" "*.Mask"){netstr})\n'
    if p.kind=='npth':
        return f'    (pad "" np_thru_hole circle (at {p.x:.3f} {p.y:.3f}) (size {p.drill:.3f} {p.drill:.3f}) (drill {p.drill:.3f}) (layers "*.Cu" "*.Mask"))\n'
    return ''

byref=defaultdict(list)
for p in pads:
    if p.kind!='via': byref[p.ref].append(p)
values={'J1':'F-FPC1M10P-C310','J2':'2x5 2.54mm Breakout','J3':'PWM/GND','R1':'100R','R2':'10K','R3':'25R','Q1':'AO3400A',
        'H1':'M2.2','H2':'M2.2','H3':'M2.2','H4':'M2.2'}
footprints=[]
for ref,plist in byref.items():
    footprints.append(f'  (footprint "Custom:{ref}" (layer "F.Cu") (at 0 0)\n')
    # safe reference/value positions mostly in fab, not silk
    px=sum(p.x for p in plist)/len(plist); py=sum(p.y for p in plist)/len(plist)
    footprints.append(f'    (property "Reference" "{ref}" (at {px:.3f} {py:.3f}) (layer "F.Fab") hide)\n')
    footprints.append(f'    (property "Value" "{values.get(ref,ref)}" (at {px:.3f} {py+1.5:.3f}) (layer "F.Fab") hide)\n')
    if ref=='J1': footprints.append('    (property "LCSC" "C132509")\n')
    if ref=='R1': footprints.append('    (property "LCSC" "C22775")\n')
    if ref=='R2': footprints.append('    (property "LCSC" "C25804")\n')
    if ref=='Q1': footprints.append('    (property "LCSC" "C20917")\n')
    for p in plist: footprints.append(kpad(p))
    footprints.append('  )\n')

kicad=[]
kicad.append('(kicad_pcb (version 20221018) (generator pcbnew)\n')
kicad.append('  (general (thickness 1.6))\n  (paper "A4")\n')
kicad.append('  (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (36 "B.SilkS" user "b.silkscreen") (37 "F.SilkS" user "f.silkscreen") (44 "Edge.Cuts" user) (48 "B.Fab" user) (49 "F.Fab" user))\n')
kicad.append('  (setup (pad_to_mask_clearance 0))\n')
for n,i in NETS.items(): kicad.append(f'  (net {i} "{n}")\n')
kicad.extend(footprints)
for p in vias:
    kicad.append(f'  (via (at {p.x:.3f} {p.y:.3f}) (size {p.sx:.3f}) (drill {p.drill:.3f}) (layers "F.Cu" "B.Cu") (net {NETS[p.net]}))\n')
for t in tracks:
    for a,b in zip(t.pts,t.pts[1:]):
        kicad.append(f'  (segment (start {a[0]:.3f} {a[1]:.3f}) (end {b[0]:.3f} {b[1]:.3f}) (width {t.width:.3f}) (layer "{t.layer}") (net {NETS[t.net]}))\n')
kicad.append('  (gr_rect (start 0 0) (end 20.000 30.000) (stroke (width 0.100) (type default)) (fill none) (layer "Edge.Cuts"))\n')
for a,b in silk:
    kicad.append(f'  (gr_line (start {a[0]:.3f} {a[1]:.3f}) (end {b[0]:.3f} {b[1]:.3f}) (stroke (width {SILK_W:.3f}) (type default)) (layer "F.SilkS"))\n')
kicad.append(')\n')
(SRC_DIR/f'{base}.kicad_pcb').write_text(''.join(kicad),encoding='utf-8')

# Copy generator source itself

if Path(__file__).resolve() != (SRC_DIR/'generate_board.py').resolve():
    shutil.copy2(__file__, SRC_DIR/'generate_board.py')

# ---- BOM/CPL/pinout ----
with open(ORDER_DIR/'BOM_JLCPCB.csv','w',newline='',encoding='utf-8-sig') as f:
    w=csv.writer(f); w.writerow(['Comment','Designator','Footprint','LCSC Part #','Manufacturer Part','Qty','Assembly','Notes'])
    w.writerow(['10P 1.0mm FPC Bottom Contact, edge-facing','J1','F-FPC1M10P-C310','C132509','F-FPC1M10P-C310',1,'SMT','0.3mm FPC, bottom contact; cable entry faces board edge; 0.45x2.30mm signal pads; enlarged 2.8x2.8mm anchor copper'])
    w.writerow(['AO3400A','Q1','SOT-23','C20917','AO3400A',1,'SMT','Low-side LED- PWM MOSFET; FPC pin 1'])
    w.writerow(['100R','R1','0603','C22775','0603WAF1000T5E',1,'SMT','MOSFET gate series resistor'])
    w.writerow(['10K','R2','0603','C25804','0603WAF1002T5E',1,'SMT','Gate pulldown, default off'])
    w.writerow(['25R','R3','0603','DNP','Generic 25 ohm 0603',1,'Hand solder','Series resistor between FPC pin 2 and LEDA breakout; select 25 ohm'])
    w.writerow(['2x5 2.54mm header','J2','PinHeader_2x05_P2.54mm','DNP','Generic',1,'Hand solder','10-pin 1:1 breakout'])
    w.writerow(['1x2 2.54mm header','J3','PinHeader_1x02_P2.54mm','DNP','Generic',1,'Hand solder','PWM + GND input'])
with open(ORDER_DIR/'CPL_JLCPCB.csv','w',newline='',encoding='utf-8-sig') as f:
    w=csv.writer(f); w.writerow(['Designator','Mid X','Mid Y','Layer','Rotation'])
    w.writerow(['J1','10.000mm','4.600mm','Top','180'])
    w.writerow(['Q1','10.000mm','13.900mm','Top','270'])
    w.writerow(['R1','14.300mm','14.000mm','Top','0'])
    w.writerow(['R2','13.300mm','17.300mm','Top','90'])
    w.writerow(['R3','6.500mm','10.800mm','Top','90'])
with open(DOC_DIR/'PINOUT.csv','w',newline='',encoding='utf-8-sig') as f:
    w=csv.writer(f); w.writerow(['Pin','J1 FPC','J2 Breakout','Function / Note'])
    rows=[
        (1,'LEDK','LEDK','Backlight cathode / LED-; also connected to Q1 drain'),(2,'LEDA via R3=25R','LEDA','Backlight anode; FPC pin 2 is connected to J2 pin 2 through R3=25 ohm'),
        (3,'GND','GND','Logic/power ground; adjacent to LED- on the original board'),(4,'SDO','SDO','LCD serial data output / NC if unused'),
        (5,'SDA','SDA','SPI MOSI'),(6,'CS','CS','Chip select'),(7,'DC','DC','Data/command'),
        (8,'SCL','SCL','SPI clock'),(9,'RESET','RST','LCD reset'),(10,'VDD','VDD','LCD logic supply, nominal 3.3V'),
    ]
    w.writerows(rows)
    w.writerow([]); w.writerow(['J3-1','PWM','','3.3V logic PWM input through R1=100R'])
    w.writerow(['J3-2','GND','','PWM reference ground'])

# ---- Preview ----
def render(layer='F.Cu', path=None):
    fig,ax=plt.subplots(figsize=(5,7.5),dpi=180)
    ax.add_patch(Rectangle((0,0),BOARD_W,BOARD_H,facecolor='#0b5f3c',edgecolor='black',lw=1.2))
    # holes
    for h in holes:
        ax.add_patch(Circle((h.x,h.y),h.drill/2,facecolor='white',edgecolor='black',lw=.5))
    # tracks
    for t in tracks:
        if t.layer!=layer: continue
        xs2=[p[0] for p in t.pts]; ys2=[p[1] for p in t.pts]
        ax.plot(xs2,ys2,color='#d5a642',lw=t.width*4.2,solid_capstyle='round',solid_joinstyle='round')
    # pads
    for p in pads:
        if p.kind=='npth' or layer not in p.layers: continue
        if p.shape=='circle':
            ax.add_patch(Circle((p.x,p.y),p.sx/2,facecolor='#d5a642',edgecolor='#7f601f',lw=.3))
        else:
            ax.add_patch(Rectangle((p.x-p.sx/2,p.y-p.sy/2),p.sx,p.sy,facecolor='#d5a642',edgecolor='#7f601f',lw=.3))
        if p.kind in ('pth','via'):
            ax.add_patch(Circle((p.x,p.y),p.drill/2,facecolor='white',edgecolor='black',lw=.25))
    if layer=='F.Cu':
        for a,b in silk:
            ax.plot([a[0],b[0]],[a[1],b[1]],color='white',lw=0.85,solid_capstyle='round',solid_joinstyle='round')
    ax.set_xlim(-.5,20.5); ax.set_ylim(30.5,-.5); ax.set_aspect('equal'); ax.axis('off')
    ax.set_title('Top Copper + redistributed placement' if layer=='F.Cu' else 'Bottom Copper routing',fontsize=9)
    fig.tight_layout(pad=.3)
    fig.savefig(path,bbox_inches='tight'); plt.close(fig)
render('F.Cu',DOC_DIR/'preview_top.png')
render('B.Cu',DOC_DIR/'preview_bottom.png')

# Render transformed CAM coordinates with +Y upward. This directly verifies
# that the manufacturing files display readable, non-mirrored top silkscreen.
def render_gerber_orientation(path):
    fig,ax=plt.subplots(figsize=(5,7.5),dpi=180)
    ax.add_patch(Rectangle((0,0),BOARD_W,BOARD_H,facecolor='#0b5f3c',edgecolor='black',lw=1.2))
    for h in holes:
        ax.add_patch(Circle((h.x,gerber_y(h.y)),h.drill/2,facecolor='white',edgecolor='black',lw=.5))
    for t in tracks:
        if t.layer!='F.Cu': continue
        ax.plot([pt[0] for pt in t.pts],[gerber_y(pt[1]) for pt in t.pts],color='#d5a642',lw=t.width*4.2,solid_capstyle='round',solid_joinstyle='round')
    for pad in pads:
        if pad.kind=='npth' or 'F.Cu' not in pad.layers: continue
        yy=gerber_y(pad.y)
        if pad.shape=='circle':
            ax.add_patch(Circle((pad.x,yy),pad.sx/2,facecolor='#d5a642',edgecolor='#7f601f',lw=.3))
        else:
            ax.add_patch(Rectangle((pad.x-pad.sx/2,yy-pad.sy/2),pad.sx,pad.sy,facecolor='#d5a642',edgecolor='#7f601f',lw=.3))
        if pad.kind in ('pth','via'):
            ax.add_patch(Circle((pad.x,yy),pad.drill/2,facecolor='white',edgecolor='black',lw=.25))
    for a,b in silk:
        ax.plot([a[0],b[0]],[gerber_y(a[1]),gerber_y(b[1])],color='white',lw=.85,solid_capstyle='round',solid_joinstyle='round')
    ax.set_xlim(-.5,20.5); ax.set_ylim(-.5,30.5); ax.set_aspect('equal'); ax.axis('off')
    ax.set_title('Gerber CAM top view - orientation verified',fontsize=9)
    fig.tight_layout(pad=.3); fig.savefig(path,bbox_inches='tight'); plt.close(fig)
render_gerber_orientation(DOC_DIR/'gerber_orientation_check.png')

# dimension drawing
fig,ax=plt.subplots(figsize=(6,8),dpi=180)
ax.add_patch(Rectangle((0,0),20,30,fill=False,lw=1.5))
for h in holes: ax.add_patch(Circle((h.x,h.y),h.drill/2,fill=False,lw=1))
ax.annotate('',xy=(0,-1.2),xytext=(20,-1.2),arrowprops=dict(arrowstyle='<->',lw=1))
ax.text(10,-1.8,'20.00 mm',ha='center',va='center',fontsize=8)
ax.annotate('',xy=(-1.2,0),xytext=(-1.2,30),arrowprops=dict(arrowstyle='<->',lw=1))
ax.text(-2.0,15,'30.00 mm',ha='center',va='center',rotation=90,fontsize=8)
ax.text(10,15,'4 x M2.2 NPTH\nUpper holes behind FPC: y=8.7 mm\nLower holes: y=27.5 mm',ha='center',va='center',fontsize=9)
ax.set_xlim(-3,22); ax.set_ylim(32,-3); ax.set_aspect('equal'); ax.axis('off'); fig.tight_layout()
fig.savefig(DOC_DIR/'dimensions.png',bbox_inches='tight'); plt.close(fig)

# ---- README and DRC report ----
readme=f'''# FPC10 + PWM 20×30 mm 转接板 V12

## V12：修正 Q1 栅极与源极焊盘
- 修正 Q1 同侧 1 脚（GATE）与 2 脚（SOURCE/GND）的物理焊盘位置。
- 使用两个过孔和一段底层走线完成 GATE 交叉，避免顶层短路或飞线。
- Q1 仍采用 AO3400A 标准电气编号：1=G、2=S、3=D。

## 延续 V11：适度加宽 FPC 10个信号焊盘

- FPC 顶视图从左往右固定为 **1～10脚**。
- 10个信号焊盘由 **0.35×2.30 mm** 适度加宽为 **0.45×2.30 mm**。
- 1.00 mm 脚距下，相邻信号焊盘铜间距仍为 **0.55 mm**，兼顾手工焊接与防连锡。
- FPC 信号焊盘钢网开口约为 **0.42×2.27 mm**，减少回流焊锡量。
- **FPC 1脚 = LED- / LEDK**，并连接 AO3400A 的漏极。
- **FPC 3脚 = GND**，对应原小板 LED- 旁边的 GND。
- J2 两排编号也按顶视图从左往右排列：上排 1～5，下排 6～10。
- 保留 FPC 第2脚串联 R3=25Ω。
- Q1、R1、R2、R3 分区布置，器件与走线之间留出更大空隙。
- FPC 两侧机械固定焊脚铜箔/阻焊开窗加大到 2.8×2.8 mm，钢网开口控制为 2.2×2.2 mm。
- SDO、SDA 与 6～10脚信号更多使用底层独立通道，减少顶层拥挤。
- PWM 电路仍只有 Q1、R1、R2；R3 属于 LEDA 串联电阻，不改变 PWM 栅极电路。

## 结构

- 板框：**20.00 × 30.00 mm**，双层。
- 固定孔：4 × **M2.2 非金属化孔**。
- J1：10P、1.0 mm、下接触 FPC，插入口朝 20 mm 板边；两侧固定焊脚为 2.8×2.8 mm。
- J2：2×5、2.54 mm 通孔，10 路按编号一一引出。
- J3：独立 `PWM / GND` 两针控制口。
- PWM 元件仍为：Q1=AO3400A、R1=100 Ω、R2=10 kΩ。
- LEDA 串联元件：R3=25 Ω（0603）。

## 引脚定义

| Pin | 名称 | 说明 |
|---:|---|---|
| 1 | LEDK / LED- | 背光负极，同时接 AO3400A 漏极 |
| 2 | LEDA | 背光正极，经 R3=25 Ω 后连接 J2 第2脚 |
| 3 | GND | 地，位于 LED- 旁边 |
| 4 | SDO | 屏幕串行输出，可不接 |
| 5 | SDA | SPI MOSI |
| 6 | CS | 片选 |
| 7 | DC | 数据/命令 |
| 8 | SCL | SPI 时钟 |
| 9 | RST | 复位 |
| 10 | VDD | 屏幕逻辑电源，按 3.3 V 使用 |

J3-1 为 3.3 V PWM 输入，J3-2 为 GND。

## 下单前检查

1. 在嘉立创顶层预览中确认 FPC 左端标记为 1，右端标记为 10。
2. 确认排线从板框上边插入，FPC 插座为 10P、1.0 mm、下接触。
3. 本板在 LEDA 上串联 R3=25 Ω，但它不等同于完整恒流驱动；首次上电仍建议使用限流电源并确认背光额定电流。
4. 建议首次只下单 5 片样板并限流上电。

## 文件

- `01_JLCPCB_Order/{base}_GERBER.zip`：嘉立创下单文件。
- `01_JLCPCB_Order/BOM_JLCPCB.csv`：SMT BOM。
- `01_JLCPCB_Order/CPL_JLCPCB.csv`：贴片坐标。
- `02_Source/{base}.kicad_pcb`：KiCad PCB 源文件。
- `03_Docs/preview_top.png`：顶层走线与正常方向丝印。
- `03_Docs/preview_bottom.png`：底层走线。
- `03_Docs/gerber_orientation_check.png`：Gerber CAM 顶视图检查。
'''
(DOC_DIR/'README_CN.md').write_text(readme,encoding='utf-8')

report=[]
report.append(f'Board: {BOARD_W:.2f} x {BOARD_H:.2f} mm')
report.append(f'Copper clearance target: {CLEARANCE:.2f} mm')
report.append(f'Copper-edge target: {EDGE_CLEARANCE:.2f} mm')
report.append(f'Different-net clearance errors: {len(drc_errors)}')
report.extend('  '+e for e in drc_errors)
report.append(f'Connectivity errors: {len(connectivity_errors)}')
report.extend('  '+e for e in connectivity_errors)
report.append('NOTE: independent geometry/connectivity checker, not official KiCad DRC.')
(DOC_DIR/'DRC_REPORT.txt').write_text('\n'.join(report)+'\n',encoding='utf-8')

# summary JSON
summary={'board_mm':[20,30],'mounting_holes':{'count':4,'diameter_mm':2.2,'centers_mm':HOLE_CENTERS},
         'gerber_y_axis_corrected':True,'fpc_top_view_direction':'left_to_right_1_to_10','pin_mapping':{'1':'LEDK/LED-','2':'LEDA through R3=25R','3':'GND'},'r3_series_resistor_ohm':25,'fpc_signal_pad_mm':[0.45,2.30],'fpc_signal_pitch_mm':1.0,'fpc_signal_copper_gap_mm':0.55,'fpc_signal_paste_mm':[0.42,2.27],'fpc_anchor_pad_mm':[2.8,2.8],'fpc_anchor_paste_mm':[2.2,2.2],'redistributed_layout':True,'silkscreen_refs_outside_components':True,'compact_q1_outline':True,'drc_errors':drc_errors,'connectivity_errors':connectivity_errors}
(DOC_DIR/'design_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')

# ZIP Gerber folder contents directly at root
with zipfile.ZipFile(ORDER_DIR/f'{base}_GERBER.zip','w',zipfile.ZIP_DEFLATED) as z:
    for p in sorted(GERBER_DIR.iterdir()): z.write(p,p.name)
# full package ZIP
fullzip=OUT.parent/f'{base}_FULL_PACKAGE.zip'
with zipfile.ZipFile(fullzip,'w',zipfile.ZIP_DEFLATED) as z:
    for p in OUT.rglob('*'):
        if p.is_file(): z.write(p,p.relative_to(OUT))

print('OUT',OUT)
print('GERBER_ZIP',ORDER_DIR/f'{base}_GERBER.zip')
print('FULL_ZIP',fullzip)
print('DRC_ERRORS',len(drc_errors))
for e in drc_errors: print('DRC',e)
print('CONNECTIVITY_ERRORS',len(connectivity_errors))
for e in connectivity_errors: print('CONN',e)
