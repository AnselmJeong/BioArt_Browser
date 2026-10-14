import asyncio
import base64
import io
import json
import zipfile
from pathlib import Path
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from bioart import studio, scenes, server
from bioart.config import workspace
from bioart.figure_plan import FigurePlan


def plan():
    return dict(title="폐와 폐포", explanation="폐와 폐포를 연결했습니다.",
        objects=[dict(file_id="2312",x=100,y=150,width=400,height=400,label="폐")],
        arrows=[dict(id="arrow-1",x1=510,y1=350,x2=800,y2=350,label="확대")],
        texts=[dict(id="text-1",x=800,y=250,text="폐포",font_size=24)])


class FakeClient:
    def __init__(self, events=None):
        self.events = events or []
        self.queues = {}
        self.received = None
        self.interrupted = False
    async def account(self):
        return {"connected":True}
    async def begin(self, cwd, instructions, images, prompt, schema):
        self.received=(images,prompt,schema)
        queue=asyncio.Queue()
        self.queues['t']=queue
        for event in self.events: await queue.put(event)
        return 't','r',queue
    async def interrupt(self,*args):
        self.interrupted=True
    async def close(self): pass


def finish(item):
    return [{"method":"item/completed","params":{"item":item}},
            {"method":"turn/completed","params":{"turn":{"status":"completed"}}}]


@pytest.fixture
def setup(library,monkeypatch):
    monkeypatch.setattr(studio,'catalog',library)
    return library


def test_plan_rejects_foreign_assets_and_nonfinite_geometry(setup):
    value=plan();value['objects'][0]['file_id']='442'
    with pytest.raises(ValueError,match='outside'):
        scenes.from_plan(value,['2312'])
    value=plan();value['objects'][0]['x']=float('nan')
    with pytest.raises(ValueError): FigurePlan.model_validate(value)
    value=plan();value['objects'][0]['x']=1300
    with pytest.raises(ValueError,match='clipped'): scenes.from_plan(value,['2312'])
    assert not list((workspace()/'projects').glob('scene-*.json'))


def test_edit_and_export_annotations_preserve_original(setup):
    original=setup.verified_path('2312').read_bytes()
    scene=scenes.from_plan(plan(),['2312'])
    texts=[dict(id='text-1',x=800,y=250,text='<script>test</script>',font_size=24)]
    scene=scenes.update_scene(scene['scene_id'],1,{'asset-1':{'x':120}},texts=texts)
    svg,_,_=scenes.render(scene)
    assert '&lt;script&gt;' in svg and '<script>' not in svg
    assert 'bioart-arrowhead' in svg
    with pytest.raises(ValueError,match='Revision conflict'):
        scenes.update_scene(scene['scene_id'],1,{})
    assert setup.verified_path('2312').read_bytes()==original


def test_successful_job_persists_and_reuses_latest_scene(setup):
    async def run():
        s=studio.Studio();s.client=FakeClient(finish({'type':'agentMessage','text':json.dumps(plan())}))
        p=studio.create_project(['2312']);p=await s.submit(p['id'],'폐를 보여줘','compose')
        await s.tasks[p['jobs'][-1]['id']]
        p=studio.read_project(p['id']);assert p['jobs'][-1]['status']=='completed'
        sid=p['scene_id'];scenes.update_scene(sid,1,{'asset-1':{'x':130}})
        p=await s.submit(p['id'],'라벨을 수정해줘','compose');await s.tasks[p['jobs'][-1]['id']]
        assert '"x": 130' in s.client.received[1]
        assert len(s.client.received[0])==2
        result=studio.export_project(p['id'])
        with zipfile.ZipFile(Path(result['path']).with_suffix('.zip')) as archive:
            assert {'project.json','scene.json','figure.svg','figure.png','SOURCES.md'}<=set(archive.namelist())
    asyncio.run(run())


def test_generated_image_saved_in_project_and_exported(setup):
    raw=io.BytesIO();Image.new('RGB',(150,90),'white').save(raw,'PNG')
    image=dict(type='imageGeneration',status='completed',failure=None,result=base64.b64encode(raw.getvalue()).decode(),savedPath='/etc/passwd')
    async def run():
        s=studio.Studio();s.client=FakeClient(finish(image))
        p=studio.create_project(['2312']);p=await s.submit(p['id'],'그림을 그려줘','image')
        await s.tasks[p['jobs'][-1]['id']]
        p=studio.read_project(p['id']);assert p['jobs'][-1]['status']=='completed'
        scene=json.loads(scenes.scene_path(p['scene_id']).read_text())
        assert scenes.generated_path(scene['generated_image']).is_file()
        result=studio.export_project(p['id'])
        manifest=json.loads((Path(result['path'])/'manifest.json').read_text())
        assert manifest['ai_generated'] and manifest['assets'][0]['role']=='generation_reference'
        assert (Path(result['path'])/'generated.png').is_file()
    asyncio.run(run())


