"""Publication export from immutable document revisions, with measurable preflight."""
from __future__ import annotations

import copy
import hashlib
import io
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

from lxml import etree
from PIL import Image, ImageCms
from pydantic import Field, model_validator
from pypdf import PdfReader
import resvg_py

from . import documents as docs
from .config import atomic_json, workspace

MAX_PIXELS = 50_000_000
MAX_DIMENSION = 20000

class Options(docs.Strict):
    widthMm: float = Field(default=174, ge=10, le=1000)
    dpi: int = Field(default=600, ge=72, le=2400)
    fontMode: Literal['outline', 'embed'] = 'outline'
    background: Literal['document', 'white', 'transparent'] = 'document'
    formats: list[Literal['pdf', 'tiff', 'png', 'svg']] = Field(default_factory=lambda:['pdf','tiff','png','svg'], min_length=1, max_length=4)
    minFontPt: float = Field(default=6, ge=1, le=30)
    minStrokePt: float = Field(default=.25, ge=.05, le=5)
    minRasterDpi: int = Field(default=300, ge=72, le=2400)

    @model_validator(mode='after')
    def unique_formats(self):
        if len(set(self.formats)) != len(self.formats): raise ValueError('Duplicate output format')
        return self


def helper_path():
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / 'publication' / 'bioart-publication'
    return Path(__file__).resolve().parents[2] / 'native/publication/target/release/bioart-publication'


def dimensions(doc, options):
    height = options.widthMm * doc.artboard.height / doc.artboard.width
    # JS-compatible positive half-up rounding, including odd-sized artboards.
    pw = math.floor(options.widthMm / 25.4 * options.dpi + .5)
    ph = math.floor(height / 25.4 * options.dpi + .5)
    return {'widthMm':options.widthMm, 'heightMm':height, 'dpi':options.dpi,
            'pixelWidth':pw, 'pixelHeight':ph, 'megapixels':round(pw*ph/1e6,2),
            'estimatedMemoryMiB':math.ceil(pw*ph*20/1048576+96), 'colorSpace':'sRGB',
            'pdfWidthPt':options.widthMm/25.4*72, 'pdfHeightPt':height/25.4*72}


class Cancelled(Exception): pass


def check_cancel(event):
    if event and event.is_set(): raise Cancelled()


