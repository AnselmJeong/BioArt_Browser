import copy
import json
import zipfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from bioart import documents as d, server, scenes

@pytest.fixture
def setup(library,monkeypatch,tmp_path):
    monkeypatch.setattr(d,'catalog',library)
    monkeypatch.setenv('BIOART_RECOVERY_ROOT',str(tmp_path/'recovery'))
    return library

def rect(id='box'):
    return d.Node(id=id,kind='rect',width=100,height=80,transform=d.Transform(x=300,y=200)).model_dump()

def test_blank_and_twenty_assets_roundtrip_export(setup):
    source=setup.verified_path('2312').read_bytes()
    doc=d.create('신호전달', ['2312']*20)
    assert len(doc['nodes'])==20
    doc['nodes'][0]['transform']['angle']=45
    doc['nodes'][0]['transform']['flipX']=True
    result=d.save(doc['id'],doc,1,'operation-001')
    assert result['revision']==2
    assert d.read(doc['id'])==result
    assert d.save(doc['id'],doc,1,'operation-001')==result
    with pytest.raises(d.Conflict):d.save(doc['id'],doc,1,'operation-002')
    exported=d.export(doc['id'],2)
    path=Path(exported['path'])
    assert Image.open(path/'figure.png').size==(1400,850)
    assert 'rotate(45' in (path/'figure.svg').read_text()
    with zipfile.ZipFile(path.with_suffix('.zip')) as z:
        assert {'document.json','figure.svg','figure.png','SOURCES.md','manifest.json'}<=set(z.namelist())
    assert setup.verified_path('2312').read_bytes()==source


def test_group_clip_text_and_gradient_roundtrip(setup):
    doc=d.create()
    clip=d.Node(id='mask',kind='ellipse',width=80,height=60)
    child=d.Node(id='child',kind='rect',clip=clip,style=d.Style(fill=d.Gradient(coords={'x1':0,'y1':0,'x2':100,'y2':80},stops=[d.Stop(offset=0,color='#ffffff'),d.Stop(offset=1,color='#276a57')])))
    group=d.Node(id='g',kind='group',children=[child],transform=d.Transform(x=400,y=300,angle=35,scaleX=2))
    text=d.Node(id='text',kind='text',text='<script>한글 α O₂</script>',transform=d.Transform(x=200,y=100))
    doc['nodes']=[group.model_dump(),text.model_dump()]
    saved=d.save(doc['id'],doc,1,'operation-group')
    svg,_,_=d.render(saved)
    assert '<clipPath' in svg and '<linearGradient' in svg and '&lt;script&gt;' in svg and '<script>' not in svg
    d.export(doc['id'],2)


def test_failed_workspace_write_keeps_recovery_and_current_doc(setup,monkeypatch):
    doc=d.create();original=d.read(doc['id']);doc['nodes']=[rect()]
    real=d.atomic_json
    def fail(path,value):
        if path==d.doc_path(doc['id']):raise OSError('disconnected volume')
        real(path,value)
    monkeypatch.setattr(d,'atomic_json',fail)
    with pytest.raises(OSError):d.save(doc['id'],doc,1,'operation-fail')
    assert d.read(doc['id'])==original
    assert d.recovery(doc['id'])['document']['nodes']==doc['nodes']
    monkeypatch.setattr(d,'atomic_json',real)
    d.save(doc['id'],doc,1,'operation-fail')
    assert d.recovery(doc['id']) is None


@pytest.mark.parametrize('change',[
    lambda v:v.update(schemaVersion=2),
    lambda v:v['nodes'][0]['transform'].update(x=float('nan')),
    lambda v:v['nodes'][0]['style'].update(fill='url(https://evil.test/x)'),
    lambda v:v['nodes'].append(copy.deepcopy(v['nodes'][0])),
    lambda v:v['nodes'][0].update(path='<script/>'),
    lambda v:v['nodes'][0].update(kind='connector',link={'start':{'nodeId':'missing','x':.5,'y':.5}}),
])
def test_rejects_bad_schema_and_geometry(setup,change):
    doc=d.create();doc['nodes']=[rect()];change(doc)
    with pytest.raises(ValueError):d.save(doc['id'],doc,1,'operation-bad')
    assert d.read(doc['id'])['revision']==1


def test_migration_preserves_old_file_and_implicit_arrows(setup):
    scene=scenes.create_scene(['2312','5672'])
    original=scenes.scene_path(scene['scene_id']).read_bytes()
    doc=d.migrate(scene['scene_id'])
    assert doc['sourceSceneId']==scene['scene_id']
    assert len([n for n in doc['nodes'] if n['kind']=='asset'])==2
    assert any(n['kind']=='connector' for n in doc['nodes'])
    assert scenes.scene_path(scene['scene_id']).read_bytes()==original
    d.export(doc['id'],1)


