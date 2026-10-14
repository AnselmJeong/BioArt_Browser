import copy
import hashlib
import io
import json
import stat
import zipfile
from pathlib import Path
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from bioart import documents as d,portable as p,publication,server
from bioart.core import Catalog

@pytest.fixture
def project(library,monkeypatch,tmp_path):
    monkeypatch.setattr(d,'catalog',library)
    doc=d.create('휴대용 원본',['2312','5671'])
    generated=tmp_path/'projects/studio-123456789abc/job-123456789abc.png';generated.parent.mkdir();Image.new('RGB',(50,50),'red').save(generated)
    doc['nodes'].append(d.Node(id='n-generated',kind='image',imagePath=str(generated.relative_to(tmp_path)),sourceFileIds=['2312'],transform=d.Transform(x=600,y=400)).model_dump())
    # Scientific parameters and geometry are preserved rather than regenerated during import.
    doc['nodes'].append(d.Node(id='n-table',kind='group',science={'type':'table','version':1,'cells':[['A','B'],['1','2']],'cellWidth':120,'rowHeight':40,'fontSize':20,'header':True,'color':'#123456','accent':'#eeeeee'},children=[d.Node(id='n-table-cell',kind='text',text='A')]).model_dump())
    doc=d.save(doc['id'],doc,1,'portable-fixture')
    return doc

def rewrite(raw,mutate):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:members={n:z.read(n) for n in z.namelist()}
    mutate(members)
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w',zipfile.ZIP_DEFLATED) as z:
        for name,value in members.items():z.writestr(name,value)
    return b.getvalue()


def test_offline_roundtrip_collision_reexport_and_edit(project,monkeypatch,tmp_path):
    exported=p.export_project(project['id'],project['revision']);raw=Path(exported['path']).read_bytes()
    before=d.render(project)[0]
    destination=tmp_path/'empty';destination.mkdir();monkeypatch.setenv('BIOART_WORKSPACE',str(destination));monkeypatch.setattr(d,'catalog',Catalog())
    result=p.import_project(raw);doc=result['document']
    assert not (destination/'data/catalog/catalog.sqlite').exists()
    assert doc['id']!=project['id'] and doc['revision']==1
    assert doc['nodes'][-1]['science']==project['nodes'][-1]['science']
    assert d.render(doc)[0]==before
    assert all(n['fileId'].startswith('local-') for n in doc['nodes'][:2])
    assert d.read(doc['id'])==doc
    second=p.import_project(raw)['document'];assert second['id']!=doc['id'] and second['nodes'][0]['fileId']!=doc['nodes'][0]['fileId']
    doc['nodes'][0]['transform']['x']+=25;doc['title']='수정 후 저장';saved=d.save(doc['id'],doc,1,'after-import-edit');assert d.read(doc['id'])==saved
    again=p.export_project(saved['id'],2);third=p.import_project(Path(again['path']).read_bytes())['document']
    assert third['nodes'][0]['transform']==saved['nodes'][0]['transform']
    output=publication.export_snapshot(saved,publication.Options(widthMm=85,dpi=150,formats=['png','pdf']))
    assert Path(output['path'],'figure.pdf').exists()


@pytest.mark.parametrize('change',[
 lambda m:m.update({'../outside.txt':b'x'}),
 lambda m:m.update({'/absolute.txt':b'x'}),
 lambda m:m.update({'a\\escape':b'x'}),
 lambda m:m.update({'assets/0000.svg':b'changed'}),
 lambda m:m.pop('assets/0000.svg'),
 lambda m:m.update({'manifest.json':json.dumps({'format':'bioart-project','version':999}).encode()}),
])
def test_invalid_archive_has_no_project_side_effects(project,change):
    raw=Path(p.export_project(project['id'],2)['path']).read_bytes();before=list((p.workspace()/'projects').glob('doc-*.json'))
    with pytest.raises((ValueError,KeyError)):p.import_project(rewrite(raw,change))
    assert list((p.workspace()/'projects').glob('doc-*.json'))==before
    assert not list((p.workspace()/'projects/imports').glob('*'))


