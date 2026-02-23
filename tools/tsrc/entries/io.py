from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Tuple

from tools.tsrc.config import get_paths, DEFAULT_TEMPLATE_ID, expected_qr_url
from tools.tsrc.entries.model import Entry, Coordinates, Inscription, CertificateSpec
from tools.tsrc.entries.validate import validate_entry_dict_or_raise


def entry_json_path_from_public(entry_id: str) -> Path:
    """
    Absolute path to:
      /public/data/entries/<ID>.json
    """
    paths = get_paths()
    return (paths.entries_dir / f"{entry_id}.json").resolve()


def read_entry_from_public(entry_id: str) -> Entry:
    """
    Read one entry JSON from:
      /public/data/entries/<ID>.json

    IMPORTANT:
    - Supports both:
      A) Canonical v1 shape (top-level fields)
      B) Your current registrar shape (object/provenance/etc.)
    - We normalize to canonical v1 before validation + model parsing.
    """
    path = entry_json_path_from_public(entry_id)
    if not path.exists():
        raise FileNotFoundError(f"Entry JSON not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    canon = normalize_to_entry_v1(raw)
    validate_entry_dict_or_raise(canon, strict_qr=True)
    return _entry_from_dict(canon)


def write_entry_to_public(entry: Entry) -> Path:
    """
    Write canonical v1 entry JSON to:
      /public/data/entries/<ID>.json
    """
    path = entry_json_path_from_public(entry.id)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as f:
        json.dump(entry.to_dict(), f, ensure_ascii=False, indent=2)
        f.write("\n")

    return path


# -----------------------------
# Normalization (registrar -> v1)
# -----------------------------

_ID_RE = re.compile(r"^SAO-(\d+)-[A-Za-z0-9]+$")


def normalize_to_entry_v1(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert your registrar JSON into canonical 'tsrc.entry.v1' dict.

    This keeps certificate generation fully offline and JSON-only.

    If raw is already canonical (has 'coordinates' with 'ra'/'dec' and 'certificate'), it is passed through,
    but we still ensure required defaults exist.
    """
    # If already canonical-ish, enrich missing certificate fields deterministically.
    if isinstance(raw.get("coordinates"), dict) and ("ra" in raw["coordinates"]) and ("dec" in raw["coordinates"]):
        out = dict(raw)
        out.setdefault("schema_version", "tsrc.entry.v1")

        # Ensure sao exists (infer from id if needed)
        out.setdefault("sao", _infer_sao(out))

        # Ensure inscription exists (or attempt salvage)
        out.setdefault("inscription", _salvage_inscription(out))

        # Ensure recorded fields exist (or salvage)
        out.setdefault("recorded_by", _salvage_recorded_by(out))
        out.setdefault("sponsor", _salvage_sponsor(out))
        out.setdefault("recorded_at", _salvage_recorded_at(out))

        # Ensure certificate exists with stable QR + template id
        out["certificate"] = _ensure_certificate(out)
        return out

    # Otherwise, assume registrar shape like you pasted.
    entry_id = str(raw.get("id", "")).strip()
    if not entry_id:
        raise ValueError("Entry JSON missing 'id'")

    sao = _infer_sao(raw)
    ins_name, ins_motto = _infer_inscription_from_registrar(raw)
    ra, dec = _infer_coordinates_from_registrar(raw)

    recorded_by = _infer_provenance(raw, "recorded_by")
    sponsor = _infer_provenance(raw, "sponsor")
    recorded_at = str(raw.get("recorded_at_utc", "")).strip() or str(raw.get("recorded_at", "")).strip()

    canon: Dict[str, Any] = {
        "schema_version": "tsrc.entry.v1",
        "id": entry_id,
        "sao": sao,
        "coordinates": {"ra": ra, "dec": dec},
        "inscription": {"name": ins_name, "motto": ins_motto},
        "recorded_by": recorded_by,
        "sponsor": sponsor,
        "recorded_at": recorded_at,
        "certificate": {
            "template_id": DEFAULT_TEMPLATE_ID,
            "qr_url": expected_qr_url(entry_id),
        },
    }

    # Preserve your extra metadata for Phase 2 / provenance, without breaking v1:
    # (These keys are allowed because schema allows additionalProperties.)
    for k in ("status", "designation", "object", "legal", "notes", "provenance", "recorded_at_utc"):
        if k in raw and k not in canon:
            canon[k] = raw[k]

    return canon


def _infer_sao(d: Dict[str, Any]) -> int:
    # 1) canonical
    if "sao" in d:
        try:
            return int(d["sao"])
        except Exception:
            pass

    # 2) registrar: object.catalog[*] where scheme == "SAO"
    obj = d.get("object")
    if isinstance(obj, dict):
        catalog = obj.get("catalog")
        if isinstance(catalog, list):
            for item in catalog:
                if isinstance(item, dict) and str(item.get("scheme", "")).upper() == "SAO":
                    try:
                        return int(str(item.get("id", "")).strip())
                    except Exception:
                        pass

    # 3) infer from id "SAO-<num>-..."
    entry_id = str(d.get("id", "")).strip()
    m = _ID_RE.match(entry_id)
    if m:
        return int(m.group(1))

    raise ValueError("Could not infer SAO number. Provide either top-level 'sao', object.catalog SAO entry, or ID 'SAO-<num>-...'.")


def _infer_inscription_from_registrar(raw: Dict[str, Any]) -> Tuple[str, str]:
    obj = raw.get("object")
    if isinstance(obj, dict):
        ins = obj.get("inscription")
        if isinstance(ins, dict):
            name = str(ins.get("name", "")).strip()
            motto = str(ins.get("motto", "")).strip()
            return name, motto
    return "", ""


def _infer_coordinates_from_registrar(raw: Dict[str, Any]) -> Tuple[str, str]:
    obj = raw.get("object")
    if not isinstance(obj, dict):
        return "", ""

    coords = obj.get("coordinates")
    if not isinstance(coords, dict):
        return "", ""

    ra_hms = str(coords.get("ra_hms", "")).strip()
    dec_dms = str(coords.get("dec_dms", "")).strip()

    ra = _format_ra_hms(ra_hms) if ra_hms else ""
    dec = _format_dec_dms(dec_dms) if dec_dms else ""
    return ra, dec


def _format_ra_hms(s: str) -> str:
    # Input example: "21 41 01.678"
    parts = [p for p in s.split() if p]
    if len(parts) == 3:
        h, m, sec = parts
        return f"{h}h {m}m {sec}s"
    # fallback: keep as-is
    return s


def _format_dec_dms(s: str) -> str:
    # Input example: "+57 08 17.29"
    parts = [p for p in s.split() if p]
    if len(parts) == 3:
        d, m, sec = parts
        return f"{d}° {m}′ {sec}″"
    return s


def _infer_provenance(raw: Dict[str, Any], key: str) -> str:
    prov = raw.get("provenance")
    if isinstance(prov, dict):
        v = str(prov.get(key, "")).strip()
        if v:
            return v
    return ""


def _salvage_inscription(d: Dict[str, Any]) -> Dict[str, Any]:
    # Try registrar path if missing
    if isinstance(d.get("inscription"), dict):
        return d["inscription"]
    obj = d.get("object")
    if isinstance(obj, dict) and isinstance(obj.get("inscription"), dict):
        ins = obj["inscription"]
        return {"name": str(ins.get("name", "")).strip(), "motto": str(ins.get("motto", "")).strip()}
    return {"name": "", "motto": ""}


def _salvage_recorded_by(d: Dict[str, Any]) -> str:
    if "recorded_by" in d:
        return str(d.get("recorded_by", "")).strip()
    prov = d.get("provenance")
    if isinstance(prov, dict):
        return str(prov.get("recorded_by", "")).strip()
    return ""


def _salvage_sponsor(d: Dict[str, Any]) -> str:
    if "sponsor" in d:
        return str(d.get("sponsor", "")).strip()
    prov = d.get("provenance")
    if isinstance(prov, dict):
        return str(prov.get("sponsor", "")).strip()
    return ""


def _salvage_recorded_at(d: Dict[str, Any]) -> str:
    if "recorded_at" in d:
        return str(d.get("recorded_at", "")).strip()
    if "recorded_at_utc" in d:
        return str(d.get("recorded_at_utc", "")).strip()
    return ""


def _ensure_certificate(d: Dict[str, Any]) -> Dict[str, Any]:
    entry_id = str(d.get("id", "")).strip()
    cert = d.get("certificate")
    if not isinstance(cert, dict):
        cert = {}

    template_id = str(cert.get("template_id", "")).strip() or DEFAULT_TEMPLATE_ID
    qr_url = str(cert.get("qr_url", "")).strip() or expected_qr_url(entry_id)

    return {"template_id": template_id, "qr_url": qr_url}


# -----------------------------
# Canonical dict -> Entry model
# -----------------------------

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