def convert(svg, directory, options, mode='analyze', event=None):
    binary=helper_path()
    if not binary.is_file(): raise ValueError('출력 엔진이 없습니다. 앱을 다시 빌드하거나 설치하세요.')
    directory.mkdir(parents=True, exist_ok=True)
    source=directory/'input.svg';source.write_text(svg)
    process=subprocess.Popen([str(binary),str(source),str(directory),str(options.widthMm),str(options.dpi),options.fontMode,mode], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    start=time.monotonic()
    try:
        while process.poll() is None:
            check_cancel(event)
            if time.monotonic()-start>120: raise ValueError('출력 엔진 시간이 초과되었습니다. 도해를 나누거나 크기를 줄이세요.')
            time.sleep(.05)
        stderr=process.communicate()[1].decode(errors='replace')
        if process.returncode: raise ValueError('출력 변환 실패: '+stderr[:1000])
    finally:
        if process.poll() is None:
            process.kill();process.wait()
    return json.loads((directory/'analysis.json').read_text())


def source_svg(doc, options):
    rendered=doc.model_copy(deep=True)
    if options.background!='document':rendered.artboard.background='transparent' if options.background=='transparent' else '#ffffff'
    return docs.render(rendered.model_dump())


def _sources(doc):
    issues=[];source_info=[];seen=set()
    for n in docs.walk(doc.nodes):
        for fid in ([n.fileId] if n.fileId else [])+n.sourceFileIds:
            if fid in seen:continue
            seen.add(fid)
            try:
                f=docs.catalog.file(fid);docs.catalog.verified_path(fid)
                if fid==n.fileId and f['sha256']!=n.sha256:raise ValueError('체크섬이 변경되었습니다.')
                a=docs.catalog.asset(f['artwork_id']);credit=a.get('metadata',{}).get('credit') if a.get('source_status')=='verified' else None
                source_info.append({'fileId':fid,'title':a['title'],'license':a.get('license'),'credit':credit,'source_url':a.get('source_url')})
                if not a.get('license') or a.get('license') not in {'Public Domain','CC-BY'} or a.get('source_status')!='verified' or not credit:
                    issues.append(issue('warning','attribution',n.id,n.name,'원본 저작자·라이선스 확인이 필요합니다.',{'fileId':fid,'license':a.get('license'),'credit':credit}))
                if f['format']=='PNG':
                    with Image.open(docs.catalog.verified_path(fid)) as image:
                        if image.mode in {'RGBA','LA'} and image.getextrema()[-1][0]<255:issues.append(issue('warning','transparency',n.id,n.name,'투명 픽셀이 있는 원본 이미지입니다.'))
            except (ValueError,OSError,KeyError) as exc:issues.append(issue('error','missing_source',n.id,n.name,str(exc),{'fileId':fid}))
        if n.imagePath:
            try:
                with Image.open(docs.scenes.generated_path(n.imagePath)) as image:image.verify()
            except (ValueError,OSError) as exc:issues.append(issue('error','missing_source',n.id,n.name,str(exc)))
    return issues,source_info


def issue(severity,code,node_id,name,message,details=None):
    return {'severity':severity,'code':code,'nodeId':node_id,'name':name,'message':message,'details':details or {}}


def inspect(value, options:Options, event=None, directory=None):
    doc=docs.Document.model_validate(value);dim=dimensions(doc,options);issues,sources=_sources(doc)
    if dim['pixelWidth']*dim['pixelHeight']>MAX_PIXELS or max(dim['pixelWidth'],dim['pixelHeight'])>MAX_DIMENSION:
        issues.append(issue('error','size_limit',None,'출력 크기','최대 5,000만 픽셀, 한 변 20,000픽셀까지 출력할 수 있습니다.',dim))
    if options.background=='transparent' or (options.background=='document' and doc.artboard.background in {'transparent','none'}):
        issues.append(issue('warning','transparent_background',None,'배경','투명 배경으로 출력합니다. 제출처가 흰 배경을 요구하는지 확인하세요.'))
    result={'documentId':doc.id,'revision':doc.revision,'options':options.model_dump(),'dimensions':dim,'issues':issues,'sources':sources,'fonts':[], 'engine':'svg2pdf 0.13 / usvg 0.45.1'}
    if any(i['severity']=='error' for i in issues):result['canExport']=False;return result
    check_cancel(event)
    svg,_,_=source_svg(doc,options)
    if directory is None:
        with tempfile.TemporaryDirectory(prefix='bioart-preflight-') as tmp:analysis=convert(svg,Path(tmp),options,event=event)
    else:analysis=convert(svg,directory,options,event=event)
    result['fonts']=analysis['fonts']
    names={n.id:n.name or n.id for n in docs.walk(doc.nodes)};point_scale=options.widthMm/doc.artboard.width/25.4*72
    collected=set()
    def add(code,owner,message,details=None,severity='warning'):
        key=(code,owner)
        if key not in collected:collected.add(key);issues.append(issue(severity,code,owner,names.get(owner,'도해'),message,details))
    if analysis.get('filterPixels',0)>MAX_PIXELS:add('filter_size_limit',None,'필터 렌더링이 5,000만 픽셀 한도를 초과합니다. DPI를 낮추거나 효과를 줄이세요.',severity='error')
    available={f.casefold() for f in analysis['availableFamilies']}
    for n in docs.walk(doc.nodes):
        if n.kind=='text' and n.visible and n.fontFamily.casefold() not in available and n.fontFamily not in {'sans-serif','serif','monospace'}:
            add('missing_font',n.id,f'요청한 글꼴 “{n.fontFamily}”이 없어 대체 글꼴을 사용합니다.')
    for r in analysis['records']:
        owner=r.get('owner')
        if r['kind']=='text' and r['size']*point_scale<options.minFontPt:
            add('small_text',owner,f"최종 글자 크기 약 {r['size']*point_scale:.2f} pt가 기준 {options.minFontPt:g} pt보다 작습니다.",{'points':r['size']*point_scale})
        if r['kind']=='stroke' and 0<r['width']*point_scale<options.minStrokePt:
            add('thin_stroke',owner,f"최종 선 굵기 약 {r['width']*point_scale:.3f} pt가 기준 {options.minStrokePt:g} pt보다 가늡니다.",{'points':r['width']*point_scale})
        if r['kind']=='raster':
            effective=r['pixelsPerUnit']*doc.artboard.width/options.widthMm*25.4
            if effective<options.minRasterDpi:add('low_dpi',owner,f'원본 이미지 유효 해상도 약 {effective:.0f} DPI · 출력 DPI를 높여도 원본 세부 정보는 늘어나지 않습니다.',{'effectiveDpi':effective,'width':r['width'],'height':r['height']})
        if r['kind']=='filter':add('rasterized_effect',owner,'SVG 필터 효과는 선택한 DPI에 맞춰 부분 래스터화됩니다.')
        if r['kind']=='transparency':add('transparency',owner,'반투명 요소가 있습니다. 출력 배경에서 색을 확인하세요.')
    # Use renderer-derived transformed stroke bounds. Clipped roots are conservative checks.
    bounds={r['id']:r['bounds'] for r in analysis['records'] if r['kind']=='bounds'}
    for n in doc.nodes:
        if not n.visible or n.id not in bounds or (n.science and n.science.type=='inset'):continue
        x,y,w,h=bounds[n.id]
        if x<-.1 or y<-.1 or x+w>doc.artboard.width+.1 or y+h>doc.artboard.height+.1:
            add('out_of_bounds',n.id,'객체의 경계가 출력 영역 밖에 있습니다.'+(' 클리핑 전 경계 기준이므로 마스크를 함께 확인하세요.' if n.clip else ''),{'bounds':[x,y,w,h]})
    if any('lastresort' in f.lower() for f in analysis['fonts']):add('missing_glyph',None,'일부 문자를 표시할 수 없어 대체 기호 글꼴이 사용되었습니다.',severity='error')
    for glyph in analysis['missingGlyphs']:add('missing_glyph',None,f'출력 글꼴에 없는 문자: {glyph}',severity='error')
    if options.fontMode=='embed':
        for font in analysis['restrictedFonts']:add('font_restricted',font,f'{font}: 글꼴 부분 포함 제한이 있습니다. 윤곽선 방식을 선택하세요.',severity='error')
        if 'svg' in options.formats and analysis['fonts']:add('svg_fonts',None,'SVG 텍스트는 글꼴을 참조합니다. 다른 컴퓨터에서도 동일한 외형이 필요하면 윤곽선 방식을 사용하세요.')
    if analysis['warnings']:
        result['rendererWarnings']=list(dict.fromkeys(analysis['warnings']))
        fallback=[s for s in result['rendererWarnings'] if 'Fallback' in s]
        if fallback:add('font_fallback',None,'일부 문자는 대체 글꼴로 렌더링됩니다. 실제 사용 글꼴을 확인하세요.',{'messages':fallback})
        missing=[s for s in result['rendererWarnings'] if s.startswith('No fonts with') or s.startswith('No match for')]
        if missing:add('unrenderable_text',None,'표시할 수 없는 문자 또는 글꼴이 있습니다.',{'messages':missing},severity='error')
        other=[s for s in result['rendererWarnings'] if 'Fallback' not in s and s not in missing]
        if other:add('renderer_warning',None,'SVG 변환 과정의 경고를 확인하세요.',{'messages':other})
    result['canExport']=not any(i['severity']=='error' for i in issues)
    result['counts']={level:sum(i['severity']==level for i in issues) for level in ['error','warning']}
    return result


def physical_svg(svg,dim):
    root=etree.fromstring(svg.encode(),etree.XMLParser(resolve_entities=False,no_network=True))
    if 'viewBox' not in root.attrib:
        root.set('viewBox',f"0 0 {root.get('width')} {root.get('height')}")
    root.set('width',f"{dim['widthMm']}mm");root.set('height',f"{dim['heightMm']}mm")
    return etree.tostring(root,encoding='unicode')


def pdf_quality(path,dim,font_mode):
    reader=PdfReader(path)
    if len(reader.pages)!=1:raise ValueError('PDF 페이지 수가 올바르지 않습니다.')
    page=reader.pages[0];width=float(page.mediabox.width);height=float(page.mediabox.height)
    if abs(width-dim['pdfWidthPt'])>.05 or abs(height-dim['pdfHeightPt'])>.05:raise ValueError('PDF 물리 크기 검증에 실패했습니다.')
    fonts=[];images=[];seen=set()
    def resources(resources):
        if not resources:return
        for f in resources.get('/Font',{}).values():
            font=f.get_object();name=str(font.get('/BaseFont',''))
            descendants=font.get('/DescendantFonts',[font])
            for item in descendants:
                data=item.get_object();desc=data.get('/FontDescriptor',{});desc=desc.get_object() if hasattr(desc,'get_object') else desc
                embedded=any(k in desc for k in ['/FontFile','/FontFile2','/FontFile3']);fonts.append({'name':name,'embedded':embedded,'unicode':'/ToUnicode' in font})
        for x in resources.get('/XObject',{}).values():
            key=(getattr(x,'idnum',None),getattr(x,'generation',None))
            if key in seen:continue
            seen.add(key);obj=x.get_object()
            if obj.get('/Subtype')=='/Image':images.append({'width':obj.get('/Width'),'height':obj.get('/Height')})
            if obj.get('/Subtype')=='/Form':resources_fn(obj.get('/Resources'))
    resources_fn=resources;resources(page.get('/Resources'))
    if font_mode=='embed' and any(not f['embedded'] for f in fonts):raise ValueError('PDF에 포함되지 않은 글꼴이 있습니다.')
    if font_mode=='outline' and fonts:raise ValueError('윤곽선 PDF에 텍스트 글꼴이 남아 있습니다.')
    return {'pages':1,'widthPt':width,'heightPt':height,'fonts':fonts,'rasterImages':images,'textExtractable':bool(page.extract_text().strip()),'fontMode':font_mode}


def export_snapshot(value,options:Options,event=None,progress=lambda *_:None):
    doc=docs.Document.model_validate(value);root=workspace()/'exports';root.mkdir(parents=True,exist_ok=True)
    eid=f'{doc.id}-r{doc.revision}-{uuid.uuid4().hex[:6]}';destination=root/eid
    with tempfile.TemporaryDirectory(prefix='.publication-',dir=root) as tmp:
        stage=Path(tmp);work=stage/'engine';out=stage/'output';out.mkdir()
        progress(10,'원본과 출력 조건 검사 중')
        report=inspect(value,options,event,work)
        if not report['canExport']:raise ValueError('프리플라이트 오류: '+' / '.join(i['message'] for i in report['issues'] if i['severity']=='error'))
        check_cancel(event);progress(30,'벡터와 글꼴 변환 중')
        svg,sources,_=source_svg(doc,options);analysis=convert(svg,work,options,'export',event)
        dim=report['dimensions'];outline=(work/'outlined.svg').read_text();quality={}
        if 'pdf' in options.formats:
            shutil.copy2(work/'figure.pdf',out/'figure.pdf');quality['pdf']=pdf_quality(out/'figure.pdf',dim,options.fontMode)
        if 'svg' in options.formats:(out/'figure.svg').write_text(physical_svg(outline if options.fontMode=='outline' else svg,dim))
        check_cancel(event);progress(55,'지정 해상도로 이미지 렌더링 중')
        if set(options.formats)&{'png','tiff'}:
            # Raster outputs always use the same resolved outlines as the PDF.
            raster_root=etree.fromstring(outline.encode(),etree.XMLParser(resolve_entities=False,no_network=True))
            raster_root.set('viewBox',f"0 0 {doc.artboard.width} {doc.artboard.height}")
            raster_root.set('preserveAspectRatio','none')
            raster_root.set('width',str(dim['pixelWidth']));raster_root.set('height',str(dim['pixelHeight']))
            raw=resvg_py.svg_to_bytes(svg_string=etree.tostring(raster_root,encoding='unicode'),skip_system_fonts=True)
            with Image.open(io.BytesIO(raw)) as decoded:
                transparent=decoded.mode=='RGBA' and decoded.getextrema()[-1][0]<255
                image=decoded.convert('RGBA' if transparent else 'RGB')
                icc=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
                for fmt in ['png','tiff']:
                    if fmt not in options.formats:continue
                    check_cancel(event);progress(70 if fmt=='png' else 80,fmt.upper()+' 압축 및 해상도 기록 중')
                    path=out/('figure.'+fmt);image.save(path,format=fmt.upper(),dpi=(options.dpi,options.dpi),icc_profile=icc,**({'compression':'tiff_lzw'} if fmt=='tiff' else {}))
                    with Image.open(path) as check:
                        if check.size!=(dim['pixelWidth'],dim['pixelHeight']):raise ValueError('이미지 픽셀 크기가 예상과 다릅니다.')
                        actual_dpi=check.info.get('dpi',(0,0))
                        if any(abs(v-options.dpi)>.1 for v in actual_dpi):raise ValueError('이미지 DPI 메타데이터가 예상과 다릅니다.')
                        quality[fmt]={'width':check.width,'height':check.height,'dpi':[float(v) for v in actual_dpi],'mode':check.mode,'iccProfile':bool(check.info.get('icc_profile')),'compression':check.info.get('compression')}
                image.close()
        check_cancel(event);progress(90,'파일 무결성과 출처 기록 중')
        atomic_json(out/'document.json',value);atomic_json(out/'preflight.json',report)
        (out/'preflight.txt').write_text(f"{doc.title} · revision {doc.revision}\n{dim['widthMm']:g} × {dim['heightMm']:.3f} mm · {options.dpi} DPI\n\n"+'\n'.join(f"[{i['severity']}] {i['name']}: {i['message']}" for i in report['issues'])+'\n\nFonts: '+', '.join(report['fonts']))
        (out/'SOURCES.md').write_text('# Sources\n\n'+'\n\n'.join(f"{s['title']} · {s['source_url']} · {s['license']} · {s['credit'] or 'Credit unconfirmed'}" for s in sources))
        for file in out.glob('figure.*'):
            quality.setdefault(file.suffix[1:],{}).update(bytes=file.stat().st_size,sha256=hashlib.sha256(file.read_bytes()).hexdigest())
        atomic_json(out/'quality.json',quality)
        atomic_json(out/'manifest.json',{'document_id':doc.id,'revision':doc.revision,'options':options.model_dump(),'dimensions':dim,'sources':sources,'fonts':report['fonts'],'quality':quality,'engine':analysis['engine'],'scientific_review':'not_assessed','colorSpace':'sRGB','pdfStandard':'PDF 1.7; not certified PDF/X or PDF/A'})
        archive=stage/'export.zip'
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
            for file in sorted(out.iterdir()):z.write(file,file.name)
        with zipfile.ZipFile(archive) as z:
            if z.testzip() is not None:raise ValueError('ZIP 검증에 실패했습니다.')
        check_cancel(event)
        out.rename(destination);archive.rename(destination.with_suffix('.zip'))
        return {'path':str(destination),'download_url':f'/api/exports/{eid}.zip','revision':doc.revision,'warnings':[i['message'] for i in report['issues']],'quality':quality,'dimensions':dim,'preflight':report}


# One large export at a time bounds peak memory; immutable snapshots are captured at enqueue.
_executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='publication')
_jobs={};_lock=threading.RLock()

