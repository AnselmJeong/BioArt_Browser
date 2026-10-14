import json
import zipfile
from pathlib import Path
import pytest
from bioart.config import workspace, under
from bioart.pipeline import inventory, parse_metadata
from bioart.imaging import safe_svg
from bioart import scenes


def test_inventory_accounts_for_every_file_and_preserves_input(library):
    stats = library.stats()
    assert stats["statuses"] == {"valid": 6, "incomplete": 1}
    assert stats["artworks"] == 4
    assert library.file("782376")["sha256"] is None
    assert (workspace() / "BioArt_PNG_SVG/SVG/missing.svg.part").exists()
    assert (
        len(
            (workspace() / "data/annotations/content-cards.jsonl")
            .read_text()
            .splitlines()
        )
        == 6
    )


def test_rebuild_is_stable_and_recovers_catalog(library):
    version = library.version
    inventory()
    library.refresh()
    assert library.version == version
    assert (workspace() / "data/catalog/catalog.previous.sqlite").exists()


def test_korean_lung_finds_alveoli_by_part_relation(library):
    r = library.search("폐")
    items = {i["id"]: i for i in r["items"]}
    assert items["231"]["match_type"] == "synonym"
    assert items["567"]["match_type"] == "relation"
    assert items["567"]["relation"]["subject"] == "alveolus"
    assert items["567"]["relation"]["object"] == "lung"
    assert items["567"]["relation"]["traversal"] == "inverse"
    assert items["567"]["relation"]["evidence_ref"]
    assert "567" not in {i["id"] for i in library.search("폐", scope="direct")["items"]}


def test_specific_alias_does_not_resolve_to_whole(library):
    r = library.search("폐포", scope="direct")
    assert [c["id"] for c in r["resolved_concepts"]] == ["alveolus"]
    assert [a["id"] for a in r["items"]] == ["567"]
    assert library.search("산소가 혈액으로 이동하는 과정")["total"] >= 1


def test_filters_precede_ranking_and_pagination_is_unique(library):
    r = library.search("폐", format="SVG")
    assert all(
        library.file(i["preview_file_id"])["format"] == "SVG" for i in r["items"]
    )
    assert library.search("폐", license="CC-BY")["total"] == 0
    first = library.search(limit=1)
    second = library.search(limit=1, cursor=first["next_cursor"])
    assert first["items"][0]["id"] != second["items"][0]["id"]
    assert library.search("this-does-not-exist")["total"] == 0


def test_provisional_representation_is_per_file(library):
    a = library.asset("231")
    assert len({f["representation_id"] for f in a["files"]}) == 2
    assert all(f["pairing_status"] == "provisional_file" for f in a["files"])
    assert all(f["annotation_status"] == "pending_visual_review" for f in a["files"])


def test_export_has_exact_fingerprints_and_attribution(library):
    result = library.export(["2312", "5671", "2312"])
    assert len(result["files"]) == 2
    with zipfile.ZipFile(result["zip_path"]) as z:
        assert "manifest.json" in z.namelist() and "SOURCES.md" in z.namelist()
        manifest = json.loads(z.read("manifest.json"))
        assert {f["file_id"] for f in manifest["files"]} == {"2312", "5671"}
        assert all(f["sha256"] and f["source_url"] for f in manifest["files"])
        assert all(
            f["license_detail_status"] == "unconfirmed" for f in manifest["files"]
        )


def test_changed_or_incomplete_file_cannot_be_exported(library):
    with pytest.raises(ValueError):
        library.export(["782376"])
    path = library.verified_path("2311")
    path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="Source changed"):
        library.export(["2311"])


def test_path_escape_and_symlink_rejected(tmp_path):
    with pytest.raises(ValueError):
        under(tmp_path, "../secrets")
    (tmp_path / "link").symlink_to("/tmp")
    with pytest.raises(ValueError):
        under(tmp_path, "link/secret")


def test_source_id_conflict_is_quarantined():
    doc = "<h4>Domestic Cat</h4><p>BIOART-000601</p><h6>Description</h6><p>Cat</p><h6>Representation</h6>"
    assert parse_metadata(doc, "202", "Hepatocyte")["status"] == "identity_conflict"
    assert parse_metadata(doc, "601", " Domestic Cat ")["status"] == "verified"


def test_svg_active_content_and_external_resources_removed():
    raw = b'<svg xmlns="http://www.w3.org/2000/svg" onload="bad()"><script>bad()</script><image href="file:///etc/passwd"/><use href="https://example.com/a"/><rect fill="url(https://evil/a)"/><foreignObject/><style>@import url(https://evil); .x {fill:url(#safe)}</style></svg>'
    clean = safe_svg(raw).decode()
    assert (
        "script" not in clean and "onload" not in clean and "foreignObject" not in clean
    )
    assert "file:" not in clean and "https:" not in clean
    assert "url(#safe)" in clean
    with pytest.raises(ValueError):
        safe_svg(
            b'<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]><svg>&x;</svg>'
        )


@pytest.mark.parametrize("layout", ["process", "comparison", "overview", "workflow"])
def test_scene_round_trip_and_exports(library, layout):
    s = scenes.create_scene(["2312", "5671"], layout, "Gas exchange")
    s2 = scenes.update_scene(s["scene_id"], 1, {"asset-1": {"label": "Lung"}})
    assert s2["revision"] == 2 and s2["objects"][1] == s["objects"][1]
    with pytest.raises(ValueError, match="Revision conflict"):
        scenes.update_scene(s["scene_id"], 1, {})
    result = scenes.export_figure(s["scene_id"])
    p = Path(result["path"])
    assert (p / "figure.png").read_bytes().startswith(b"\x89PNG")
    assert "data:image/svg+xml;base64," in (p / "figure.svg").read_text()
    assert json.loads((p / "manifest.json").read_text())["contains_raster"] is True
    assert json.loads((p / "scene.json").read_text())["objects"][0]["label"] == "Lung"


def test_scene_rejects_clipping_and_script_injection(library):
    s = scenes.create_scene(["2311"], title="<script>alert(1)</script>")
    svg, _, _ = scenes.render(s)
    assert "<script>" not in svg
    with pytest.raises(ValueError, match="clipped"):
        scenes.update_scene(s["scene_id"], 1, {"asset-1": {"x": 1400}})
    assert json.loads(scenes.scene_path(s["scene_id"]).read_text())["revision"] == 1
    with pytest.raises(ValueError):
        scenes.scene_path("../../secret")


def test_preview_board_maps_exact_ids(library):
    png, mapping = library.preview_board(["2312", "5671"])
    assert png.startswith(b"\x89PNG")
    assert mapping == [
        {"number": 1, "file_id": "2312", "representation_id": "rep-2312"},
        {"number": 2, "file_id": "5671", "representation_id": "rep-5671"},
    ]


@pytest.mark.parametrize("layout", ["process", "comparison", "overview", "workflow"])
@pytest.mark.parametrize("count", [1, 2, 3, 4, 5, 6, 7, 8])
def test_supported_layout_capacity_stays_inside_canvas(library, layout, count):
    scene = scenes.create_scene(["2312"] * count, layout)
    assert scenes.validate(scene) == []


def test_copy_time_change_never_publishes_bundle(library, monkeypatch):
    import bioart.core as core

    original = core.shutil.copyfile

    def corrupt_copy(source, target):
        original(source, target)
        target.write_bytes(b"changed during copy")

    monkeypatch.setattr(core.shutil, "copyfile", corrupt_copy)
    with pytest.raises(ValueError, match="during export"):
        library.export(["2311"])
    assert not list((workspace() / "exports").iterdir())
