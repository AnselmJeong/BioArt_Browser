"""Versioned, self-contained project archives. Imported resources never overwrite a catalog."""
from __future__ import annotations
import copy
import hashlib
import io
import json
import re
import shutil
import stat
import tempfile
import uuid
import zipfile
import zlib
from pathlib import Path, PurePosixPath
from PIL import Image
from pydantic import Field
import resvg_py
from . import documents as d, publication
from .config import workspace, under, atomic_json
from .imaging import safe_svg

MAX_ZIP=100_000_000
MAX_TOTAL=256_000_000
MAX_FILE=32_000_000
LOCAL_PATTERN=r'local-([a-f0-9]{32})-(\d{4})'

class Entry(d.Strict):
    path:str=Field(max_length=180)
    bytes:int=Field(ge=0,le=MAX_FILE)
    sha256:str=Field(pattern=r'^[a-f0-9]{64}$')

class Source(d.Strict):
    title:str=Field(max_length=500)
    license:str=Field(max_length=200)
    source_url:str=Field(default='',max_length=2000)
    credit:str|None=Field(default=None,max_length=20000)
    license_url:str|None=Field(default=None,max_length=2000)
    source_status:str=Field(default='pending',max_length=50)
    originalFileId:str=Field(max_length=100)

class Resource(d.Strict):
    fileId:str=Field(max_length=100)
    path:str=Field(max_length=180)
    format:str=Field(pattern=r'^(SVG|PNG)$')
    source:Source

class Generated(d.Strict):
    imagePath:str=Field(max_length=250)
    path:str=Field(max_length=180)

class Manifest(d.Strict):
    format:str=Field(pattern=r'^bioart-project$')
    version:int=Field(ge=1,le=1)
    document:str='document.json'
    files:list[Entry]=Field(max_length=2048)
    resources:list[Resource]=Field(default_factory=list,max_length=1000)
    images:list[Generated]=Field(default_factory=list,max_length=1000)
    requiredFonts:list[str]=Field(default_factory=list,max_length=100)
    warnings:list[str]=Field(default_factory=list,max_length=2000)


def local_record(fid):
    match=re.fullmatch(LOCAL_PATTERN,str(fid))
    if not match:raise ValueError('Invalid portable resource ID')
    root=under(workspace()/'projects/imports',match[1])
    records=json.loads((root/'resources.json').read_text())
    record=records[match[2]]
    f=record['file'];path=under(root,f"assets/{match[2]}.{f['format'].lower()}")
    return record,path


def walk(nodes):
    for n in nodes:
        yield n
        yield from walk(n.children)
        if n.clip:yield from walk([n.clip])


def references(doc):
    files={};images=set()
    for n in walk(doc.nodes):
        if n.fileId:
            previous=files.get(n.fileId)
            if previous and previous!=n.sha256:raise ValueError('Conflicting asset checksums')
            files[n.fileId]=n.sha256
        for fid in n.sourceFileIds:files.setdefault(fid,None)
        if n.imagePath:images.add(n.imagePath)
    return files,images


def image_valid(raw,fmt):
    if fmt=='SVG':safe_svg(raw);return
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.format!='PNG' or image.width*image.height>50_000_000:raise ValueError('Invalid or oversized PNG')
            image.verify()
    except (OSError,Image.DecompressionBombError) as exc:raise ValueError('잘못된 PNG 이미지입니다.') from exc


