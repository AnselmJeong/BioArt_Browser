import csv
import json
import pytest
from PIL import Image
from bioart.pipeline import inventory, checksum
from bioart.core import Catalog


@pytest.fixture()
def library(tmp_path, monkeypatch):
    monkeypatch.setenv("BIOART_WORKSPACE", str(tmp_path))
    root = tmp_path / "BioArt_PNG_SVG"
    (root / "PNG").mkdir(parents=True)
    (root / "SVG").mkdir()
    rows = []
    logs = []
    for aid, title in [("231", "Human Lungs"), ("567", "Alveoli"), ("44", "Antibody")]:
        for fmt in ["PNG", "SVG"]:
            fid = aid + ("1" if fmt == "PNG" else "2")
            path = (
                root / f"{fmt}/{title}__BIOART-{int(aid):06}__file-{fid}.{fmt.lower()}"
            )
            if fmt == "PNG":
                Image.new("RGBA", (90, 60), (80, 140, 100, 255)).save(path)
            else:
                path.write_text(
                    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 90 60"><defs><linearGradient id="a"><stop stop-color="red"/><stop offset="1" stop-color="blue"/></linearGradient></defs><rect width="90" height="60" fill="url(#a)"/></svg>'
                )
            row = dict(
                bioart_id=aid,
                title=title,
                format=fmt,
                file_id=fid,
                license="Public Domain",
                download_url=f"https://example.com/{fid}",
            )
            rows.append(row)
            logs.append(
                dict(
                    row,
                    path=str(path.relative_to(root)),
                    sha256=checksum(path),
                    result="downloaded",
                )
            )
    rows.append(
        dict(
            bioart_id="689",
            title="MRI",
            format="SVG",
            file_id="782376",
            license="Public Domain",
            download_url="https://example.com/missing",
        )
    )
    logs.append(dict(rows[-1], path="SVG/missing.svg", result="failed"))
    (root / "SVG/missing.svg.part").write_bytes(b"")
    with (root / "download-list.csv").open("w") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    (root / "download-results.jsonl").write_text("\n".join(json.dumps(r) for r in logs))
    inventory()
    cat = Catalog()
    cat.refresh()
    import bioart.scenes as scenes

    monkeypatch.setattr(scenes, "catalog", cat)
    return cat
