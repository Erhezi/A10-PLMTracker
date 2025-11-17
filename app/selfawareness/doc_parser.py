from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any
from zipfile import ZipFile
import re
import xml.etree.ElementTree as ET

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
HEADING_PATTERN = re.compile(r"^\d+\.\d+(?:\.\d+)?\s+")


def _w(tag: str) -> str:
    return f"{{{W_NS}}}{tag}"


def _paragraph_text(p: ET.Element) -> str:
    texts: list[str] = []
    for node in p.findall(".//w:t", namespaces={"w": W_NS}):
        if node.text:
            texts.append(node.text)
    raw = "".join(texts)
    return raw.strip()


def _slugify(title: str, fallback: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug or f"section-{fallback}"


def _append_block(section: dict[str, Any], block: dict[str, Any]) -> None:
    if block["type"] == "list-item":
        items = block["text"]
        if not items:
            return
        if section["blocks"] and section["blocks"][-1]["type"] == "list":
            section["blocks"][-1]["list_items"].append(items)
        else:
            section["blocks"].append({"type": "list", "list_items": [items]})
        return
    section["blocks"].append(block)


def _gather_search_blob(section: dict[str, Any]) -> str:
    pieces = [section["title"]]
    for block in section["blocks"]:
        if block["type"] == "paragraph":
            pieces.append(block["text"])
        elif block["type"] == "list":
            pieces.extend(block["list_items"])
        elif block["type"] == "table":
            for row in block["rows"]:
                pieces.extend(row)
    return " ".join(filter(None, pieces)).lower()


def _iter_document_nodes(body: ET.Element):
    for child in body:
        if child.tag == _w("p"):
            yield ("paragraph", child)
        elif child.tag == _w("tbl"):
            yield ("table", child)


def _parse_table(tbl: ET.Element) -> list[list[str]]:
    rows: list[list[str]] = []
    for tr in tbl.findall(_w("tr")):
        cells: list[str] = []
        for tc in tr.findall(_w("tc")):
            cell_text_parts: list[str] = []
            for p in tc.findall(_w("p")):
                text = _paragraph_text(p)
                if text:
                    cell_text_parts.append(text)
            cell_text = " ".join(cell_text_parts).strip()
            if cell_text:
                cells.append(cell_text)
        if cells:
            rows.append(cells)
    return rows


def _section_from_doc(path: Path) -> list[dict[str, Any]]:
    with ZipFile(path) as zf:
        xml_bytes = zf.read("word/document.xml")
    root = ET.fromstring(xml_bytes)
    body = root.find(_w("body"))
    if body is None:
        return []

    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for node_type, node in _iter_document_nodes(body):
        if node_type == "paragraph":
            text = _paragraph_text(node)
            if not text:
                continue
            p_style = None
            p_props = node.find(_w("pPr"))
            if p_props is not None:
                style_node = p_props.find(_w("pStyle"))
                if style_node is not None:
                    p_style = style_node.get(_w("val"))
            is_heading = bool(p_style and "heading" in p_style.lower())
            if not is_heading and HEADING_PATTERN.match(text):
                is_heading = True
            is_list_item = (
                p_props is not None and p_props.find(_w("numPr")) is not None
            )

            if is_heading:
                current = {
                    "title": text,
                    "blocks": [],
                }
                sections.append(current)
                continue

            if current is None:
                current = {"title": "Overview", "blocks": []}
                sections.append(current)

            if is_list_item:
                _append_block(current, {"type": "list-item", "text": text})
            else:
                _append_block(current, {"type": "paragraph", "text": text})

        elif node_type == "table":
            table_rows = _parse_table(node)
            if not table_rows:
                continue
            if current is None:
                current = {"title": "Overview", "blocks": []}
                sections.append(current)
            current["blocks"].append({"type": "table", "rows": table_rows})

    for idx, section in enumerate(sections, start=1):
        section["id"] = _slugify(section["title"], idx)
        section["search_blob"] = _gather_search_blob(section)

    return sections


@lru_cache(maxsize=1)
def load_manual_sections(path: str, mtime: float) -> list[dict[str, Any]]:
    """Parse the onboarding manual docx into structured sections."""
    return _section_from_doc(Path(path))
