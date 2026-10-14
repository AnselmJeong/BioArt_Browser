"""Bounded deterministic layout, editable SVG + JSON, optimistic revisions."""

import base64
import math
import textwrap
import fcntl
import json
import re
import uuid
from html import escape
from lxml import etree
import resvg_py
from .config import workspace, atomic_json, under
from .figure_plan import FigurePlan, FigureArrow, FigureText
from .imaging import safe_svg
from .core import catalog


def scene_path(sid):
    if not re.fullmatch(r"scene-[a-f0-9]{12}", sid):
        raise ValueError("Invalid scene ID")
    return workspace() / f"projects/{sid}.json"


def create_scene(file_ids, layout="process", title="BioArt Figure"):
    if layout not in {"process", "comparison", "overview", "workflow"}:
        raise ValueError("Unknown layout")
    if not 1 <= len(file_ids) <= 8:
        raise ValueError("도해에는 1–8개 파일을 선택하세요.")
    width = 1400
    height = 850
    objects = []
    for i, fid in enumerate(file_ids):
        f = catalog.file(fid)
        catalog.verified_path(fid)
        if layout == "overview" and len(file_ids) > 1:
            x, y, w, h = (
                (70, 170, 600, 540)
                if i == 0
                else (780, 185, 500, 470)
                if len(file_ids) == 2
                else (820 + ((i - 1) % 2) * 265, 150 + ((i - 1) // 2) * 175, 220, 125)
            )
        elif layout == "comparison":
            cols = 2
            w = 490
            h = min(480, 645 / ((len(file_ids) + 1) // 2) - 55)
            x = 150 + (i % 2) * 610
            y = 155 + (i // 2) * (h + 55)
        else:
            cols = min(4, len(file_ids))
            w = min(330, 1200 / cols - 30)
            h = 230 if len(file_ids) > 4 else 420
            x = 80 + (i % cols) * (1240 / cols)
            y = 150 + (i // cols) * 320
        source_title = catalog.asset(f["artwork_id"])["title"]
        capacity = max(8, int(w / 17))
        lines = textwrap.wrap(source_title, width=capacity)
        label = source_title if len(lines) <= 2 else " ".join(lines[:2])[:-1] + "…"
        objects.append(
            dict(
                id="asset-" + str(i + 1),
                file_id=str(fid),
                representation_id=f["representation_id"],
                sha256=f["sha256"],
                x=x,
                y=y,
                width=w,
                height=h,
                label=label,
                source_title=source_title,
                rotation=0,
            )
        )
    scene = dict(
        schema_version="0.1",
        scene_id="scene-" + uuid.uuid4().hex[:12],
        revision=1,
        catalog_version=catalog.version,
        title=title[:150],
        layout=layout,
        canvas=dict(width=width, height=height, background="#ffffff"),
        objects=objects,
        unresolved=["Scientific interpretation and visual suitability require review."],
        scientific_review="not_assessed",
    )
    validate(scene)
    atomic_json(scene_path(scene["scene_id"]), scene)
    return scene


def validate(scene):
    ids = set()
    if len(scene["title"]) > 65:
        raise ValueError("Title too long for the canvas; use at most 65 characters")
    if not (0 if scene.get("generated_image") else 1) <= len(scene["objects"]) <= 8:
        raise ValueError("Invalid object count")
    if scene.get("generated_image"):
        generated_path(scene["generated_image"])
    arrows = [FigureArrow.model_validate(a).model_dump() for a in scene.get("arrows", [])]
    texts = [FigureText.model_validate(t).model_dump() for t in scene.get("texts", [])]
    if len(arrows) > 24 or len(texts) > 24:
        raise ValueError("Too many annotations")
    for element in arrows + texts:
        if element["id"] in ids:
            raise ValueError("Duplicate annotation ID")
        ids.add(element["id"])
    for obj in scene["objects"]:
        if obj["id"] in ids:
            raise ValueError("Duplicate object ID")
        ids.add(obj["id"])
        if obj.get("rotation", 0) != 0:
            raise ValueError("Rotation is disabled to preserve anatomical orientation")
        for key in ["x", "y", "width", "height"]:
            val = obj[key]
            if not isinstance(val, (int, float)) or not math.isfinite(val) or not 0 <= val <= 2000:
                raise ValueError("Invalid geometry")
        if obj["width"] < 20 or obj["height"] < 20:
            raise ValueError("Object too small")
        if (
            obj["x"] + obj["width"] > scene["canvas"]["width"]
            or obj["y"] + obj["height"] + 50 > scene["canvas"]["height"]
        ):
            raise ValueError("Object or label would be clipped by canvas")
        if len(textwrap.wrap(obj["label"], width=max(8, int(obj["width"] / 17)))) > 2:
            raise ValueError("Label does not fit. Shorten it or enlarge the object.")
        if len(obj["label"]) > 120:
            raise ValueError("Label too long")
        f = catalog.file(obj["file_id"])
        if (
            f["sha256"] != obj["sha256"]
            or f["representation_id"] != obj["representation_id"]
        ):
            raise ValueError("Asset fingerprint changed")
    warnings = []
    for i, a in enumerate(scene["objects"]):
        for b in scene["objects"][i + 1 :]:
            if (
                a["x"] < b["x"] + b["width"]
                and b["x"] < a["x"] + a["width"]
                and a["y"] < b["y"] + b["height"] + 50
                and b["y"] < a["y"] + a["height"] + 50
            ):
                warnings.append(f"{a['id']} overlaps {b['id']}")
    return warnings


def update_scene(sid, revision, patches, title=None, arrows=None, texts=None):
    path = scene_path(sid)
    with path.with_suffix(".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        scene = json.loads(path.read_text())
        if scene["revision"] != revision:
            raise ValueError("Revision conflict; reload the scene")
        for oid, patch in patches.items():
            obj = next((o for o in scene["objects"] if o["id"] == oid), None)
            if obj is None:
                raise ValueError("Unknown object ID")
            if set(patch) - {"label", "x", "y", "width", "height"}:
                raise ValueError("Unsupported patch")
            obj.update(patch)
        if title is not None:
            scene["title"] = title[:150]
        if arrows is not None:
            scene["arrows"] = [FigureArrow.model_validate(a).model_dump() for a in arrows]
        if texts is not None:
            scene["texts"] = [FigureText.model_validate(t).model_dump() for t in texts]
        validate(scene)
        scene["revision"] += 1
        atomic_json(path, scene)
        return scene


def render(scene):
    warnings = validate(scene)
    width = scene["canvas"]["width"]
    height = scene["canvas"]["height"]
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="70" y="75" font-family="Arial, sans-serif" font-size="32" fill="#203d37">{escape(scene["title"])}</text>',
    ]
    if scene.get("generated_image"):
        encoded = base64.b64encode(generated_path(scene["generated_image"]).read_bytes()).decode()
        parts.append(f'<image id="generated-background" width="{width}" height="{height}" preserveAspectRatio="xMidYMid meet" xlink:href="data:image/png;base64,{encoded}"/>')
    manifest = []
    for obj in scene["objects"]:
        path = catalog.verified_path(obj["file_id"])
        f = catalog.file(obj["file_id"])
        a = catalog.asset(f["artwork_id"])
        x, y, w, h = (obj[k] for k in ["x", "y", "width", "height"])
        if f["format"] == "SVG":
            root = etree.fromstring(safe_svg(path.read_bytes()))
            # Embed as isolated SVG image: each has its own IDs, CSS, gradients and clipping scope.
            encoded = base64.b64encode(etree.tostring(root)).decode()
            mime = "image/svg+xml"
        else:
            encoded = base64.b64encode(path.read_bytes()).decode()
            mime = "image/png"
        parts.append(
            f'<g id="{escape(obj["id"])}"><image x="{x}" y="{y}" width="{w}" height="{h}" preserveAspectRatio="xMidYMid meet" xlink:href="data:{mime};base64,{encoded}"/>'
        )
        # Bounded wrapping; label remains editable text in the output SVG.
        lines = textwrap.wrap(obj["label"], width=max(8, int(w / 17)))
        for i, line in enumerate(lines):
            parts.append(
                f'<text x="{x + w / 2}" y="{y + h + 24 + i * 22}" text-anchor="middle" font-size="17" font-family="Arial, sans-serif" fill="#263b36">{escape(line)}</text>'
            )
        parts.append("</g>")
        meta = a["metadata"] if a["source_status"] == "verified" else {}
        manifest.append(
            dict(
                file_id=f["id"],
                sha256=f["sha256"],
                title=a["title"],
                format=f["format"],
                source_url=a["source_url"],
                license=a["license"],
                license_url=meta.get("license_url"),
                credit=meta.get("credit"),
            )
        )
    if scene.get("generated_image"):
        for fid in scene.get("reference_file_ids", []):
            f = catalog.file(fid)
            a = catalog.asset(f["artwork_id"])
            meta = a["metadata"] if a["source_status"] == "verified" else {}
            manifest.append(dict(file_id=fid, sha256=f["sha256"], title=a["title"],
                format=f["format"], source_url=a["source_url"], license=a["license"],
                credit=meta.get("credit"), role="generation_reference"))
    parts.append('<defs><marker id="bioart-arrowhead" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8" fill="#276a57"/></marker></defs>')
    for a in scene.get("arrows", []):
        parts.append(f'<g id="{escape(a["id"])}"><line x1="{a["x1"]}" y1="{a["y1"]}" x2="{a["x2"]}" y2="{a["y2"]}" stroke="#276a57" stroke-width="3" marker-end="url(#bioart-arrowhead)"/><text x="{(a["x1"]+a["x2"])/2}" y="{(a["y1"]+a["y2"])/2-12}" text-anchor="middle" font-size="18" font-family="Arial, sans-serif" fill="#263b36">{escape(a["label"])}</text></g>')
    for t in scene.get("texts", []):
        parts.append(f'<text id="{escape(t["id"])}" x="{t["x"]}" y="{t["y"]}" font-size="{t["font_size"]}" font-family="Arial, sans-serif" fill="#263b36">{escape(t["text"])}</text>')
    if scene["layout"] in {"process", "workflow"}:
        for a, b in zip(scene["objects"], scene["objects"][1:]):
            if a["y"] == b["y"]:
                x1 = a["x"] + a["width"] + 5
                x2 = b["x"] - 10
                y = a["y"] + a["height"] / 2
                parts.append(
                    f'<path d="M{x1},{y} H{x2} m-8,-5 l8,5 -8,5" fill="none" stroke="#84958e" stroke-width="2"/>'
                )
    parts.append("</svg>")
    return "".join(parts), manifest, warnings


def export_figure(sid):
    scene = json.loads(scene_path(sid).read_text())
    svg, manifest, warnings = render(scene)
    export_id = f"{sid}-r{scene['revision']}-{uuid.uuid4().hex[:6]}"
    directory = workspace() / "exports" / export_id
    png = resvg_py.svg_to_bytes(svg_string=svg)
    directory.mkdir()
    (directory / "figure.svg").write_text(svg)
    (directory / "figure.png").write_bytes(png)
    atomic_json(directory / "scene.json", scene)
    atomic_json(
        directory / "manifest.json",
        dict(
            catalog_version=scene["catalog_version"],
            assets=manifest,
            contains_raster=bool(scene.get("generated_image")) or any(m["format"] == "PNG" for m in manifest),
            ai_generated=bool(scene.get("generated_image")),
            warnings=warnings,
            scientific_review="not_assessed",
        ),
    )
    (directory / "SOURCES.md").write_text(
        "# Sources\n\n"
        + "\n\n".join(
            f"{m['title']} · {m['source_url']} · {m['license']} · {m['credit'] or 'Credit unconfirmed'}"
            for m in manifest
        )
    )
    import zipfile

    with zipfile.ZipFile(directory.with_suffix(".zip"), "w", zipfile.ZIP_DEFLATED) as z:
        for p in directory.iterdir():
            z.write(p, p.name)
    return dict(
        export_id=export_id,
        path=str(directory),
        download_url=f"/api/exports/{export_id}.zip",
        warnings=warnings,
    )


def generated_path(relative):
    if not re.fullmatch(r"projects/(?:studio-[a-f0-9]{12}/job-[a-f0-9]{12}\.png|imports/[a-f0-9]{32}/images/\d{4}\.png)", relative):
        raise ValueError("Invalid generated image path")
    return under(workspace() / "projects", relative.removeprefix("projects/"))


def from_plan(value, allowed_ids):
    plan = FigurePlan.model_validate(value)
    if any(o.file_id not in allowed_ids for o in plan.objects):
        raise ValueError("Codex selected an asset outside the project")
    # Build without publishing intermediate template documents.
    objects = []
    for i, o in enumerate(plan.objects):
        f = catalog.file(o.file_id)
        catalog.verified_path(o.file_id)
        objects.append(dict(o.model_dump(), id=f"asset-{i+1}", rotation=0,
            representation_id=f["representation_id"], sha256=f["sha256"],
            source_title=catalog.asset(f["artwork_id"])["title"]))
    scene = dict(schema_version="0.2", scene_id="scene-"+uuid.uuid4().hex[:12], revision=1,
        catalog_version=catalog.version, title=plan.title, layout="freeform",
        canvas=dict(width=1400, height=850, background="#ffffff"), objects=objects,
        arrows=[a.model_dump() for a in plan.arrows], texts=[t.model_dump() for t in plan.texts if t.text.strip() != plan.title.strip()],
        scientific_review="not_assessed", unresolved=[])
    validate(scene)
    atomic_json(scene_path(scene["scene_id"]), scene)
    return scene


def from_image(relative, reference_ids):
    generated_path(relative)
    scene = dict(schema_version="0.2", scene_id="scene-"+uuid.uuid4().hex[:12], revision=1,
        catalog_version=catalog.version, title="", layout="freeform",
        canvas=dict(width=1400, height=850, background="#ffffff"), objects=[], arrows=[], texts=[],
        generated_image=relative, reference_file_ids=reference_ids,
        scientific_review="not_assessed", unresolved=["AI-generated image; references may be altered."])
    validate(scene)
    atomic_json(scene_path(scene["scene_id"]), scene)
    return scene