def export_project(did,revision):
    value=d.read(did)
    if value['revision']!=revision:raise d.Conflict('저장한 도해가 변경되었습니다. 다시 시도하세요.')
    doc=d.Document.model_validate(value);refs,images=references(doc)
    payload={};resources=[];generated=[];warnings=[]
    for i,(fid,expected) in enumerate(sorted(refs.items())):
        f=d.catalog.file(fid);a=d.catalog.asset(f['artwork_id']);raw=d.catalog.verified_path(fid).read_bytes()
        if expected and expected!=f['sha256']:raise ValueError('원본 자료 체크섬이 변경되었습니다.')
        meta=a.get('metadata',{})
        if a.get('license') not in {'Public Domain','CC-BY'}:raise ValueError(f"{a['title']}: 재배포 조건을 확인할 수 없어 휴대용 ZIP에 포함할 수 없습니다.")
        if a['license']=='CC-BY' and not (a.get('source_status')=='verified' and meta.get('credit') and a.get('source_url')):
            raise ValueError(f"{a['title']}: CC-BY 저작자와 원본 출처를 먼저 확인하세요.")
        if a.get('source_status')!='verified':warnings.append(a['title']+': 출처 메타데이터가 확인되지 않았습니다.')
        path=f"assets/{i:04d}.{f['format'].lower()}";payload[path]=raw
        resources.append(Resource(fileId=fid,path=path,format=f['format'],source=Source(title=a['title'],license=a['license'],source_url=a.get('source_url') or '',credit=meta.get('credit'),license_url=meta.get('license_url'),source_status=a.get('source_status','pending'),originalFileId=f.get('originalFileId',fid))))
    for i,relative in enumerate(sorted(images)):
        raw=d.scenes.generated_path(relative).read_bytes();image_valid(raw,'PNG');path=f'images/{i:04d}.png';payload[path]=raw;generated.append(Generated(imagePath=relative,path=path))
    if images:warnings.append('생성·사용자 이미지의 재배포 권한은 별도로 확인하세요.')
    payload['document.json']=json.dumps(value,ensure_ascii=False).encode()
    payload['publication.json']=json.dumps(publication.settings(did)).encode()
    svg,_,_=d.render(value)
    payload['preview.png']=resvg_py.svg_to_bytes(svg_string=svg,width=1000)
    payload['SOURCES.md']=('# Sources\n\n'+'\n\n'.join(f"{r.source.title}\nFile: {r.source.originalFileId}\n{r.source.source_url}\nLicense: {r.source.license}\nCredit: {r.source.credit or 'Unconfirmed'}" for r in resources)+'\n\nFonts are not bundled. Editable text uses installed fonts.').encode()
    payload['README.txt']='BioArt Portable Project v1\n앱의 프로젝트 ZIP → 가져오기로 여세요. 출력 ZIP과 다른 형식입니다.\n원본 자료와 편집 정보가 포함됩니다. 글꼴 파일은 포함하지 않습니다. preview.png로 외형을 비교하세요.\n'.encode()
    entries=[Entry(path=name,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()) for name,raw in payload.items()]
    manifest=Manifest(format='bioart-project',version=1,files=entries,resources=resources,images=generated,requiredFonts=sorted({n.fontFamily for n in walk(doc.nodes) if n.kind=='text'}),warnings=warnings)
    payload['manifest.json']=manifest.model_dump_json().encode()
    if sum(map(len,payload.values()))>MAX_TOTAL or any(len(v)>MAX_FILE for v in payload.values()):raise ValueError('휴대용 프로젝트 크기 한도를 초과했습니다 (파일 32 MB / 전체 256 MB).')
    root=workspace()/'exports';root.mkdir(parents=True,exist_ok=True);name=f'project-{did}-r{revision}-{uuid.uuid4().hex[:6]}.zip'
    with tempfile.TemporaryDirectory(prefix='.portable-',dir=root) as temp:
        temp=Path(temp)/name
        with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as z:
            for member,raw in payload.items():z.writestr(member,raw)
        if temp.stat().st_size>MAX_ZIP:raise ValueError('압축 파일은 최대 100 MB까지 지원합니다.')
        with zipfile.ZipFile(temp) as z:
            if z.testzip():raise ValueError('ZIP 무결성 검증 실패')
        temp.rename(root/name)
    return {'path':str(root/name),'download_url':'/api/exports/'+name,'portable':True,'revision':revision,'resources':len(resources),'images':len(images),'warnings':warnings,'fonts':manifest.requiredFonts}


