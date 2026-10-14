import json
import re
import secrets
import sys
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from .config import workspace, atomic_json
from .core import catalog
from . import scenes, studio
from .document_routes import router as document_router
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
    app.state.studio = studio.Studio()
    app.state.studio.recover()
    yield
    await app.state.studio.close()


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
TOKEN = secrets.token_urlsafe(32)


@app.middleware("http")
async def protect(request: Request, call_next):
    host = request.headers.get("host", "").split(":")[0]
    if host not in {"127.0.0.1", "localhost", "testserver"}:
        return JSONResponse({"detail": "Invalid host"}, status_code=403)
    if request.method not in {"GET", "HEAD"}:
        if request.headers.get("x-bioart-token") != TOKEN:
            return JSONResponse({"detail": "Invalid session token"}, status_code=403)
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            return JSONResponse({"detail": "Invalid origin"}, status_code=403)
        limit = 100_000_000 if request.url.path=="/api/documents/portable-import" else 16_000_000 if request.url.path.startswith("/api/documents") else 200000
        try:
            declared_size = int(request.headers.get("content-length", "0"))
        except ValueError:
            return JSONResponse({"detail": "Invalid content length"}, status_code=400)
        if declared_size > limit:
            return JSONResponse({"detail": "Request too large"}, status_code=413)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > limit:
                return JSONResponse({"detail": "Request too large"}, status_code=413)
        request._body = bytes(body)
    try:
        response = await call_next(request)
    except (ValueError, FileNotFoundError, KeyError) as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; object-src 'none'; frame-ancestors 'none'; connect-src 'self'"
    )
    return response


