from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .repo import RepoContext
from .util import safe_int


@dataclass(frozen=True)
class DuplicateMatch:
    sao: int
    file_name: str
    entry_id: str | None
    reason: str  # "filename" or "content"


def list_entry_files(ctx: RepoContext) -> list[Path]:
    assert ctx.repo_root and ctx.entries_dir
    entries_dir = ctx.entries_dir
    if not entries_dir.exists():
        return []
    # Only top-level JSON files; ignore subfolders like maps/
    return sorted([p for p in entries_dir.glob("*.json") if p.is_file()])


def _matches_filename(file_path: Path, sao: int) -> bool:
    # SAO-12345-XXXX.json
    prefix = f"SAO-{sao}-"
    return file_path.name.startswith(prefix) and file_path.suffix.lower() == ".json"


def _extract_sao_from_json(obj: dict) -> int | None:
    """
    Expected structure (based on current repo example):
      object.catalog = [{scheme:"SAO", id:"12346"}, ...]
    """
    try:
        catalogs = obj.get("object", {}).get("catalog", [])
        for c in catalogs:
            if str(c.get("scheme", "")).upper() == "SAO":
                return safe_int(str(c.get("id", "")).strip())
    except Exception:
        return None
    return None


def _extract_entry_id(obj: dict) -> str | None:
    try:
        v = obj.get("id")
        return str(v).strip() if v else None
    except Exception:
        return None


def find_duplicates(ctx: RepoContext, sao: int) -> list[DuplicateMatch]:
    matches: list[DuplicateMatch] = []
    for fp in list_entry_files(ctx):
        # 1) filename check (fast)
        if _matches_filename(fp, sao):
            matches.append(
                DuplicateMatch(
                    sao=sao,
                    file_name=fp.name,
                    entry_id=fp.stem,
                    reason="filename",
                )
            )
            continue

        # 2) content check (robust)
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            # Ignore unreadable JSON rather than blocking everything
            continue

        sao_in_json = _extract_sao_from_json(data)
        if sao_in_json == sao:
            matches.append(
                DuplicateMatch(
                    sao=sao,
                    file_name=fp.name,
                    entry_id=_extract_entry_id(data) or fp.stem,
                    reason="content",
                )
            )

    # De-dup same file
    uniq = {(m.file_name, m.reason): m for m in matches}
    return list(uniq.values())
