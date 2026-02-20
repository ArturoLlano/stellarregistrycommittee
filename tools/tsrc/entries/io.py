from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from tools.tsrc.config import get_paths
from tools.tsrc.entries.model import Entry, Coordinates, Inscription, CertificateSpec
from tools.tsrc.entries.validate import validate_entry_dict_or_raise


def entry_json_path_from_public(entry_id: str) -> Path:
    paths = get_paths()
    return (paths.entries_dir / f"{entry_id}.json").resolve()


def read_entry_from_public(entry_id: str) -> Entry:
    """
    Read and parse one entry JSON from:
      /public/data/entries/<ID>.json
    """
    path = entry_json_path_from_public(entry_id)
    if not path.exists():
        raise FileNotFoundError(f"Entry JSON not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    validate_entry_dict_or_raise(data)

    return _entry_from_dict(data)


def write_entry_to_public(entry: Entry) -> Path:
    """
    Writes back to /public/data/entries/<ID>.json (useful for tooling),
    but certificate generation itself does NOT require writing.
    """
    path = entry_json_path_from_public(entry.id)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as f:
        json.dump(entry.to_dict(), f, ensure_ascii=False, indent=2)
        f.write("\n")

    return path


def _entry_from_dict(data: Dict[str, Any]) -> Entry:
    known = {
        "schema_version",
        "id",
        "sao",
        "coordinates",
        "inscription",
        "recorded_by",
        "sponsor",
        "recorded_at",
        "certificate",
    }
    extra = {k: v for k, v in data.items() if k not in known}

    coords = data["coordinates"]
    ins = data["inscription"]
    cert = data["certificate"]

    return Entry(
        id=str(data["id"]),
        sao=int(data["sao"]),
        coordinates=Coordinates(ra=str(coords["ra"]), dec=str(coords["dec"])),
        inscription=Inscription(name=str(ins["name"]), motto=str(ins["motto"])),
        recorded_by=str(data["recorded_by"]),
        sponsor=str(data["sponsor"]),
        recorded_at=str(data["recorded_at"]),
        certificate=CertificateSpec(
            template_id=str(cert["template_id"]),
            qr_url=str(cert["qr_url"]),
        ),
        extra=extra,
    )