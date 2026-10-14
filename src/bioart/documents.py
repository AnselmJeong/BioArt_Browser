"""Versioned, renderer-independent figure documents and atomic local persistence."""
from __future__ import annotations

import base64
import copy
import fcntl
import hashlib
import io
import json
import math
import os
import re
import textwrap
import uuid
import zipfile
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Literal

import resvg_py
from PIL import Image
from lxml import etree
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .config import workspace, atomic_json, under
from .core import catalog
from .imaging import safe_svg
from . import scenes
from .science_models import Science


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Transform(Strict):
    x: float = Field(default=0, ge=-100000, le=100000)
    y: float = Field(default=0, ge=-100000, le=100000)
    scaleX: float = Field(default=1, gt=0, le=1000)
    scaleY: float = Field(default=1, gt=0, le=1000)
    angle: float = Field(default=0, ge=-36000, le=36000)
    skewX: float = Field(default=0, ge=-89, le=89)
    skewY: float = Field(default=0, ge=-89, le=89)
    flipX: bool = False
    flipY: bool = False


Color = str


def color(value):
    if not re.fullmatch(r'#[a-fA-F0-9]{3,8}|none|transparent|[a-zA-Z]{1,24}|rgba?\([\d., %]+\)', value):
        raise ValueError('Invalid color')
    return value


class Stop(Strict):
    offset: float = Field(ge=0, le=1)
    color: str
    opacity: float = Field(default=1, ge=0, le=1)


class Gradient(Strict):
    type: Literal['linear', 'radial'] = 'linear'
    units: Literal['pixels', 'percentage'] = 'pixels'
    coords: dict[str, float]
    stops: list[Stop] = Field(min_length=2, max_length=64)
    offsetX: float = 0
    offsetY: float = 0
    matrix: list[float] | None = None

    @model_validator(mode='after')
    def check(self):
        if set(self.coords) - {'x1', 'y1', 'x2', 'y2', 'r1', 'r2'}:
            raise ValueError('Invalid gradient coordinates')
        if self.matrix is not None and len(self.matrix) != 6:
            raise ValueError('Invalid gradient transform')
        for s in self.stops: color(s.color)
        return self


class Style(Strict):
    fill: str | Gradient = '#a5c9b4'
    stroke: str = '#276a57'
    strokeWidth: float = Field(default=2, ge=0, le=500)
    opacity: float = Field(default=1, ge=0, le=1)
    dash: list[float] = Field(default_factory=list, max_length=16)
    lineCap: Literal['butt', 'round', 'square'] = 'round'
    lineJoin: Literal['miter', 'round', 'bevel'] = 'round'
    fillRule: Literal['nonzero', 'evenodd'] = 'nonzero'

    @model_validator(mode='after')
    def check(self):
        if isinstance(self.fill, str): color(self.fill)
        color(self.stroke)
        if any(not 0 <= v <= 10000 for v in self.dash): raise ValueError('Invalid dash')
        return self


class Anchor(Strict):
    nodeId: str
    x: float = Field(default=0.5, ge=0, le=1)
    y: float = Field(default=0.5, ge=0, le=1)


class Link(Strict):
    start: Anchor | None = None
    end: Anchor | None = None
    mode: Literal['straight', 'curve', 'elbow'] = 'straight'
    startHead: Literal['none', 'arrow', 'bar'] = 'none'
    endHead: Literal['none', 'arrow', 'bar'] = 'arrow'


