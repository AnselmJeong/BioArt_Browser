"""Local document endpoints; share the existing origin/session boundary."""
from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool
from . import portable
from fastapi.responses import JSONResponse, Response
from pydantic import Field
from . import documents as docs
from . import publication
from .documents import Strict, Document

router=APIRouter(prefix='/api/documents')

class Create(Strict):
    title: str = Field(default='새 과학 도해',max_length=200)
    file_ids: list[str] = Field(default_factory=list,max_length=100)

class Save(Strict):
    document: Document
    baseRevision: int
    operationId: str

class Legacy(Strict):
    scene_id: str

class Export(Strict):
    revision: int

class Publication(Export):
    options: publication.Options = Field(default_factory=publication.Options)

@router.get('')
def listing():return docs.list_documents()

@router.post('')
def create(body:Create):return docs.create(body.title,body.file_ids)

@router.post('/validate')
def validate(body:Document):
    docs.validate_sources(body)
    svg,_,warnings=docs.render(body.model_dump())
    return {'valid':True,'svg':svg,'warnings':warnings}

@router.get('/schema')
def schema():return Document.model_json_schema()

@router.get('/legacy')
def legacy():return docs.legacy_list()

@router.post('/migrate')
def migrate(body:Legacy):return docs.migrate(body.scene_id)

@router.get('/assets/{fid}')
def asset(fid:str):return docs.asset_data(fid)

@router.get('/generated-image')
def generated_image(path:str):
    import base64
    from .scenes import generated_path
    return {'url':'data:image/png;base64,'+base64.b64encode(generated_path(path).read_bytes()).decode()}

@router.get('/publication-jobs/{jid}')
def publication_job(jid:str):return publication.job_status(jid)

@router.post('/publication-jobs/{jid}/cancel')
def publication_cancel(jid:str):return publication.cancel(jid)

@router.get('/{did}/publication-settings')
def publication_settings(did:str):return publication.settings(did)

@router.post('/{did}/preflight')
def preflight(did:str,body:Publication):
    value=docs.read(did)
    if value['revision']!=body.revision:return JSONResponse({'detail':'도해가 변경되었습니다. 저장 후 다시 검사하세요.'},status_code=409)
    return publication.inspect(value,body.options)

@router.post('/{did}/publication')
def publication_start(did:str,body:Publication):
    try:return publication.start(did,body.revision,body.options)
    except docs.Conflict as exc:return JSONResponse({'detail':str(exc)},status_code=409)

@router.post('/portable-import')
async def portable_import(request:Request):
    return await run_in_threadpool(portable.import_project,await request.body())

@router.post('/{did}/portable-export')
def portable_export(did:str,body:Export):
    try:return portable.export_project(did,body.revision)
    except docs.Conflict as exc:return JSONResponse({'detail':str(exc)},status_code=409)

@router.get('/{did}')
def read(did:str):return docs.read(did)

@router.get('/{did}/recovery')
def recovery(did:str):return docs.recovery(did)

@router.post('/{did}')
def save(did:str,body:Save):
    try:return docs.save(did,body.document.model_dump(),body.baseRevision,body.operationId)
    except docs.Conflict as exc:return JSONResponse({'detail':str(exc)},status_code=409)
    except OSError:return JSONResponse({'detail':'작업 폴더에 저장하지 못했습니다. 내부 디스크의 복구본을 확인하고 다시 저장하세요.'},status_code=507)

@router.get('/{did}/svg')
def svg(did:str):return Response(docs.render(docs.read(did))[0],media_type='image/svg+xml')

@router.post('/{did}/export')
def export(did:str,body:Export):
    try:return docs.export(did,body.revision)
    except docs.Conflict as exc:return JSONResponse({'detail':str(exc)},status_code=409)
