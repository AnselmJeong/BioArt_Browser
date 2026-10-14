"""Safe derivative images; never edit an input asset."""

import io
import base64
import binascii
import re
from pathlib import Path
from lxml import etree
from PIL import Image
import resvg_py


def safe_embedded_raster(value: str) -> bool:
    """Allow verified inline pixels only; never external or nested SVG resources."""
    match = re.fullmatch(r'data:image/(png|jpeg);base64,([A-Za-z0-9+/=\s]+)', value)
    if not match or len(value) > 30_000_000:
        return False
    try:
        raw = base64.b64decode(re.sub(r'\s', '', match[2]), validate=True)
        with Image.open(io.BytesIO(raw)) as image:
            if image.format != {'png':'PNG','jpeg':'JPEG'}[match[1]] or image.width*image.height > 25_000_000:
                return False
            image.verify()
        return True
    except (ValueError, OSError, binascii.Error, Image.DecompressionBombError):
        return False


def safe_svg(data: bytes) -> bytes:
    if len(data) > 30_000_000:
        raise ValueError("SVG exceeds size limit")
    if re.search(rb"<!\s*(?:DOCTYPE|ENTITY)", data, re.I):
        raise ValueError("SVG DTD/entities are not allowed")
    root = etree.fromstring(
        data, etree.XMLParser(resolve_entities=False, no_network=True)
    )
    if etree.QName(root).localname != "svg":
        raise ValueError("Not an SVG")
    for el in list(root.iter()):
        if not isinstance(el.tag, str):
            continue
        if etree.QName(el).localname in {
            "script",
            "foreignObject",
            "iframe",
            "object",
            "embed",
            "animate",
            "set",
            "animateTransform",
        }:
            if el.getparent() is not None:
                el.getparent().remove(el)
            continue
        for name, val in list(el.attrib.items()):
            local = etree.QName(name).localname.lower()
            if local.startswith("on") or (
                local in {"href", "src"} and not val.startswith("#")
                and not (local == "href" and etree.QName(el).localname == "image" and safe_embedded_raster(val))
            ):
                del el.attrib[name]
            elif (
                re.search(r'url\s*\(\s*[\'"]?(?!#)', val, re.I)
                and "url(" in val.lower()
            ):
                # Retain only local fragment references, never load network/files.
                el.attrib[name] = re.sub(
                    r"url\(([^)]+)\)",
                    lambda m: (
                        m.group(0) if m[1].strip(" \"'").startswith("#") else "none"
                    ),
                    val,
                    flags=re.I,
                )
        if etree.QName(el).localname == "style" and el.text:
            el.text = re.sub(r"@import[^;]+;", "", el.text, flags=re.I)
            el.text = re.sub(
                r"url\(([^)]+)\)",
                lambda m: m.group(0) if m[1].strip(" \"'").startswith("#") else "none",
                el.text,
                flags=re.I,
            )
    return etree.tostring(root)


def thumbnail(path: Path, fmt: str, target: Path, size=400):
    if fmt == "SVG":
        clean = safe_svg(path.read_bytes())
        img = Image.open(
            io.BytesIO(
                resvg_py.svg_to_bytes(
                    svg_string=clean.decode(), width=size, height=size
                )
            )
        )
    else:
        img = Image.open(path)
        img.load()  # full decoding, not just the PNG signature
    dimensions = img.size
    img = img.convert("RGBA")
    bbox = img.getbbox()
    alpha = img.getextrema()[3][0] < 255
    img.thumbnail((size, size), Image.Resampling.LANCZOS)
    target.parent.mkdir(parents=True, exist_ok=True)
    img.save(target, "PNG")
    return dict(
        width=dimensions[0],
        height=dimensions[1],
        bbox=bbox,
        transparency=alpha,
        dimensions_kind="rendered_preview" if fmt == "SVG" else "original",
    )
