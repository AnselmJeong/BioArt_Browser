"""End-to-end local stdio client check, using the official SDK and exact files."""

import asyncio
import json
import sys
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


async def verify():
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "bioart", "mcp", "--workspace", str(ROOT)]
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            names = [t.name for t in (await session.list_tools()).tools]
            assert {
                "search_assets",
                "get_asset",
                "get_related_assets",
                "preview_assets",
                "export_assets",
            } <= set(names)
            result = await session.call_tool("search_assets", {"query": "폐"})
            assert not result.isError
            data = result.structuredContent
            assert any(a["match_type"] == "relation" for a in data["items"])
            aid = data["items"][0]["id"]
            asset = await session.call_tool(
                "get_asset", {"artwork_or_representation_id": aid}
            )
            a = asset.structuredContent
            f = next(
                f for f in a["files"] if f["status"] == "valid" and f["format"] == "SVG"
            )
            preview = await session.call_tool(
                "preview_assets", {"representation_ids": [f["representation_id"]]}
            )
            assert not preview.isError, preview
            assert any(c.type == "image" for c in preview.content), preview
            output = await session.call_tool("export_assets", {"file_ids": [f["id"]]})
            assert not output.isError
            assert Path(output.structuredContent["path"]).is_dir()
            scene = await session.call_tool(
                "render_scene",
                {
                    "file_ids": [f["id"]],
                    "layout": "overview",
                    "title": "MCP validation",
                },
            )
            assert not scene.isError, scene
            s = scene.structuredContent["scene"]
            revised = await session.call_tool(
                "update_scene",
                {
                    "scene_id": s["scene_id"],
                    "revision": s["revision"],
                    "patches": {"asset-1": {"label": "Human lungs"}},
                },
            )
            assert not revised.isError
            figure = await session.call_tool(
                "export_figure", {"scene_id": s["scene_id"]}
            )
            assert not figure.isError, figure
            report = {
                "tools": names,
                "search_count": data["total"],
                "selected_file": f["id"],
                "image_content_received": True,
                "export": output.structuredContent["path"],
                "figure": figure.structuredContent["path"],
                "client": "Official MCP Python SDK ClientSession over stdio",
                "catalog_version": data["catalog_version"],
            }
            (ROOT / "state/mcp-validation.json").write_text(
                json.dumps(report, indent=2)
            )
            print(json.dumps(report, indent=2))


asyncio.run(verify())
