"""Independent local stdio MCP. No HTTP server or GUI required."""

from mcp.server.fastmcp import FastMCP, Image
from .core import catalog
from . import scenes
import json
from typing import Any
from .config import workspace

mcp = FastMCP("BioArt Browser")


@mcp.tool()
def search_assets(
    query: str = "",
    topic: str = "all",
    format: str = "",
    license: str = "",
    scope: str = "related",
    limit: int = 30,
    cursor: int = 0,
) -> dict[str, Any]:
    """Find real local artwork, with exact/alias/relation reasons and catalog version."""
    result = catalog.search(query, topic, format, license, scope, limit, cursor)
    for item in result["items"]:
        f = catalog.file(item["preview_file_id"])
        item.pop("thumbnail", None)
        item["thumbnail_path"] = str(
            workspace() / f"cache/thumbnails/{f['sha256']}.png"
        )
    result["transport_note"] = (
        "Paths are local to this machine. Use preview_assets for MCP image content."
    )
    return result


@mcp.tool()
def get_asset(artwork_or_representation_id: str) -> dict[str, Any]:
    """Get source metadata, unreviewed status, variants and exact usable file IDs."""
    return catalog.asset(artwork_or_representation_id)


@mcp.tool()
def get_related_assets(artwork_id: str) -> dict[str, Any]:
    """One-hop whole/part galleries with original relation direction and evidence."""
    return catalog.related(artwork_id)


@mcp.tool()
def preview_assets(representation_ids: list[str]) -> list:
    """Return a numbered PNG comparison board and its exact ID mapping. Maximum 24."""
    ids = []
    for rid in representation_ids:
        if not rid.startswith("rep-"):
            raise ValueError("Expected representation ID rep-<file ID>")
        ids.append(rid[4:])
    png, mapping = catalog.preview_board(ids)
    return [
        Image(data=png, format="png"),
        json.dumps(dict(catalog_version=catalog.version, mapping=mapping)),
    ]


@mcp.tool()
def export_assets(file_ids: list[str]) -> dict[str, Any]:
    """Copy exact file IDs and provenance into a new workspace exports folder. Local paths only."""
    return catalog.export(file_ids)


@mcp.tool()
def render_scene(
    file_ids: list[str], layout: str = "process", title: str = "BioArt Figure"
) -> dict[str, Any]:
    """Create a limited editable scene. Layout: process, comparison, overview, workflow."""
    scene = scenes.create_scene(file_ids, layout, title)
    return dict(scene=scene, warnings=scenes.validate(scene))


@mcp.tool()
def update_scene(
    scene_id: str, revision: int, patches: dict, title: str | None = None
) -> dict[str, Any]:
    """Revise explicit objects' x/y/width/height/label fields with revision conflict detection."""
    return scenes.update_scene(scene_id, revision, patches, title)


@mcp.tool()
def export_figure(scene_id: str) -> dict[str, Any]:
    """Export editable SVG, rendered PNG, scene JSON and attribution; scientific review remains separate."""
    return scenes.export_figure(scene_id)