class Node(Strict):
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,80}$')
    kind: Literal['rect', 'ellipse', 'path', 'text', 'asset', 'image', 'group', 'connector']
    name: str = Field(default='', max_length=250)
    transform: Transform = Field(default_factory=Transform)
    width: float = Field(default=100, ge=0, le=100000)
    height: float = Field(default=100, ge=0, le=100000)
    style: Style = Field(default_factory=Style)
    visible: bool = True
    locked: bool = False
    radius: float = Field(default=0, ge=0, le=10000)
    path: str = Field(default='', max_length=2000000)
    pathOffset: list[float] = Field(default_factory=lambda: [0, 0], min_length=2, max_length=2)
    text: str = Field(default='', max_length=20000)
    fontSize: float = Field(default=28, ge=1, le=1000)
    fontFamily: str = Field(default='Helvetica Neue', max_length=120)
    fontWeight: Literal['normal', 'bold'] = 'normal'
    fontStyle: Literal['normal', 'italic'] = 'normal'
    textAlign: Literal['left', 'center', 'right'] = 'left'
    lineHeight: float = Field(default=1.16, ge=0.5, le=5)
    fileId: str | None = Field(default=None, pattern=r'^(?:\d{1,20}|local-[a-f0-9]{32}-\d{4})$')
    sha256: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    imagePath: str | None = None
    sourceFileIds: list[str] = Field(default_factory=list, max_length=100)
    children: list[Node] = Field(default_factory=list, max_length=2000)
    clip: Node | None = None
    link: Link | None = None
    science: Science | None = None

    @model_validator(mode='after')
    def check(self):
        if self.path and not re.fullmatch(r'[MmLlHhVvCcSsQqTtAaZz\d.,+\-\seE]+', self.path):
            raise ValueError('Invalid path data')
        if self.kind == 'asset' and not (self.fileId and self.sha256):
            raise ValueError('Asset fingerprint required')
        if self.kind == 'image' and not self.imagePath:
            raise ValueError('Image path required')
        if self.kind == 'connector' and not self.link:
            raise ValueError('Connector metadata required')
        if self.science and self.kind != 'group': raise ValueError('Scientific metadata requires group geometry')
        if self.kind != 'group' and self.children: raise ValueError('Only groups have children')
        if self.clip and self.clip.kind not in {'rect', 'ellipse', 'path'}: raise ValueError('Invalid clipping path')
        return self


class Artboard(Strict):
    width: float = Field(default=1400, ge=100, le=10000)
    height: float = Field(default=850, ge=100, le=10000)
    background: str = '#ffffff'

    @model_validator(mode='after')
    def check(self):
        color(self.background)
        return self


class Document(Strict):
    schemaVersion: Literal[1] = 1
    id: str = Field(pattern=r'^doc-[a-f0-9]{12}$')
    revision: int = Field(default=1, ge=1)
    title: str = Field(default='새 과학 도해', max_length=200)
    artboard: Artboard = Field(default_factory=Artboard)
    nodes: list[Node] = Field(default_factory=list, max_length=2000)
    sourceSceneId: str | None = None
    updatedAt: str = ''

    @model_validator(mode='after')
    def check(self):
        ids = set()
        def visit(items, depth=0):
            if depth > 12: raise ValueError('Too many nested groups')
            for n in items:
                if n.id in ids: raise ValueError('Duplicate node ID')
                ids.add(n.id)
                if len(ids) > 4000: raise ValueError('Too many nodes')
                visit(n.children, depth + 1)
                if n.clip: visit([n.clip], depth + 1)
        visit(self.nodes)
        all_nodes = {n.id:n for n in walk(self.nodes)}
        for n in all_nodes.values():
            if n.science and n.science.type == 'inset' and n.science.live:
                source = all_nodes.get(n.science.sourceId)
                if not source or any(x.science and x.science.type == 'inset' for x in walk([source])):
                    raise ValueError('Live inset requires a source without inset references')
            if n.link:
                for a in [n.link.start, n.link.end]:
                    if a and (a.nodeId not in ids or a.nodeId == n.id): raise ValueError('Invalid connector target')
        return self


def walk(nodes):
    for n in nodes:
        yield n
        yield from walk(n.children)


def now(): return datetime.now(timezone.utc).isoformat()


def doc_path(did):
    if not re.fullmatch(r'doc-[a-f0-9]{12}', did): raise ValueError('Invalid document ID')
    return under(workspace() / 'projects', f'{did}.json')


def recovery_path(did):
    doc_path(did)
    key = hashlib.sha256(str(workspace()).encode()).hexdigest()[:16]
    root = Path(os.environ.get('BIOART_RECOVERY_ROOT', Path.home() / 'Library/Application Support/BioArt Browser/Recovery'))
    return root / key / (did + '.json')