def test_zip_duplicates_symlinks_and_bombs_rejected(project,monkeypatch):
    raw=Path(p.export_project(project['id'],2)['path']).read_bytes()
    duplicate=io.BytesIO(raw)
    with zipfile.ZipFile(duplicate,'a') as z:z.writestr('document.json',b'{}')
    with pytest.raises(ValueError,match='중복'):p.unpack(duplicate.getvalue())
    buf=io.BytesIO();info=zipfile.ZipInfo('link');info.create_system=3;info.external_attr=(stat.S_IFLNK|0o777)<<16
    with zipfile.ZipFile(buf,'w') as z:z.writestr(info,'/tmp/secret')
    with pytest.raises(ValueError,match='안전'):p.unpack(buf.getvalue())
    monkeypatch.setattr(p,'MAX_TOTAL',100)
    with pytest.raises(ValueError,match='해제 크기'):p.unpack(raw)


def test_license_gate_revision_and_atomic_failure(project,monkeypatch):
    with pytest.raises(d.Conflict):p.export_project(project['id'],99)
    original=d.catalog.asset
    monkeypatch.setattr(d.catalog,'asset',lambda aid:dict(original(aid),license='Unknown'))
    with pytest.raises(ValueError,match='재배포'):p.export_project(project['id'],2)
    monkeypatch.setattr(d.catalog,'asset',lambda aid:dict(original(aid),license='CC-BY',source_status='pending'))
    with pytest.raises(ValueError,match='CC-BY'):p.export_project(project['id'],2)
    monkeypatch.setattr(d.catalog,'asset',original)
    raw=Path(p.export_project(project['id'],2)['path']).read_bytes();before=d.list_documents();real=p.atomic_json
    def fail(path,value):
        if path.parent==p.workspace()/'projects':raise OSError('disk full')
        real(path,value)
    monkeypatch.setattr(p,'atomic_json',fail)
    with pytest.raises(OSError):p.import_project(raw)
    assert d.list_documents()==before
    assert not list((p.workspace()/'projects/imports').glob('*'))


def test_api_binary_upload_and_output_zip_rejection(project):
    with TestClient(server.app) as c:
        headers={'X-Bioart-Token':server.TOKEN,'Content-Type':'application/zip'}
        result=c.post(f"/api/documents/{project['id']}/portable-export",json={'revision':2},headers={'X-Bioart-Token':server.TOKEN});assert result.status_code==200
        raw=c.get(result.json()['download_url']).content
        assert c.post('/api/documents/portable-import',content=raw).status_code==403
        assert c.post('/api/documents/portable-import',content=raw,headers=dict(headers,Origin='https://evil.test')).status_code==403
        imported=c.post('/api/documents/portable-import',content=raw,headers=headers);assert imported.status_code==200,imported.text
        bad=rewrite(raw,lambda m:m.update({'manifest.json':b'{"document_id":"foo"}'}))
        response=c.post('/api/documents/portable-import',content=bad,headers=headers)
        assert response.status_code==400 and '출력용 ZIP' in response.json()['detail']


def test_valid_manifest_with_invalid_png_rejected_without_writes(project):
    raw=Path(p.export_project(project['id'],2)['path']).read_bytes()
    def corrupt(members):
        name='images/0000.png';members[name]=b'not a PNG';m=json.loads(members['manifest.json'])
        for entry in m['files']:
            if entry['path']==name:entry.update(bytes=len(members[name]),sha256=hashlib.sha256(members[name]).hexdigest())
        members['manifest.json']=json.dumps(m).encode()
    with pytest.raises(ValueError,match='PNG'):p.import_project(rewrite(raw,corrupt))
    assert not list((p.workspace()/'projects/imports').glob('*'))
