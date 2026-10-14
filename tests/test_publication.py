import copy
import json
import threading
import time
import zipfile
from pathlib import Path
import pytest
from PIL import Image, ImageChops
from pypdf import PdfReader
from bioart import documents as d, publication as p

@pytest.fixture
def document(library,monkeypatch):
    monkeypatch.setattr(d,'catalog',library)
    doc=d.create('출판 검증',['2312'])
    doc['nodes'] += [d.Node(id='n-label',kind='text',text='한글 α O₂',fontSize=36,transform=d.Transform(x=100,y=600),style=d.Style(fill='#153e25',stroke='none')).model_dump()]
    return d.save(doc['id'],doc,1,'publication-fixture')

@pytest.mark.parametrize('mode',['outline','embed'])
def test_real_export_dimensions_fonts_color_and_lossless_pixels(document,mode):
    result=p.export_snapshot(document,p.Options(widthMm=85,dpi=300,fontMode=mode))
    path=Path(result['path']);q=result['quality']
    assert q['pdf']['pages']==1 and q['pdf']['rasterImages']==[]
    assert abs(q['pdf']['widthPt']-85/25.4*72)<.01
    if mode=='outline':assert not q['pdf']['fonts']
    else:
        assert all(f['embedded'] and f['unicode'] for f in q['pdf']['fonts'])
        assert '한글' in PdfReader(path/'figure.pdf').pages[0].extract_text()
    with Image.open(path/'figure.tiff') as tiff,Image.open(path/'figure.png') as png:
        assert tiff.mode=='RGB'
        assert tiff.size==(1004,610) and tiff.info['dpi']==(300,300)
        assert tiff.info['icc_profile'] and tiff.info['compression']=='tiff_lzw'
        assert ImageChops.difference(tiff,png).getbbox() is None
    assert '85.0mm' in (path/'figure.svg').read_text()
    with zipfile.ZipFile(path.with_suffix('.zip')) as z:assert z.testzip() is None and 'quality.json' in z.namelist()
    assert d.read(document['id'])==document


def test_preflight_measures_original_resolution_and_small_transformed_text(document):
    raster=d.create('raster',['2311']);raster['nodes'][0]['width']=1000;raster['nodes'][0]['height']=700
    raster['nodes']+= [d.Node(id='n-small',kind='text',text='small',fontSize=10,fontFamily='Not Installed Bioart',transform=d.Transform(x=-40,y=20,scaleX=.5,scaleY=.5),style=d.Style(strokeWidth=.1)).model_dump()]
    r=p.inspect(raster,p.Options())
    codes={i['code'] for i in r['issues']}
    assert {'low_dpi','small_text','missing_font','out_of_bounds'}<=codes
    dpi=next(i['details']['effectiveDpi'] for i in r['issues'] if i['code']=='low_dpi')
    assert dpi<30
    r2=p.inspect(raster,p.Options(dpi=1200))
    assert next(i['details']['effectiveDpi'] for i in r2['issues'] if i['code']=='low_dpi')==dpi


def test_limits_sources_and_cancellation_leave_no_partial_output(document,monkeypatch):
    r=p.inspect(document,p.Options(widthMm=1000,dpi=2400))
    assert not r['canExport'] and any(i['code']=='size_limit' for i in r['issues'])
    changed=copy.deepcopy(document);changed['nodes'][0]['sha256']='a'*64
    assert not p.inspect(changed,p.Options())['canExport']
    event=threading.Event();event.set()
    with pytest.raises(p.Cancelled):p.export_snapshot(document,p.Options(),event)
    assert not list((p.workspace()/'exports').glob('.publication-*'))
    with pytest.raises(d.Conflict):p.start(document['id'],999,p.Options())


def test_job_uses_snapshot_persists_settings_and_cancel(document,monkeypatch):
    entered=threading.Event();release=threading.Event();captured=[]
    def fake(value,options,event,progress):
        entered.set();release.wait(5);p.check_cancel(event);captured.append(value);return {'revision':value['revision']}
    monkeypatch.setattr(p,'export_snapshot',fake)
    options=p.Options(widthMm=85,dpi=1200)
    job=p.start(document['id'],document['revision'],options);assert entered.wait(5)
    changed=copy.deepcopy(document);changed['title']='changed';d.save(document['id'],changed,document['revision'],'changed-after-enqueue')
    release.set()
    for _ in range(100):
        status=p.job_status(job['id'])
        if status['state']=='completed':break
        time.sleep(.02)
    assert status['state']=='completed' and captured[0]==document
    assert p.settings(document['id'])==options.model_dump()
    entered.clear();release.clear()
    job=p.start(document['id'],document['revision']+1,options);assert entered.wait(5);p.cancel(job['id']);release.set()
    for _ in range(100):
        status=p.job_status(job['id'])
        if status['state']=='cancelled':break
        time.sleep(.02)
    assert status['state']=='cancelled'


def test_transparent_output_preserves_alpha(document):
    document['artboard']['background']='transparent'
    r=p.export_snapshot(document,p.Options(widthMm=40,dpi=150,formats=['tiff']))
    with Image.open(Path(r['path'])/'figure.tiff') as image:
        assert image.mode=='RGBA' and image.getextrema()[-1][0]==0
    assert any(i['code']=='transparent_background' for i in r['preflight']['issues'])


def test_unrenderable_character_blocks_export(document):
    document['nodes']=[d.Node(id='n-missing',kind='text',text='\U0010ffff',transform=d.Transform(x=100,y=100)).model_dump()]
    report=p.inspect(document,p.Options())
    assert not report['canExport']
    assert any(i['code'] in {'missing_glyph','unrenderable_text'} for i in report['issues'])


def test_safe_svg_keeps_verified_pixels_but_blocks_active_and_external_resources():
    import io,base64
    from lxml import etree
    from bioart.imaging import safe_svg
    buf=io.BytesIO();Image.new('RGB',(4,4),'red').save(buf,format='PNG')
    uri='data:image/png;base64,'+base64.b64encode(buf.getvalue()).decode()
    raw=f'<svg xmlns="http://www.w3.org/2000/svg"><image id="ok" href="{uri}"/><image id="bad" href="data:image/svg+xml;base64,PHN2Zy8+"/><image id="remote" href="https://example.com/a.png"/><image id="fake" href="data:image/png;base64,ZmFrZQ=="/></svg>'
    root=etree.fromstring(safe_svg(raw.encode()))
    assert root[0].get('href')==uri
    assert all(x.get('href') is None for x in list(root)[1:])


def test_scaled_filter_uses_output_resolution_and_is_memory_bounded(tmp_path):
    svg='<svg xmlns="http://www.w3.org/2000/svg" width="1400" height="850"><defs><filter id="f"><feGaussianBlur stdDeviation="2"/></filter></defs><g transform="scale(4)"><g filter="url(#f)"><rect width="100" height="50" x="30" y="30" fill="green"/></g></g></svg>'
    a=p.convert(svg,tmp_path,p.Options())
    assert next(r for r in a['records'] if r['kind']=='filter')['parentScale']==4
    assert a['filterPixels']>900000
    with pytest.raises(ValueError,match='memory limit'):
        p.convert(svg,tmp_path,p.Options(widthMm=1000,dpi=2400),'export')