def validate_sources(doc, verify=False):
    for n in walk(doc.nodes):
        if n.fileId:
            f = catalog.file(n.fileId)
            if f['sha256'] != n.sha256: raise ValueError('Asset fingerprint changed')
            if verify: catalog.verified_path(n.fileId)
        for fid in n.sourceFileIds: catalog.file(fid)
        if n.imagePath:
            p = scenes.generated_path(n.imagePath)
            if verify and not p.is_file(): raise ValueError('Generated image missing')


def read(did):
    return Document.model_validate(json.loads(doc_path(did).read_text())['document']).model_dump()


def list_documents():
    items = []
    for p in (workspace() / 'projects').glob('doc-*.json'):
        try:
            d = read(p.stem)
            items.append({k:d[k] for k in ['id', 'title', 'revision', 'updatedAt']})
        except (ValueError, KeyError, OSError): continue
    return sorted(items, key=lambda d:d['updatedAt'], reverse=True)


def create(title='새 과학 도해', file_ids=None):
    d = Document(id='doc-' + uuid.uuid4().hex[:12], title=title, updatedAt=now())
    for i, fid in enumerate(file_ids or []):
        f = catalog.file(fid)
        catalog.verified_path(fid)
        a = catalog.asset(f['artwork_id'])
        d.nodes.append(Node(id='n-'+uuid.uuid4().hex[:12], kind='asset', name=a['title'],
            fileId=str(fid), sha256=f['sha256'], width=240, height=200,
            transform=Transform(x=170+(i%4)*320, y=170+(i//4)*240),
            style=Style(stroke='none',strokeWidth=0)))
    d = Document.model_validate(d.model_dump())
    atomic_json(doc_path(d.id), {'document':d.model_dump(), 'operations':[]})
    return d.model_dump()


class Conflict(ValueError): pass


def save(did, value, base_revision, operation_id):
    if not re.fullmatch(r'[a-zA-Z0-9_-]{8,100}', operation_id): raise ValueError('Invalid operation ID')
    d = Document.model_validate(value)
    if d.id != did or d.revision != base_revision: raise ValueError('Document identity/revision mismatch')
    path = doc_path(did)
    # Save a recoverable proposal on the internal volume before touching the workspace.
    proposal = {'document': d.model_dump(), 'baseRevision':base_revision, 'operationId':operation_id}
    rec = recovery_path(did)
    rec.parent.mkdir(parents=True, exist_ok=True)
    with rec.with_suffix('.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            previous = json.loads(path.read_text())
        except OSError:
            atomic_json(rec, proposal)
            raise
        Document.model_validate(previous['document'])
        if operation_id in previous.get('operations', []): return previous['document']
        if previous['document']['revision'] != base_revision:
            atomic_json(rec.with_name(f'{did}-conflict-{operation_id}.json'), proposal)
            raise Conflict('다른 창에서 변경되었습니다. 새 사본으로 저장하거나 다시 불러오세요.')
        atomic_json(rec, proposal)
        validate_sources(d)
        d.revision += 1
        d.updatedAt = now()
        envelope = {'document':d.model_dump(), 'operations':(previous.get('operations', []) + [operation_id])[-100:]}
        atomic_json(path, envelope)
        rec.unlink(missing_ok=True)
        return d.model_dump()


def recovery(did):
    path = recovery_path(did)
    return json.loads(path.read_text()) if path.exists() else None


def legacy_list():
    items=[]
    for p in (workspace()/'projects').glob('scene-*.json'):
        try:
            s=json.loads(p.read_text())
            items.append({'id':s['scene_id'],'title':s.get('title') or 'AI 이미지', 'revision':s['revision']})
        except (OSError, ValueError, KeyError): continue
    return items


def migrate(sid):
    s=json.loads(scenes.scene_path(sid).read_text())
    d=Document(id='doc-'+uuid.uuid4().hex[:12],title=s.get('title') or '가져온 도해',sourceSceneId=sid,
        artboard=Artboard(width=s['canvas']['width'],height=s['canvas']['height']),updatedAt=now())
    def text(txt,x,y,size,name='라벨',align='left'):
        # Legacy y is baseline; new text box starts approximately at baseline-size.
        return Node(id='n-'+uuid.uuid4().hex[:12],kind='text',name=name,text=txt,
            width=max(size,len(txt)*size*.65),height=size*1.13,fontSize=size,textAlign=align,
            transform=Transform(x=x+(0 if align=='center' else max(size,len(txt)*size*.65)/2),y=y-size*.35),
            style=Style(fill='#263b36',stroke='none',strokeWidth=0))
    if s.get('title'): d.nodes.append(text(s['title'],70,75,32,'제목'))
    if s.get('generated_image'):
        d.nodes.append(Node(id='n-'+uuid.uuid4().hex[:12],kind='image',name='AI 생성 이미지',
            imagePath=s['generated_image'],width=d.artboard.width,height=d.artboard.height,
            sourceFileIds=s.get('reference_file_ids',[]),transform=Transform(x=d.artboard.width/2,y=d.artboard.height/2),
            style=Style(stroke='none',strokeWidth=0)))
    for a in s['objects']:
        d.nodes.append(Node(id=a['id'],kind='asset',name=a.get('source_title',a['label']),fileId=a['file_id'],sha256=a['sha256'],
            width=a['width'],height=a['height'],transform=Transform(x=a['x']+a['width']/2,y=a['y']+a['height']/2),
            style=Style(stroke='none',strokeWidth=0)))
        for i,line in enumerate(textwrap.wrap(a['label'],width=max(8,int(a['width']/17)))):
            d.nodes.append(text(line,a['x']+a['width']/2,a['y']+a['height']+24+i*22,17,align='center'))
    def arrow(x1,y1,x2,y2):
        return Node(id='n-'+uuid.uuid4().hex[:12],kind='connector',name='연결선',path=f'M {x1} {y1} L {x2} {y2}',
            pathOffset=[0,0],style=Style(fill='none',stroke='#276a57',strokeWidth=3),link=Link())
    for a in s.get('arrows',[]):
        d.nodes.append(arrow(a['x1'],a['y1'],a['x2'],a['y2']))
        if a.get('label'): d.nodes.append(text(a['label'],(a['x1']+a['x2'])/2,(a['y1']+a['y2'])/2-12,18,align='center'))
    for t in s.get('texts',[]): d.nodes.append(text(t['text'],t['x'],t['y'],t['font_size']))
    if s.get('layout') in {'process','workflow'}:
        for a,b in zip(s['objects'],s['objects'][1:]):
            if a['y']==b['y']: d.nodes.append(arrow(a['x']+a['width']+5,a['y']+a['height']/2,b['x']-10,a['y']+a['height']/2))
    atomic_json(doc_path(d.id),{'document':d.model_dump(),'operations':[]})
    return d.model_dump()


def asset_data(fid):
    f=catalog.file(fid)
    p=catalog.verified_path(fid)
    raw=safe_svg(p.read_bytes()) if f['format']=='SVG' else p.read_bytes()
    if f['format']=='SVG':
        old=etree.fromstring(raw)
        root=etree.Element('{http://www.w3.org/2000/svg}svg', nsmap={None:'http://www.w3.org/2000/svg','xlink':'http://www.w3.org/1999/xlink'})
        root.attrib.update(old.attrib)
        root.text=old.text
        root.extend(list(old))
        raw=etree.tostring(root)
    mime='image/svg+xml' if f['format']=='SVG' else 'image/png'
    return {'fileId':str(fid),'sha256':f['sha256'],'format':f['format'],
        'title':catalog.asset(f['artwork_id'])['title'], 'url':f'data:{mime};base64,'+base64.b64encode(raw).decode(),
        'svg':raw.decode() if f['format']=='SVG' else None}


def transform(t):
    sx=t.scaleX*(-1 if t.flipX else 1); sy=t.scaleY*(-1 if t.flipY else 1)
    return f'translate({t.x} {t.y}) rotate({t.angle}) scale({sx} {sy}) skewX({t.skewX}) skewY({t.skewY})'


def render(value):
    d=Document.model_validate(value)
    defs=[]; warnings=[]; sources={}; assets={}
    def paint(fill,n):
        if isinstance(fill,str): return fill
        gid='gradient-'+n.id
        tag='linearGradient' if fill.type=='linear' else 'radialGradient'
        coords=dict(fill.coords)
        if fill.type=='radial': coords={'cx':coords.get('x2',0),'cy':coords.get('y2',0),'r':coords.get('r2',1),'fx':coords.get('x1',0),'fy':coords.get('y1',0)}
        attrs=' '.join(f'{k}="{v}"' for k,v in coords.items())
        matrix=f' matrix({" ".join(map(str,fill.matrix))})' if fill.matrix else ''
        unit='userSpaceOnUse' if fill.units=='pixels' else 'objectBoundingBox'
        # Fabric gradient coordinates are relative to the object's top-left corner.
        tr=f'translate({-n.width/2+fill.offsetX} {-n.height/2+fill.offsetY}){matrix}' if unit=='userSpaceOnUse' else matrix.strip()
        defs.append(f'<{tag} id="{gid}" gradientUnits="{unit}" {attrs} gradientTransform="{tr}">'+''.join(f'<stop offset="{s.offset}" stop-color="{escape(s.color)}" stop-opacity="{s.opacity}"/>' for s in fill.stops)+f'</{tag}>')
        return f'url(#{gid})'
    def source(fid):
        if fid in sources:return
        f=catalog.file(fid); a=catalog.asset(f['artwork_id']); meta=a.get('metadata',{}) if a['source_status']=='verified' else {}
        sources[fid]={'file_id':fid,'sha256':f['sha256'],'title':a['title'],'source_url':a['source_url'],'license':a['license'],'credit':meta.get('credit'),'license_url':meta.get('license_url')}
    def node(n,mask=False):
        if not n.visible and not mask:return ''
        for fid in n.sourceFileIds: source(fid)
        st=n.style
        fill=paint(st.fill,n)
        style=f'fill="{escape(fill)}" stroke="{escape(st.stroke)}" stroke-width="{st.strokeWidth}" opacity="{st.opacity}" stroke-linecap="{st.lineCap}" stroke-linejoin="{st.lineJoin}" fill-rule="{st.fillRule}"'
        if mask: style='fill="black" stroke="none"'
        if st.dash and not mask:style+=f' stroke-dasharray="{" ".join(map(str,st.dash))}"'
        w,h=n.width,n.height
        if n.kind=='rect': body=f'<rect x="{-w/2}" y="{-h/2}" width="{w}" height="{h}" rx="{n.radius}" {style}/>'
        elif n.kind=='ellipse': body=f'<ellipse rx="{w/2}" ry="{h/2}" {style}/>'
        elif n.kind in {'path','connector'}:
            marks=''
            if n.link:
                for end,head in [('start',n.link.startHead),('end',n.link.endHead)]:
                    if head!='none':
                        mid=f'{n.id}-{end}'; shape='<path d="M 0 -4 L 8 0 L 0 4 Z"/>' if head=='arrow' else '<path d="M 7 -5 L 7 5" fill="none" stroke-width="2"/>'
                        defs.append(f'<marker id="{mid}" markerWidth="12" markerHeight="12" viewBox="-2 -6 12 12" refX="7" refY="0" orient="auto-start-reverse" markerUnits="strokeWidth" fill="{escape(st.stroke)}" stroke="{escape(st.stroke)}">{shape}</marker>')
                        marks+=f' marker-{end}="url(#{mid})"'
            body=f'<path d="{escape(n.path)}" transform="translate({-n.pathOffset[0]} {-n.pathOffset[1]})" {style}{marks}/>'
        elif n.kind=='text':
            anchor={'left':'start','center':'middle','right':'end'}[n.textAlign]; x={'left':-w/2,'center':0,'right':w/2}[n.textAlign]
            # Fabric uses a 1.13 em font box and baseline fraction .222.
            baseline=-h/2+n.fontSize*1.13*(1-.222)
            lines=n.text.split('\n')
            spans=''.join(f'<tspan x="{x}" y="{baseline+i*n.fontSize*1.13*n.lineHeight}">{escape(line)}</tspan>' for i,line in enumerate(lines))
            body=f'<text xml:space="preserve" font-family="{escape(n.fontFamily)}, Apple SD Gothic Neo, sans-serif" font-size="{n.fontSize}" font-weight="{n.fontWeight}" font-style="{n.fontStyle}" text-anchor="{anchor}" {style}>{spans}</text>'
        elif n.kind in {'asset','image'}:
            if n.fileId:
                source(n.fileId)
                if n.fileId not in assets: assets[n.fileId]=asset_data(n.fileId)['url']
                url=assets[n.fileId]
            else:
                url='data:image/png;base64,'+base64.b64encode(scenes.generated_path(n.imagePath).read_bytes()).decode()
            body=f'<image x="{-w/2}" y="{-h/2}" width="{w}" height="{h}" preserveAspectRatio="xMidYMid meet" href="{url}" opacity="{st.opacity}"/>'
        else: body=''.join(node(c) for c in n.children)
        if mask:
            # SVG clipPath accepts shapes, not a nested group (resvg ignores it).
            if ' transform="' in body:
                return body.replace(' transform="', f' transform="{transform(n.transform)} ', 1)
            return body.replace(' ', f' transform="{transform(n.transform)}" ', 1)
        if n.clip:
            cid='clip-'+n.id
            defs.append(f'<clipPath id="{cid}">{node(n.clip,True)}</clipPath>')
            body=f'<g clip-path="url(#{cid})">{body}</g>'
        return f'<g id="{n.id}" transform="{transform(n.transform)}"'+(f' opacity="{st.opacity}"' if n.kind=='group' else '')+'>'+body+'</g>'
    body=''.join(node(n) for n in d.nodes)
    for n in d.nodes:
        if n.transform.x<0 or n.transform.y<0 or n.transform.x>d.artboard.width or n.transform.y>d.artboard.height:
            warnings.append(f'{n.name or n.id}: 중심점이 출력 영역 밖에 있습니다.')
    svg=f'<svg xmlns="http://www.w3.org/2000/svg" width="{d.artboard.width}" height="{d.artboard.height}" viewBox="0 0 {d.artboard.width} {d.artboard.height}"><defs>{"".join(defs)}</defs><rect width="100%" height="100%" fill="{escape(d.artboard.background)}"/>{body}</svg>'
    return svg,list(sources.values()),warnings


def export(did,revision):
    value=read(did)
    if value['revision']!=revision:raise Conflict('먼저 현재 변경 사항을 저장하세요.')
    doc=Document.model_validate(value)
    validate_sources(doc,True)
    svg,sources,warnings=render(value)
    if doc.artboard.width*doc.artboard.height>25_000_000:raise ValueError('PNG 출력은 2,500만 픽셀 이하로 설정하세요.')
    png=resvg_py.svg_to_bytes(svg_string=svg)
    eid=f'{did}-r{revision}-{uuid.uuid4().hex[:6]}'
    directory=workspace()/'exports'/eid
    directory.mkdir(parents=True)
    (directory/'figure.svg').write_text(svg)
    (directory/'figure.png').write_bytes(png)
    atomic_json(directory/'document.json',value)
    atomic_json(directory/'manifest.json',{'document_id':did,'revision':revision,'sources':sources,'warnings':warnings,
        'contains_raster':any(n.kind=='image' or (n.fileId and catalog.file(n.fileId)['format']=='PNG') for n in walk(doc.nodes)),
        'scientific_review':'not_assessed'})
    (directory/'SOURCES.md').write_text('# Sources\n\n'+'\n\n'.join(f"{s['title']} · {s['source_url']} · {s['license']} · {s['credit'] or 'Credit unconfirmed'}" for s in sources))
    with zipfile.ZipFile(directory.with_suffix('.zip'),'w',zipfile.ZIP_DEFLATED) as archive:
        for p in directory.iterdir():archive.write(p,p.name)
    return {'path':str(directory),'download_url':f'/api/exports/{eid}.zip','warnings':warnings,'revision':revision}
