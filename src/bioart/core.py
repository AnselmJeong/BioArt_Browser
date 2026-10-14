import hashlib
import io
import json
import re
import shutil
import sqlite3
import uuid
import zipfile
from collections import Counter
from PIL import Image, ImageDraw
from .config import workspace, source_root, under, atomic_json
from .concepts import VOCABULARY, TOPICS, RELATIONS, USAGE_QUERIES
from .pipeline import checksum


def contains(text, token):
    if re.fullmatch(r"[a-zA-Z -]+", token) and len(token) < 4:
        return re.search(r"\b" + re.escape(token) + r"\b", text, re.I) is not None
    if len(token) == 1 and re.fullmatch(r"[가-힣]", token):
        return (
            re.search(re.escape(token) + r"(?=에서|의|에|를|가|와|은|$|\s)", text)
            is not None
        )
    return token.casefold() in text.casefold()


class Catalog:
    def __init__(self):
        self.path = workspace() / "data/catalog/catalog.sqlite"
        self._signature = None
        self.items = []
        self.files = {}
        self.version = "uninitialized"

    def refresh(self):
        if not self.path.exists():
            self.items=[];self.files={};self.version="empty";self._signature=None
            return
        stat = self.path.stat()
        sig = (stat.st_mtime_ns, stat.st_size)
        if sig == self._signature:
            return
        with sqlite3.connect(self.path) as db:
            base = db.execute("SELECT value FROM meta WHERE key='version'").fetchone()[
                0
            ]
            artworks = db.execute(
                "SELECT id,title,license,source_url FROM artworks"
            ).fetchall()
            files = [json.loads(r[0]) for r in db.execute("SELECT data FROM files")]
            metadata = {
                r[0]: json.loads(r[1])
                for r in db.execute("SELECT artwork_id,data FROM source_metadata")
            }
        self.version = (
            base
            + "-"
            + hashlib.sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()[
                :8
            ]
        )
        grouped = {}
        for f in files:
            grouped.setdefault(f["artwork_id"], []).append(f)
        items = []
        for aid, title, license, url in artworks:
            fs = sorted(
                grouped.get(aid, []), key=lambda f: (f["format"] != "PNG", int(f["id"]))
            )
            usable = [f for f in fs if f["status"] == "valid"]
            meta = metadata.get(aid, {"status": "pending"})
            verified = meta.get("status") == "verified"
            text = title.casefold()
            concepts = [
                v[0] for v in VOCABULARY if any(contains(text, w) for w in v[3])
            ]
            topics = list(
                dict.fromkeys(v[2] for v in VOCABULARY if v[0] in concepts)
            ) or ["other"]
            preview = usable[0] if usable else None
            items.append(
                dict(
                    id=aid,
                    title=title,
                    license=license,
                    source_url=url,
                    files=fs,
                    file_count=len(usable),
                    formats=sorted({f["format"] for f in usable}),
                    preview_file_id=preview["id"] if preview else None,
                    thumbnail=f"/api/preview/{preview['id']}" if preview else None,
                    concepts=concepts,
                    topics=topics,
                    metadata=meta,
                    description=meta.get("description") if verified else None,
                    keywords=meta.get("keywords") if verified else None,
                    annotation_status="pending_visual_review",
                    concept_evidence="title_candidate",
                    source_status=meta.get("status", "pending"),
                )
            )
        self.items = sorted(items, key=lambda x: x["title"].casefold())
        self.files = {f["id"]: f for f in files}
        self._signature = sig

    def stats(self):
        self.refresh()
        return dict(
            catalog_version=self.version,
            artworks=len(self.items),
            files=len(self.files),
            valid_files=sum(f["status"] == "valid" for f in self.files.values()),
            statuses=dict(Counter(f["status"] for f in self.files.values())),
            metadata=dict(Counter(i["source_status"] for i in self.items)),
            topics=[
                dict(
                    id=k,
                    label=v,
                    count=sum(k in i["topics"] for i in self.items)
                    if k != "all"
                    else len(self.items),
                )
                for k, v in TOPICS
            ],
            source_root=str(source_root()),
            source_available=source_root().is_dir(),
            annotation_status="pending_visual_review",
            search_engine="local_title_alias_relation",
        )

    def search(
        self,
        q="",
        topic="all",
        format="",
        license="",
        scope="related",
        limit=60,
        cursor=0,
        source_status="",
    ):
        self.refresh()
        limit = max(1, min(int(limit), 120))
        cursor = max(0, int(cursor))
        q = q.strip().casefold()[:500]
        query_concepts = (
            {
                v[0]
                for v in VOCABULARY
                if any(contains(q, w) for w in [v[1], *v[3], *v[4]])
            }
            if q
            else set()
        )
        exact_concepts = {
            v[0]
            for v in VOCABULARY
            if q and q in [w.casefold() for w in [v[1], *v[3], *v[4]]]
        }
        if exact_concepts:
            query_concepts = exact_concepts
        usage = next(
            (u for u in USAGE_QUERIES if any(p in q for p in u["phrases"])), None
        )
        expanded = {}
        if scope == "related":
            for r in RELATIONS:
                if r["object"] in query_concepts:
                    expanded[r["subject"]] = dict(r, traversal="inverse")
                if r["subject"] in query_concepts:
                    expanded[r["object"]] = dict(r, traversal="forward")
        results = []
        for item in self.items:
            if not item["file_count"]:
                continue
            if topic != "all" and topic not in item["topics"]:
                continue
            if format and format not in item["formats"]:
                continue
            if license and license != item["license"]:
                continue
            if source_status and source_status != item["source_status"]:
                continue
            score = 0
            mode = "browse"
            reason = "제목 기반 분류 · 이미지 미검토"
            relation = None
            if q:
                title = item["title"].casefold()
                hay = title + " " + (item["keywords"] or "").casefold()
                if q in title:
                    score = 100 if q == title else 90
                    mode = "exact"
                    reason = "제목 일치"
                elif usage and set(item["concepts"]) & set(usage["concepts"]):
                    score = 70
                    mode = "usage_suggestion"
                    reason = usage["label"]
                elif set(item["concepts"]) & query_concepts:
                    score = 75
                    mode = "synonym"
                    reason = "한영 명칭·별칭 일치 · 제목 기준"
                elif set(item["concepts"]) & expanded.keys():
                    concept = next(c for c in item["concepts"] if c in expanded)
                    relation = expanded[concept]
                    score = 55
                    mode = "relation"
                    reason = relation["label"]
                elif q in hay:
                    score = 50
                    mode = "exact"
                    reason = "원본 키워드 일치"
                elif all(w in hay for w in q.split()):
                    score = 40
                    mode = "exact"
                    reason = "원본 텍스트 일치"
                else:
                    continue
            result = {
                k: v
                for k, v in item.items()
                if k not in {"files", "metadata", "description", "keywords"}
            }
            if format:
                f = next(
                    f
                    for f in item["files"]
                    if f["status"] == "valid" and f["format"] == format
                )
                result.update(
                    preview_file_id=f["id"], thumbnail=f"/api/preview/{f['id']}"
                )
            result.update(
                score=score, match_type=mode, reason=reason, relation=relation
            )
            results.append(result)
        results.sort(key=lambda x: (-x["score"], x["title"].casefold()))
        return dict(
            catalog_version=self.version,
            query=q,
            total=len(results),
            items=results[cursor : cursor + limit],
            next_cursor=cursor + limit if len(results) > cursor + limit else None,
            resolved_concepts=[
                dict(id=v[0], label=v[1]) for v in VOCABULARY if v[0] in query_concepts
            ],
            scope=scope,
            semantics="Local aliases and a documented one-hop relation; no embedding model.",
        )

    def asset(self, aid):
        if str(aid).startswith("local-"):
            from .portable import local_record
            return local_record(aid)[0]["asset"]
        self.refresh()
        aid = str(aid)
        if aid.startswith("rep-"):
            f = self.file(aid.removeprefix("rep-"))
            aid = f["artwork_id"]
        result = next((i for i in self.items if i["id"] == aid), None)
        if not result:
            raise ValueError("Unknown artwork")
        return dict(result, catalog_version=self.version)

    def file(self, fid):
        if str(fid).startswith("local-"):
            from .portable import local_record
            return local_record(fid)[0]["file"]
        self.refresh()
        if str(fid) not in self.files:
            raise ValueError("Unknown file")
        return self.files[str(fid)]

    def verified_path(self, fid):
        f = self.file(fid)
        if f["status"] != "valid":
            raise ValueError("File is not usable: " + f["status"])
        if str(fid).startswith("local-"):
            from .portable import local_record
            path=local_record(fid)[1]
        else:path = under(source_root(), f["relative_path"])
        if not path.is_file():
            raise ValueError(
                "원본 폴더를 찾을 수 없습니다. 자료 경로를 다시 연결하세요."
            )
        if checksum(path) != f["sha256"]:
            raise ValueError("Source changed since inventory. Rebuild before using it.")
        return path

    def related(self, aid):
        asset = self.asset(aid)
        groups = []
        for c in asset["concepts"]:
            for r in RELATIONS:
                target = (
                    r["subject"]
                    if r["object"] == c
                    else r["object"]
                    if r["subject"] == c
                    else None
                )
                if target:
                    matches = [
                        dict(id=i["id"], title=i["title"], thumbnail=i["thumbnail"])
                        for i in self.items
                        if target in i["concepts"] and i["file_count"]
                    ]
                    groups.append(
                        dict(
                            label="구성 요소" if r["object"] == c else "전체 구조",
                            relation=r,
                            items=matches,
                        )
                    )
        return dict(catalog_version=self.version, groups=groups)

    def export(self, file_ids):
        if not 1 <= len(file_ids) <= 100:
            raise ValueError("Choose 1–100 files")
        selected = list(dict.fromkeys(str(i) for i in file_ids))
        paths = {fid: self.verified_path(fid) for fid in selected}
        export_id = "assets-" + uuid.uuid4().hex[:12]
        staging = workspace() / "exports" / ("." + export_id)
        staging.mkdir(parents=True)
        try:
            manifest = []
            for fid, path in paths.items():
                f = self.file(fid)
                a = self.asset(f["artwork_id"])
                meta = a["metadata"] if a["source_status"] == "verified" else {}
                name = f"{fid}-{path.name}"
                shutil.copyfile(path, staging / name)
                if checksum(staging / name) != f["sha256"]:
                    raise ValueError("Source changed during export; no bundle published")
                manifest.append(
                    dict(
                        file_id=fid,
                        representation_id=f["representation_id"],
                        artwork_id=a["id"],
                        title=a["title"],
                        filename=name,
                        sha256=f["sha256"],
                        format=f["format"],
                        source_url=a["source_url"],
                        license=a["license"],
                        license_url=meta.get("license_url"),
                        credit=meta.get("credit"),
                        creator=meta.get("creator"),
                        license_detail_status="source_available"
                        if meta.get("license_url")
                        else "unconfirmed",
                        annotation_status=a["annotation_status"],
                    )
                )
            value = dict(catalog_version=self.version, files=manifest)
            atomic_json(staging / "manifest.json", value)
            (staging / "SOURCES.md").write_text(
                "# BioArt sources\n\n"
                + "\n\n".join(
                    f"- {m['title']} · file {m['file_id']}\n  {m['source_url']}\n  {m['license']} · {m['credit'] or 'Credit not confirmed'}"
                    for m in manifest
                )
            )
            target = staging.with_name(export_id)
            staging.rename(target)
            zip_path = target.with_suffix(".zip")
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
                for p in target.iterdir():
                    z.write(p, p.name)
            return dict(
                export_id=export_id,
                path=str(target),
                zip_path=str(zip_path),
                download_url=f"/api/exports/{zip_path.name}",
                **value,
            )
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def preview_board(self, file_ids):
        if not 1 <= len(file_ids) <= 24:
            raise ValueError("Choose 1–24 files")
        board = Image.new("RGB", (800, ((len(file_ids) + 3) // 4) * 220), "#f4f3ee")
        draw = ImageDraw.Draw(board)
        mapping = []
        for i, fid in enumerate(file_ids):
            f = self.file(fid)
            if f["status"] != "valid":
                raise ValueError("Unavailable preview")
            im = Image.open(
                workspace() / f"cache/thumbnails/{f['sha256']}.png"
            ).convert("RGBA")
            im.thumbnail((180, 170))
            x = (i % 4) * 200
            y = (i // 4) * 220
            board.paste(im, (x + (200 - im.width) // 2, y + 8), im)
            draw.text((x + 8, y + 184), f"{i + 1} | file {fid}", fill="#222222")
            draw.text(
                (x + 8, y + 201),
                self.asset(f["artwork_id"])["title"][:27],
                fill="#222222",
            )
            mapping.append(
                dict(
                    number=i + 1, file_id=fid, representation_id=f["representation_id"]
                )
            )
        buf = io.BytesIO()
        board.save(buf, format="PNG")
        return buf.getvalue(), mapping


catalog = Catalog()