def unpack(raw):
    if len(raw)>MAX_ZIP:raise ValueError('ZIP은 최대 100 MB까지 가져올 수 있습니다.')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            infos=z.infolist()
            if len(infos)>2049 or len({i.filename for i in infos})!=len(infos):raise ValueError('중복 항목 또는 너무 많은 ZIP 항목')
            if sum(i.file_size for i in infos)>MAX_TOTAL:raise ValueError('ZIP 해제 크기가 256 MB를 초과합니다.')
            for i in infos:
                p=PurePosixPath(i.filename);mode=i.external_attr>>16
                if (i.is_dir() or p.is_absolute() or any(part in {'..','.'} for part in p.parts) or '\\' in i.filename or ':' in i.filename or str(p)!=i.filename or len(i.filename)>180 or i.flag_bits&1 or stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in {0,stat.S_IFREG}) or i.file_size>MAX_FILE or i.compress_type not in {zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED}):raise ValueError('안전하지 않거나 지원하지 않는 ZIP 항목')
            if 'manifest.json' not in z.namelist():raise ValueError('휴대용 프로젝트 ZIP이 아닙니다. 프로젝트 ZIP 내보내기를 사용하세요.')
            manifest_raw=z.read('manifest.json')
            if len(manifest_raw)>2_000_000:raise ValueError('Manifest too large')
            header=json.loads(manifest_raw)
            if not isinstance(header,dict) or header.get('format')!='bioart-project':raise ValueError('출력용 ZIP은 가져올 수 없습니다. 프로젝트 ZIP 내보내기를 사용하세요.')
            if header.get('version')!=1:raise ValueError('지원하지 않는 휴대용 프로젝트 버전입니다. 앱 업데이트가 필요합니다.')
            m=Manifest.model_validate(header)
            if m.document!='document.json':raise ValueError('Unsupported document entry')
            names={f.path for f in m.files}
            if len(names)!=len(m.files) or set(z.namelist())!=names|{'manifest.json'}:raise ValueError('ZIP 목록과 manifest가 일치하지 않습니다.')
            allowed={'document.json','publication.json','preview.png','SOURCES.md','README.txt'}
            if any(not (n in allowed or re.fullmatch(r'(assets/\d{4}\.(svg|png)|images/\d{4}\.png)',n)) for n in names):raise ValueError('지원하지 않는 프로젝트 파일')
            contents={}
            for entry in m.files:
                if z.getinfo(entry.path).file_size!=entry.bytes:raise ValueError('파일 크기가 manifest와 다릅니다.')
                data=z.read(entry.path)
                if hashlib.sha256(data).hexdigest()!=entry.sha256:raise ValueError('파일 체크섬 검증 실패: '+entry.path)
                contents[entry.path]=data
    except (zipfile.BadZipFile,RuntimeError,NotImplementedError,zlib.error,EOFError) as exc:raise ValueError('읽을 수 없는 프로젝트 ZIP입니다.') from exc
    if len(contents['document.json'])>16_000_000:raise ValueError('편집 문서가 16 MB 한도를 초과합니다.')
    doc=d.Document.model_validate_json(contents['document.json']);refs,images=references(doc)
    if set(refs)!={r.fileId for r in m.resources} or len(m.resources)!=len(refs) or images!={r.imagePath for r in m.images} or len(m.images)!=len(images):raise ValueError('도해 자료와 manifest 참조가 일치하지 않습니다.')
    used=set()
    for r in m.resources:
        if r.path in used or r.path not in contents or not re.fullmatch(r'assets/\d{4}\.'+r.format.lower(),r.path):raise ValueError('잘못된 자료 경로')
        used.add(r.path);image_valid(contents[r.path],r.format)
        if refs[r.fileId] and hashlib.sha256(contents[r.path]).hexdigest()!=refs[r.fileId]:raise ValueError('도해의 원본 체크섬이 일치하지 않습니다.')
    for r in m.images:
        if r.path in used or r.path not in contents or not re.fullmatch(r'images/\d{4}\.png',r.path):raise ValueError('잘못된 이미지 경로')
        used.add(r.path);image_valid(contents[r.path],'PNG')
    if {p for p in contents if p.startswith(('assets/','images/'))}!=used:raise ValueError('참조되지 않은 자료가 있습니다.')
    if 'preview.png' in contents:image_valid(contents['preview.png'],'PNG')
    options=publication.Options.model_validate_json(contents['publication.json']) if 'publication.json' in contents else publication.Options()
    return m,doc,contents,options