def _job_path(jid):
    if not re.fullmatch(r'pub-[a-f0-9]{16}',jid):raise ValueError('Invalid export job')
    return workspace()/'state/publication-jobs'/f'{jid}.json'


def settings(did):
    docs.doc_path(did)
    path=workspace()/'state/publication-settings'/f'{did}.json'
    try:return Options.model_validate_json(path.read_text()).model_dump()
    except (ValueError,OSError):return Options().model_dump()


def start(did,revision,options):
    value=docs.read(did)
    if value['revision']!=revision:raise docs.Conflict('도해가 변경되었습니다. 저장 후 다시 검사하세요.')
    jid='pub-'+uuid.uuid4().hex[:16];event=threading.Event();path=_job_path(jid)
    job={'id':jid,'documentId':did,'revision':revision,'state':'queued','progress':0,'message':'출력 대기 중','result':None,'error':None}
    with _lock:
        if sum(v[0]['state'] in {'queued','running'} for v in _jobs.values())>=3:raise ValueError('출력 대기열이 가득 찼습니다. 진행 중인 출력을 기다려 주세요.')
        _jobs[jid]=(job,event);atomic_json(path,job)
        atomic_json(workspace()/'state/publication-settings'/f'{did}.json',options.model_dump())
    def progress(value,message):
        with _lock:job.update(state='running',progress=value,message=message);atomic_json(path,job)
    def run():
        try:
            check_cancel(event)
            result=export_snapshot(copy.deepcopy(value),options,event,progress)
            # Cancellation after publication is a completed export, never a false cancelled result.
            with _lock:job.update(state='completed',progress=100,message='내보내기 완료',result=result)
        except Cancelled:
            with _lock:job.update(state='cancelled',message='내보내기 취소됨')
        except Exception as exc:
            with _lock:job.update(state='failed',message='내보내기 실패',error=str(exc))
        finally:
            with _lock:atomic_json(path,job)
    _executor.submit(run)
    return copy.deepcopy(job)


def job_status(jid):
    path=_job_path(jid)
    with _lock:
        if jid in _jobs:return copy.deepcopy(_jobs[jid][0])
    if not path.is_file():raise ValueError('출력 작업을 찾을 수 없습니다.')
    job=json.loads(path.read_text())
    if job['state'] in {'queued','running'}:
        job.update(state='failed',message='앱 종료로 출력이 중단되었습니다.',error='저장한 도해에서 다시 내보내세요.');atomic_json(path,job)
    return job


def cancel(jid):
    with _lock:
        if jid in _jobs and _jobs[jid][0]['state'] in {'queued','running'}:_jobs[jid][1].set()
    return job_status(jid)