@app.exception_handler(ValueError)
async def invalid(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/session")
def session():
    p = workspace() / "state/session.json"
    return dict(token=TOKEN, state=json.loads(p.read_text()) if p.exists() else {})


class SessionBody(BaseModel):
    tray: list[str] = Field(default_factory=list, max_length=100)
    query: str = Field(default="", max_length=500)
    topic: str = "all"
    format: str = ""
    license: str = ""
    scope: str = "related"


@app.post("/api/session")
def save_session(body: SessionBody):
    atomic_json(workspace() / "state/session.json", body.model_dump())
    return {"ok": True}


@app.get("/api/stats")
def stats():
    return catalog.stats()


@app.get("/api/search")
def search(
    q: str = "",
    topic: str = "all",
    format: str = "",
    license: str = "",
    scope: str = "related",
    limit: int = 60,
    cursor: int = 0,
    source_status: str = "",
):
    return catalog.search(
        q, topic, format, license, scope, limit, cursor, source_status
    )


@app.get("/api/assets/{aid}")
def asset(aid: str):
    return catalog.asset(aid)


@app.get("/api/related/{aid}")
def related(aid: str):
    return catalog.related(aid)


@app.get("/api/files/{fid}")
def file_info(fid: str):
    return dict(
        catalog.file(fid),
        artwork=catalog.asset(catalog.file(fid)["artwork_id"])["title"],
    )


@app.get("/api/preview/{fid}")
def preview(fid: str, size: int = 400):
    f = catalog.file(fid)
    if f["status"] != "valid":
        raise ValueError("Unavailable preview")
    target = workspace() / f"cache/thumbnails/{f['sha256']}.png"
    if size > 400:
        size = min(size, 1600)
        target = workspace() / f"cache/thumbnails/{f['sha256']}-{size}.png"
        if not target.exists():
            from .imaging import thumbnail

            thumbnail(catalog.verified_path(fid), f["format"], target, size)
    return FileResponse(target, headers={"Cache-Control": "public, max-age=3600"})


@app.get("/api/original/{fid}")
def original(fid: str):
    path = catalog.verified_path(fid)
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


class ExportBody(BaseModel):
    file_ids: list[str] = Field(min_length=1, max_length=100)


@app.post("/api/export")
def export(body: ExportBody):
    return catalog.export(body.file_ids)


@app.post("/api/compare")
def compare(body: ExportBody):
    data, _ = catalog.preview_board(body.file_ids)
    return Response(data, media_type="image/png")


@app.get("/api/exports/{name}")
def download(name: str):
    if not re.fullmatch(
        r"(?:project-doc-[a-f0-9]{12}-r\d+-[a-f0-9]{6}|assets-[a-f0-9]{12}|(?:scene|doc)-[a-f0-9]{12}-r\d+-[a-f0-9]{6})\.zip", name
    ):
        raise ValueError("Invalid export")
    return FileResponse(workspace() / "exports" / name, filename=name)


class SceneBody(BaseModel):
    file_ids: list[str] = Field(min_length=1, max_length=8)
    layout: str = "process"
    title: str = Field(default="BioArt Figure", max_length=150)


@app.post("/api/scenes")
def create_scene(body: SceneBody):
    return scenes.create_scene(**body.model_dump())


@app.get("/api/scenes/{sid}")
def read_scene(sid: str):
    return json.loads(scenes.scene_path(sid).read_text())


@app.get("/api/scenes/{sid}/preview")
def scene_preview(sid: str):
    scene = json.loads(scenes.scene_path(sid).read_text())
    svg, _, _ = scenes.render(scene)
    import resvg_py

    return Response(
        resvg_py.svg_to_bytes(svg_string=svg, width=1000),
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


class ScenePatch(BaseModel):
    revision: int
    patches: dict
    title: str | None = None
    arrows: list[dict] | None = None
    texts: list[dict] | None = None


@app.post("/api/scenes/{sid}")
def edit_scene(sid: str, body: ScenePatch):
    return scenes.update_scene(sid, **body.model_dump())


@app.post("/api/scenes/{sid}/export")
def figure_export(sid: str):
    return scenes.export_figure(sid)


class RootBody(BaseModel):
    path: str


@app.post("/api/settings/source")
def reconnect(body: RootBody):
    from .pipeline import checksum

    root = Path(body.path).expanduser().resolve()
    if not (root / "download-list.csv").is_file():
        raise ValueError("download-list.csv가 있는 폴더를 선택하세요.")
    catalog.refresh()
    # Verify every known usable file before committing the root change.
    from .config import under

    for f in catalog.files.values():
        if f["status"] == "valid":
            path = under(root, f["relative_path"])
            if not path.is_file() or checksum(path) != f["sha256"]:
                raise ValueError("File missing or checksum mismatch: " + f["id"])
    atomic_json(workspace() / "state/settings.json", {"source_root": str(root)})
    return {"ok": True, "source_root": str(root)}


class ProjectBody(BaseModel):
    file_ids: list[str] = Field(min_length=1, max_length=8)


class PromptBody(BaseModel):
    prompt: str = Field(min_length=1, max_length=6000)
    mode: str


@app.get("/api/codex/status")
async def codex_status():
    return await app.state.studio.status()


@app.post("/api/codex/login")
async def codex_login():
    return await app.state.studio.client.login()


@app.get("/api/studio/projects")
def projects():
    return studio.list_projects()


@app.post("/api/studio/projects")
def new_project(body: ProjectBody):
    return studio.create_project(body.file_ids)


@app.get("/api/studio/projects/{pid}")
def project(pid: str):
    return studio.read_project(pid)


@app.post("/api/studio/projects/{pid}/messages")
async def project_message(pid: str, body: PromptBody):
    return await app.state.studio.submit(pid, body.prompt, body.mode)


@app.post("/api/studio/projects/{pid}/cancel/{jid}")
async def cancel_job(pid: str, jid: str):
    return await app.state.studio.cancel(pid, jid)


class VersionBody(BaseModel):
    scene_id: str


@app.post("/api/studio/projects/{pid}/version")
def select_version(pid: str, body: VersionBody):
    p = studio.read_project(pid)
    if any(j["status"] in {"queued", "running"} for j in p["jobs"]):
        raise ValueError("제작이 끝난 뒤 버전을 선택하세요.")
    if not any(j.get("scene_id") == body.scene_id and j["status"] == "completed" for j in p["jobs"]):
        raise ValueError("이 프로젝트의 완료된 결과를 선택하세요.")
    p["scene_id"] = body.scene_id
    studio.save_project(p)
    return p


@app.post("/api/studio/projects/{pid}/export")
def studio_export(pid: str):
    return studio.export_project(pid)


@app.get("/api/scenes/{sid}/svg")
def scene_svg(sid: str):
    scene = json.loads(scenes.scene_path(sid).read_text())
    svg, _, _ = scenes.render(scene)
    return Response(svg, media_type="image/svg+xml", headers={"Cache-Control": "no-store"})


app.include_router(document_router)

WEB = Path(getattr(sys, "_MEIPASS", workspace())) / "web"
app.mount("/", StaticFiles(directory=WEB, html=True), name="ui")