def import_project(raw):
    m,doc,contents,options=unpack(raw)
    bundle=uuid.uuid4().hex;parent=workspace()/'projects/imports';parent.mkdir(parents=True,exist_ok=True)
    target=parent/bundle;did='doc-'+uuid.uuid4().hex[:12];records={};mapping={};image_mapping={};warnings=list(m.warnings)
    # Stage resources first; the project becomes visible only at the final atomic document write.
    with tempfile.TemporaryDirectory(prefix='.incoming-',dir=parent) as temp:
        stage=Path(temp)/'bundle';stage.mkdir();(stage/'assets').mkdir();(stage/'images').mkdir()
        for i,r in enumerate(m.resources):
            key=f'{i:04d}';fid=f'local-{bundle}-{key}';mapping[r.fileId]=fid;data=contents[r.path];path=stage/f'assets/{key}.{r.format.lower()}';path.write_bytes(data)
            source=r.source;meta={'status':source.source_status,'credit':source.credit,'license_url':source.license_url}
            file={'id':fid,'artwork_id':fid,'representation_id':'rep-'+fid,'format':r.format,'status':'valid','sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'originalFileId':source.originalFileId}
            asset={'id':fid,'title':source.title,'license':source.license,'source_url':source.source_url,'source_status':source.source_status,'metadata':meta,'files':[file],'formats':[r.format],'portable':True}
            records[key]={'file':file,'asset':asset}
        for i,r in enumerate(m.images):
            name=f'{i:04d}.png';(stage/'images'/name).write_bytes(contents[r.path]);image_mapping[r.imagePath]=f'projects/imports/{bundle}/images/{name}'
        atomic_json(stage/'resources.json',records);atomic_json(stage/'original-manifest.json',m.model_dump())
        if 'preview.png' in contents:(stage/'preview.png').write_bytes(contents['preview.png'])
        for n in walk(doc.nodes):
            if n.fileId:n.fileId=mapping[n.fileId]
            n.sourceFileIds=[mapping[fid] for fid in n.sourceFileIds]
            if n.imagePath:n.imagePath=image_mapping[n.imagePath]
        doc.id=did;doc.revision=1;doc.sourceSceneId=None;doc.updatedAt=d.now()
        doc=d.Document.model_validate(doc.model_dump());settings_path=workspace()/'state/publication-settings'/f'{did}.json'
        try:
            stage.rename(target)
            d.validate_sources(doc,verify=True)
            atomic_json(settings_path,options.model_dump())
            atomic_json(d.doc_path(did),{'document':doc.model_dump(),'operations':[]})
        except Exception:
            shutil.rmtree(target,ignore_errors=True);settings_path.unlink(missing_ok=True);raise
    if m.resources:warnings.append('출처·라이선스 표기는 ZIP에 담긴 정보를 보존한 것이며 온라인으로 다시 검증하지 않았습니다.')
    if m.requiredFonts:warnings.append('편집 글꼴 필요: '+', '.join(m.requiredFonts)+'. 다른 컴퓨터에서는 미리보기와 비교하고 프리플라이트를 실행하세요.')
    return {'document':doc.model_dump(),'resources':len(m.resources),'images':len(m.images),'warnings':warnings,'portable':True}
