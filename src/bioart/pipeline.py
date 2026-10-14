"""Restartable, non-destructive inventory and public-page metadata ingestion."""

import csv
import hashlib
import json
import re
import sqlite3
import time
import fcntl
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import httpx
from lxml import html
from .config import workspace, source_root, prepare, under, atomic_json
from .imaging import thumbnail


def now():
    return datetime.now(timezone.utc).isoformat()


def checksum(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def inventory():
    prepare()
    lock = (workspace() / "state/catalog.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    root = source_root()
    rows = list(csv.DictReader((root / "download-list.csv").open(encoding="utf-8-sig")))
    logs = {}
    for line in (root / "download-results.jsonl").read_text().splitlines():
        item = json.loads(line)
        logs[str(item["file_id"])] = item
    physical = {
        p.name.split("__file-")[-1].split(".")[0]: str(p.relative_to(root))
        for folder in ("PNG", "SVG")
        for p in (root / folder).glob("*")
        if p.suffix.lower() in {".png", ".svg"}
    }
    started = now()
    prior = workspace() / "data/catalog/inventory-report.json"
    cached = (
        {f["id"]: f for f in json.loads(prior.read_text()).get("files", [])}
        if prior.exists()
        else {}
    )

    def inspect(row):
        fid = str(row["file_id"])
        log = logs.get(fid, {})
        item = dict(
            id=fid,
            artwork_id=str(row["bioart_id"]),
            representation_id="rep-" + fid,
            format=row["format"],
            relative_path=log.get("path", physical.get(fid, "")),
            download_url=row["download_url"],
            status="missing",
            error=None,
            sha256=None,
            bytes=0,
            annotation_status="pending_visual_review",
            pairing_status="provisional_file",
        )
        if not item["relative_path"]:
            item["error"] = "No path in log or filesystem"
            return item
        path = under(root, item["relative_path"])
        if not path.exists():
            item["status"] = (
                "incomplete"
                if path.with_suffix(path.suffix + ".part").exists()
                else "missing"
            )
            item["error"] = log.get("error", "File missing")
            return item
        item["bytes"] = path.stat().st_size
        item["sha256"] = checksum(path)
        if log.get("sha256") and log["sha256"] != item["sha256"]:
            item.update(
                status="checksum_mismatch", error="SHA-256 differs from download log"
            )
            return item
        try:
            thumb = workspace() / f"cache/thumbnails/{item['sha256']}.png"
            old = cached.get(fid, {})
            if (
                old.get("sha256") == item["sha256"]
                and old.get("status") == "valid"
                and thumb.exists()
            ):
                item["image"] = old["image"]
            else:
                item["image"] = thumbnail(path, row["format"], thumb)
            item["status"] = "valid"
        except Exception as exc:
            item.update(status="invalid", error=str(exc))
        return item

    files = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for item in pool.map(inspect, rows):
            files.append(item)
            if len(files) % 200 == 0:
                atomic_json(
                    workspace() / "state/inventory-progress.json",
                    dict(state="running", done=len(files), total=len(rows)),
                )
                print(f"Inventory {len(files)}/{len(rows)}", flush=True)
    duplicate_ids = [
        key for key, n in Counter(str(r["file_id"]) for r in rows).items() if n > 1
    ]
    known_paths = {f["relative_path"] for f in files}
    extra = [
        str(p.relative_to(root))
        for folder in ("PNG", "SVG")
        for p in (root / folder).iterdir()
        if p.is_file() and str(p.relative_to(root)) not in known_paths
    ]
    version = hashlib.sha256(
        json.dumps([(f["id"], f["sha256"], f["status"]) for f in files]).encode()
    ).hexdigest()[:16]
    report = dict(
        schema_version="0.1",
        catalog_version=version,
        started_at=started,
        finished_at=now(),
        source_root=str(root),
        total=len(rows),
        artworks=len({r["bioart_id"] for r in rows}),
        statuses=dict(Counter(f["status"] for f in files)),
        duplicate_file_ids=duplicate_ids,
        extra_files=extra,
        files=files,
    )
    atomic_json(prior, report)
    if duplicate_ids:
        raise ValueError("Duplicate manifest file IDs; catalog not published")
    stage = workspace() / "state/catalog.staging.sqlite"
    stage.unlink(missing_ok=True)
    db = sqlite3.connect(stage)
    db.executescript("""CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT);
    CREATE TABLE artworks(id TEXT PRIMARY KEY,title TEXT NOT NULL,license TEXT NOT NULL,source_url TEXT NOT NULL);
    CREATE TABLE representations(id TEXT PRIMARY KEY,artwork_id TEXT REFERENCES artworks(id),status TEXT NOT NULL);
    CREATE TABLE files(id TEXT PRIMARY KEY,artwork_id TEXT REFERENCES artworks(id),representation_id TEXT REFERENCES representations(id),status TEXT,data TEXT);
    CREATE INDEX file_artwork ON files(artwork_id);
    CREATE TABLE source_metadata(artwork_id TEXT PRIMARY KEY,status TEXT NOT NULL,data TEXT NOT NULL);
    """)
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("INSERT INTO meta VALUES (?,?)", ("version", version))
    for row in rows:
        db.execute(
            "INSERT OR IGNORE INTO artworks VALUES (?,?,?,?)",
            (
                row["bioart_id"],
                row["title"],
                row["license"],
                f"https://bioart.niaid.nih.gov/bioart/{row['bioart_id']}",
            ),
        )
    for item in files:
        db.execute(
            "INSERT INTO representations VALUES (?,?,?)",
            (item["representation_id"], item["artwork_id"], "pending_visual_review"),
        )
        db.execute(
            "INSERT INTO files VALUES (?,?,?,?,?)",
            (
                item["id"],
                item["artwork_id"],
                item["representation_id"],
                item["status"],
                json.dumps(item),
            ),
        )
    for art in db.execute("SELECT id FROM artworks").fetchall():
        snap = workspace() / f"data/source_snapshots/{art[0]}.json"
        data = (
            json.loads(snap.read_text())
            if snap.exists()
            else dict(status="pending", requested_id=art[0])
        )
        db.execute(
            "INSERT INTO source_metadata VALUES (?,?,?)",
            (art[0], data["status"], json.dumps(data)),
        )
    assert not db.execute("PRAGMA foreign_key_check").fetchall()
    db.commit()
    db.close()
    target = workspace() / "data/catalog/catalog.sqlite"
    if target.exists():
        import shutil

        shutil.copy2(target, target.with_suffix(".previous.sqlite"))
    stage.replace(target)
    atomic_json(
        workspace() / "state/inventory-progress.json",
        dict(state="completed", done=len(files), total=len(rows)),
    )
    pilot(files, rows)
    summary = (
        f"# Inventory\n\n{len(rows):,} manifest files · {report['artworks']} artworks\n\n"
        + "\n".join(f"- {k}: {v}" for k, v in report["statuses"].items())
    )
    (workspace() / "data/catalog/inventory-summary.md").write_text(
        summary
        + "\n\nAll SHA-256 values recomputed. PNG fully decoded; SVG parsed, sanitized and rendered.\n"
    )
    print(summary, flush=True)
    return report


def pilot(files, rows):
    from PIL import Image, ImageDraw

    valid = [f for f in files if f["status"] == "valid" and f["format"] == "PNG"]
    titles = {str(r["bioart_id"]): r["title"] for r in rows}
    chosen = []
    used = set()
    terms = [
        "lung",
        "alveol",
        "immune",
        "macrophage",
        "antibod",
        "microscope",
        "MRI",
        "molecul",
        "bacter",
        "arrow",
        "virus",
        "cell",
        "fish",
        "workflow",
    ]
    for term in terms:
        for f in valid:
            if (
                term.lower() in titles[f["artwork_id"]].lower()
                and f["artwork_id"] not in used
            ):
                chosen.append(f)
                used.add(f["artwork_id"])
                break
    for f in sorted(valid, key=lambda x: hashlib.sha256(x["id"].encode()).hexdigest()):
        if len(chosen) >= 64:
            break
        if f["artwork_id"] not in used:
            chosen.append(f)
            used.add(f["artwork_id"])
    atomic_json(
        workspace() / "data/annotations/pilot.json",
        dict(status="prepared_not_annotated", sample=chosen, cost=None, model=None),
    )
    board = Image.new("RGB", (1280, 8 * 170), "#f5f5f2")
    draw = ImageDraw.Draw(board)
    for i, f in enumerate(chosen):
        im = Image.open(workspace() / f"cache/thumbnails/{f['sha256']}.png")
        im.thumbnail((138, 125))
        x = (i % 8) * 160
        y = (i // 8) * 170
        board.paste(im, (x + (160 - im.width) // 2, y + 5), im)
        draw.text((x + 5, y + 135), f"{i + 1}. file {f['id']}", fill="#333333")
        draw.text((x + 5, y + 150), titles[f["artwork_id"]][:23], fill="#333333")
    board.save(workspace() / "data/annotations/pilot-contact-sheet.jpg")
    with (workspace() / "data/annotations/content-cards.jsonl").open("w") as out:
        for f in files:
            if f["status"] != "valid":
                continue
            out.write(
                json.dumps(
                    dict(
                        schema_version="0.1",
                        representation_id=f["representation_id"],
                        input_file_ids=[f["id"]],
                        input_fingerprint=f["sha256"],
                        summary_ko=None,
                        assertions=[],
                        measurements=f.get("image"),
                        annotation_status="pending_visual_review",
                        unresolved_questions=[
                            "Image content has not been visually reviewed."
                        ],
                    ),
                    ensure_ascii=False,
                )
                + "\n"
            )
    with (workspace() / "data/annotations/review-queue.jsonl").open("w") as out:
        for f in files:
            out.write(
                json.dumps(
                    dict(
                        representation_id=f["representation_id"],
                        reason="pending_visual_review"
                        if f["status"] == "valid"
                        else f["status"],
                    )
                )
                + "\n"
            )


def parse_metadata(content: str, requested_id: str, expected_title: str):
    tree = html.fromstring(content)
    # Ignore executable/hydration data. Match the visible identity, not URL digits.
    for el in tree.xpath("//script|//style"):
        el.drop_tree()
    texts = [t.strip() for t in tree.xpath("//text()") if t.strip()]
    ids = re.findall(r"BIOART-(\d+)", " ".join(texts))
    title = next(iter(tree.xpath("//h4/text()")), "").strip()
    response_ids = sorted({str(int(i)) for i in ids})
    verified = (
        response_ids == [str(int(requested_id))]
        and " ".join(title.split()).casefold()
        == " ".join(expected_title.split()).casefold()
    )

    def section(start, end):
        try:
            i = (
                len(texts) - 1 - texts[::-1].index(start)
                if start == "Anatomy"
                else texts.index(start)
            ) + 1
            j = next((k for k in range(i, len(texts)) if texts[k] in end), len(texts))
            return " ".join(texts[i:j])
        except ValueError:
            return None

    canonical = tree.xpath('//link[@rel="canonical"]/@href')
    return dict(
        requested_id=requested_id,
        response_ids=response_ids,
        title=title,
        canonical_url=canonical[0] if canonical else None,
        status="verified" if verified else "identity_conflict",
        description=section("Description", {"Representation", "File type"}),
        keywords=section(
            "Keywords", {"Collection", "Creator", "Credit", "Image Type", "Category"}
        ),
        creator=section("Creator", {"Credit", "Image Type", "Category"}),
        credit=section("Credit", {"Image Type", "Category"}),
        collection=section(
            "Collection", {"Creator", "Credit", "Image Type", "Category"}
        ),
        license=section("Licensing:", {"Category:", "Description"}),
        license_url=next(
            iter(tree.xpath('//a[contains(@href,"creativecommons.org")]/@href')), None
        ),
        anatomy=section(
            "Anatomy",
            {
                "National Institute of Allergy and Infectious Disease",
                "National Institute of Allergy & Infectious Diseases",
            },
        ),
        evidence_type="source_metadata",
        review_status="unreviewed",
    )


def collect_metadata(limit=0):
    prepare()
    rows = list(
        csv.DictReader((source_root() / "download-list.csv").open(encoding="utf-8-sig"))
    )
    arts = {str(r["bioart_id"]): r["title"] for r in rows}
    selected = list(arts.items())[: limit or None]
    with httpx.Client(
        timeout=25,
        follow_redirects=True,
        headers={"User-Agent": "BioArtBrowser/0.1 (local research catalog)"},
    ) as client:
        for index, (aid, title) in enumerate(selected):
            dest = workspace() / f"data/source_snapshots/{aid}.json"
            if dest.exists() and json.loads(dest.read_text()).get("status") in {
                "verified",
                "identity_conflict",
            }:
                continue
            url = f"https://bioart.niaid.nih.gov/bioart/{aid}"
            value = dict(
                requested_id=aid, request_url=url, status="failed", fetched_at=now()
            )
            for attempt in range(3):
                try:
                    response = client.get(url)
                    response.raise_for_status()
                    raw = response.content
                    digest = hashlib.sha256(raw).hexdigest()
                    (
                        workspace() / f"data/source_snapshots/{aid}-{digest[:12]}.html"
                    ).write_bytes(raw)
                    value.update(
                        parse_metadata(response.text, aid, title),
                        sha256=digest,
                        final_url=str(response.url),
                        snapshot=f"{aid}-{digest[:12]}.html",
                    )
                    break
                except Exception as exc:
                    value["error"] = str(exc)
                    if attempt < 2:
                        time.sleep(2**attempt)
            atomic_json(dest, value)
            dbpath = workspace() / "data/catalog/catalog.sqlite"
            if dbpath.exists():
                with sqlite3.connect(dbpath, timeout=30) as db:
                    db.execute(
                        "INSERT OR REPLACE INTO source_metadata VALUES (?,?,?)",
                        (aid, value["status"], json.dumps(value)),
                    )
            atomic_json(
                workspace() / "state/metadata-progress.json",
                dict(done=index + 1, total=len(selected), updated_at=now()),
            )
            if (index + 1) % 25 == 0:
                print(f"Metadata {index + 1}/{len(selected)}", flush=True)
            time.sleep(0.35)
    return dict(total=len(selected))


def reparse_metadata():
    """Replay preserved responses without network traffic; keep raw snapshots immutable."""
    rows = list(
        csv.DictReader((source_root() / "download-list.csv").open(encoding="utf-8-sig"))
    )
    titles = {str(r["bioart_id"]): r["title"] for r in rows}
    statuses = Counter()
    with sqlite3.connect(workspace() / "data/catalog/catalog.sqlite", timeout=30) as db:
        for dest in (workspace() / "data/source_snapshots").glob("*.json"):
            value = json.loads(dest.read_text())
            if value.get("snapshot"):
                raw = under(workspace() / "data/source_snapshots", value["snapshot"])
                value.update(
                    parse_metadata(
                        raw.read_text(),
                        value["requested_id"],
                        titles[value["requested_id"]],
                    )
                )
                value["parser_version"] = "0.1.1"
                atomic_json(dest, value)
            db.execute(
                "INSERT OR REPLACE INTO source_metadata VALUES (?,?,?)",
                (value["requested_id"], value["status"], json.dumps(value)),
            )
            statuses[value["status"]] += 1
    atomic_json(
        workspace() / "data/catalog/metadata-report.json",
        dict(statuses=dict(statuses), parsed_at=now()),
    )
    return dict(statuses)