def test_cancel_and_failure_keep_previous_result(setup):
    async def run():
        s=studio.Studio();s.client=FakeClient()
        p=studio.create_project(['2312']);scene=scenes.from_plan(plan(),['2312']);p['scene_id']=scene['scene_id'];studio.save_project(p)
        p=await s.submit(p['id'],'수정해줘','image')
        jid=p['jobs'][-1]['id']
        for _ in range(100):
            if jid in s.handles: break
            await asyncio.sleep(.01)
        with pytest.raises(ValueError,match='진행 중'): await s.submit(p['id'],'다시','compose')
        p=await s.cancel(p['id'],jid)
        assert p['jobs'][-1]['status']=='cancelled' and p['scene_id']==scene['scene_id']
        assert s.client.interrupted
        s.client=FakeClient(finish({'type':'agentMessage','text':'이미지 생성 없이 완료'}))
        p=await s.submit(p['id'],'그려줘','image');await s.tasks[p['jobs'][-1]['id']]
        p=studio.read_project(p['id']);assert p['jobs'][-1]['status']=='failed'
        assert p['scene_id']==scene['scene_id']
    asyncio.run(run())


def test_restart_recovery_and_path_validation(setup):
    p=studio.create_project(['2312']);p['jobs']=[dict(id='job-test',status='running')];studio.save_project(p)
    studio.Studio().recover()
    assert studio.read_project(p['id'])['jobs'][0]['status']=='interrupted'
    with pytest.raises(ValueError): studio.read_project('../secret')
    with pytest.raises(ValueError): scenes.generated_path('projects/../../secret.png')
    with pytest.raises(ValueError): studio.import_image({'savedPath':'/etc/passwd'},workspace()/'bad.png')


def test_studio_http_token_and_invalid_mode(setup,monkeypatch):
    monkeypatch.setattr(server,'catalog',setup)
    with TestClient(server.app) as client:
        token=client.get('/api/session').json()['token'];headers={'X-Bioart-Token':token}
        assert client.post('/api/studio/projects',json={'file_ids':['2312']}).status_code==403
        p=client.post('/api/studio/projects',json={'file_ids':['2312']},headers=headers).json()
        server.app.state.studio.client=FakeClient()
        response=client.post('/api/studio/projects/'+p['id']+'/messages',json={'prompt':'test','mode':'shell'},headers=headers)
        assert response.status_code==400
        assert client.get('/api/studio/projects/'+p['id']).json()['jobs']==[]


def test_cancel_before_worker_starts(setup):
    async def run():
        s=studio.Studio();s.client=FakeClient()
        p=studio.create_project(['2312']);p=await s.submit(p['id'],'그려줘','image')
        p=await s.cancel(p['id'],p['jobs'][-1]['id'])
        assert p['jobs'][-1]['status']=='cancelled'
        assert not s.tasks
    asyncio.run(run())


def test_version_selection_is_project_scoped_and_busy_guarded(setup,monkeypatch):
    monkeypatch.setattr(server,'catalog',setup)
    p=studio.create_project(['2312']);scene=scenes.from_plan(plan(),['2312'])
    p['jobs']=[dict(id='job-old',status='completed',scene_id=scene['scene_id'])];studio.save_project(p)
    with TestClient(server.app) as client:
        headers={'X-Bioart-Token':client.get('/api/session').json()['token']}
        url='/api/studio/projects/'+p['id']+'/version'
        assert client.post(url,json={'scene_id':'scene-'+'a'*12},headers=headers).status_code==400
        assert client.post(url,json={'scene_id':scene['scene_id']},headers=headers).json()['scene_id']==scene['scene_id']
        p=studio.read_project(p['id']);p['jobs'].append(dict(id='job-new',status='running'));studio.save_project(p)
        assert client.post(url,json={'scene_id':scene['scene_id']},headers=headers).status_code==400


def test_other_backend_does_not_interrupt_live_job(setup):
    first=studio.Studio();second=studio.Studio()
    p=studio.create_project(['2312']);p['jobs']=[dict(id='job-test',status='running')];studio.save_project(p)
    first.acquire()
    try:
        second.recover()
        assert studio.read_project(p['id'])['jobs'][0]['status']=='running'
        with pytest.raises(ValueError,match='다른 BioArt'): second.acquire()
    finally: first.release()
    second.recover()
    assert studio.read_project(p['id'])['jobs'][0]['status']=='interrupted'
