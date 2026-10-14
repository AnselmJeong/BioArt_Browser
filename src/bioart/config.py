from pathlib import Path
import os
import json


def workspace() -> Path:
    return Path(
        os.environ.get("BIOART_WORKSPACE", Path(__file__).resolve().parents[2])
    ).resolve()


def source_root() -> Path:
    cfg = workspace() / "state/settings.json"
    settings = json.loads(cfg.read_text()) if cfg.exists() else {}
    return Path(
        os.environ.get(
            "BIOART_SOURCE_ROOT",
            settings.get("source_root", workspace() / "BioArt_PNG_SVG"),
        )
    ).resolve()


def prepare():
    for path in [
        "data/catalog",
        "data/source_snapshots",
        "data/annotations",
        "data/reviews",
        "cache/thumbnails",
        "state",
        "projects",
        "exports",
    ]:
        (workspace() / path).mkdir(parents=True, exist_ok=True)


def under(root: Path, relative: str) -> Path:
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError("Path is outside the allowed root")
    return target


def atomic_json(path: Path, value):
    import uuid

    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temp.replace(path)