def test_api_boundaries_and_actual_export_download(setup):
    with TestClient(server.app) as c:
        headers={'X-Bioart-Token':c.get('/api/session').json()['token']}
        assert c.post('/api/documents',json={}).status_code==403
        doc=c.post('/api/documents',json={},headers=headers).json()
        doc['nodes']=[rect()]
        payload={'document':doc,'baseRevision':1,'operationId':'operation-api'}
        assert c.post('/api/documents/'+doc['id'],json=payload,headers=headers).status_code==200
        payload['operationId']='operation-stale'
        assert c.post('/api/documents/'+doc['id'],json=payload,headers=headers).status_code==409
        result=c.post('/api/documents/'+doc['id']+'/export',json={'revision':2},headers=headers).json()
        assert c.get(result['download_url']).status_code==200
        assert c.get('/api/documents/not-a-document').status_code==400
        assert c.get('/api/documents/generated-image',params={'path':'/etc/passwd'}).status_code==400


def test_unavailable_document_read_keeps_recovery(setup,monkeypatch):
    doc=d.create('disconnected');path=d.doc_path(doc['id']);real=Path.read_text
    def unavailable(self,*args,**kwargs):
        if self==path:raise OSError('volume disconnected')
        return real(self,*args,**kwargs)
    monkeypatch.setattr(Path,'read_text',unavailable)
    doc['nodes']=[rect()]
    with pytest.raises(OSError):d.save(doc['id'],doc,1,'operation-offline')
    assert d.recovery(doc['id'])['document']['nodes']==doc['nodes']


def test_future_document_cannot_be_overwritten(setup):
    doc=d.create();path=d.doc_path(doc['id']);envelope=json.loads(path.read_text())
    envelope['document']['schemaVersion']=2
    path.write_text(json.dumps(envelope));original=path.read_bytes()
    with pytest.raises(ValueError):d.save(doc['id'],doc,1,'operation-future')
    assert path.read_bytes()==original


def test_scientific_metadata_roundtrip_and_export(setup):
    doc=d.create('과학 객체 왕복')
    params=dict(width=360,height=140,spacing=18,thickness=36,count=18,seed=17,color='#276a57',accent='#d99b73')
    group=d.Node(id='science',kind='group',children=[d.Node.model_validate(rect('child'))],science={'type':'generator','version':1,'id':'membrane','params':params})
    doc['nodes']=[group.model_dump()]
    saved=d.save(doc['id'],doc,1,'science-save')
    assert d.read(doc['id'])==saved
    output=Path(d.export(doc['id'],2)['path'])
    assert json.loads((output/'document.json').read_text())['nodes'][0]['science']['params']['seed']==17
    for change in [dict(id='arbitrary-code'),dict(version=2),dict(params={**params,'count':10000})]:
        invalid=copy.deepcopy(saved);invalid['nodes'][0]['science'].update(change)
        with pytest.raises(ValueError):d.Document.model_validate(invalid)


def test_live_insets_reject_cycles_missing_sources_and_nested_insets(setup):
    doc=d.create();source=d.Node(id='source',kind='group',children=[d.Node.model_validate(rect('child'))])
    inset=d.Node(id='inset',kind='group',science={'type':'inset','version':1,'sourceId':'source','live':True,'centerX':.5,'centerY':.5,'span':.5,'size':200,'shape':'circle','color':'#276a57'})
    doc['nodes']=[source.model_dump(),inset.model_dump()];d.Document.model_validate(doc)
    for target in ['missing','inset']:
        invalid=copy.deepcopy(doc);invalid['nodes'][1]['science']['sourceId']=target
        with pytest.raises(ValueError):d.Document.model_validate(invalid)
    invalid=copy.deepcopy(doc);invalid['nodes'][0]['children'].append(invalid['nodes'].pop())
    with pytest.raises(ValueError):d.Document.model_validate(invalid)


def test_table_metadata_rejects_ragged_rows_and_unsafe_colors(setup):
    meta={'type':'table','version':1,'cells':[['A','B'],['C']],'cellWidth':100,'rowHeight':40,'fontSize':18,'header':True,'color':'#276a57','accent':'#ffffff'}
    with pytest.raises(ValueError):d.Node(id='table',kind='group',science=meta)
    meta['cells']=[['A','B']];meta['color']='url(https://example.com)'
    with pytest.raises(ValueError):d.Node(id='table',kind='group',science=meta)


def test_export_clip_keeps_pixels_inside_and_excludes_outside(setup):
    doc=d.create()
    shape=d.Node(id='shape',kind='rect',width=200,height=100,style=d.Style(fill='#ff0000',stroke='none'),transform=d.Transform(x=300,y=200),clip=d.Node(id='crop',kind='ellipse',width=80,height=60))
    doc['nodes']=[shape.model_dump()];d.save(doc['id'],doc,1,'clip-pixels')
    image=Image.open(Path(d.export(doc['id'],2)['path'])/'figure.png').convert('RGB')
    assert image.getpixel((300,200))==(255,0,0)
    assert image.getpixel((350,200))==(255,255,255)
