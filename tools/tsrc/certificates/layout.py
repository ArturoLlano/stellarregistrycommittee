from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from tools.tsrc.config import get_paths


class TemplateNotFoundError(FileNotFoundError):
    pass


@dataclass(frozen=True)
class TemplateBundle:
    template_id: str
    root_dir: Path
    manifest: Dict[str, Any]
    layout: Dict[str, Any]
    disclaimer_text: str

    @property
    def background_path(self) -> Path:
        rel = str(self.manifest.get("background", "background.jpg"))
        return (self.root_dir / rel).resolve()


def load_template_bundle(template_id: str) -> TemplateBundle:
    """
    Loads an immutable template bundle from:
      tools/tsrc/certificates/templates/<template_id>/
    """
    paths = get_paths()
    root = (paths.templates_dir / template_id).resolve()
    if not root.exists():
        raise TemplateNotFoundError(f"Template bundle not found: {root}")

    manifest_path = root / "manifest.json"
    layout_path = root / "layout.json"
    disclaimer_path = root / "disclaimer.txt"

    if not manifest_path.exists():
        raise TemplateNotFoundError(f"Missing manifest.json: {manifest_path}")
    if not layout_path.exists():
        raise TemplateNotFoundError(f"Missing layout.json: {layout_path}")
    if not disclaimer_path.exists():
        raise TemplateNotFoundError(f"Missing disclaimer.txt: {disclaimer_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    disclaimer_text = disclaimer_path.read_text(encoding="utf-8").strip()

    declared_id = str(manifest.get("template_id", "")).strip()
    if declared_id and declared_id != template_id:
        raise ValueError(
            "Template manifest.template_id mismatch.\n"
            f"Folder name: {template_id}\n"
            f"manifest.json: {declared_id}"
        )

    return TemplateBundle(
        template_id=template_id,
        root_dir=root,
        manifest=manifest,
        layout=layout,
        disclaimer_text=disclaimer_text,
    )


def get_by_path(obj: Dict[str, Any], dotted: str) -> str:
    """
    Resolve dotted paths like:
      "coordinates.ra" or "inscription.name"

    Returns "" if missing.
    """
    cur: Any = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return ""
        cur = cur[part]
    return "" if cur is None else str(cur)
