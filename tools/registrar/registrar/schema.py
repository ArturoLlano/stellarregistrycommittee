from __future__ import annotations

from typing import Any

from .util import random_suffix
from .vizier import compute_constellation_best_effort

def _prune_none(x):
    """
    Remove None / empty strings recursively.
    Keeps 0 / False.
    Removes empty dicts/lists after pruning.
    """
    if x is None:
        return None

    if isinstance(x, str):
        s = x.strip()
        return s if s else None

    if isinstance(x, list):
        out = []
        for v in x:
            pv = _prune_none(v)
            if pv is None:
                continue
            if pv == {} or pv == []:
                continue
            out.append(pv)
        return out if out else None

    if isinstance(x, dict):
        out = {}
        for k, v in x.items():
            pv = _prune_none(v)
            if pv is None:
                continue
            if pv == {} or pv == []:
                continue
            out[k] = pv
        return out if out else None

    return x


def _drop_block_if_only_source(obj: dict, key: str, source_key: str = "source") -> None:
    """
    If the block exists but contains only {"source": "..."} (or becomes empty), remove it.
    Also prunes None inside the block.
    """
    if key not in obj:
        return
    cleaned = _prune_none(obj.get(key))
    if cleaned is None:
        obj.pop(key, None)
        return
    if isinstance(cleaned, dict) and set(cleaned.keys()) == {source_key}:
        obj.pop(key, None)
        return
    obj[key] = cleaned
    
def _normalize_motto(motto: str | None) -> str | None:
    if motto is None:
        return None
    m = motto.strip()
    return m if m else None


def _normalize_text(v: str | None) -> str | None:
    if v is None:
        return None
    t = v.strip()
    return t if t else None


def _append_catalog_id(catalog: list[dict[str, str]], scheme: str, value: str | None) -> None:
    v = (value or "").strip()
    if not v:
        return
    for c in catalog:
        if str(c.get("scheme", "")).upper() == scheme.upper() and str(c.get("id", "")).strip() == v:
            return
    catalog.append({"scheme": scheme, "id": v})
def _fmt_ra_for_legend(ra_hms: str) -> str | None:
    if not ra_hms:
        return None
    parts = ra_hms.strip().split()
    if len(parts) != 3:
        return None
    h, m, s = parts
    try:
        # seconds with 2 decimals
        s2 = f"{float(s):.2f}"
    except Exception:
        s2 = s
    return f"{h.zfill(2)}h {m.zfill(2)}m {s2}s"


def _fmt_dec_for_legend(dec_dms: str) -> str | None:
    if not dec_dms:
        return None
    parts = dec_dms.strip().split()
    if len(parts) != 3:
        return None

    d, m, s = parts

    # keep sign in degrees
    sign = ""
    if d.startswith("+"):
        sign = "+"
        d = d[1:]
    elif d.startswith("-"):
        sign = "-"
        d = d[1:]

    try:
        s2 = f"{float(s):.2f}"
    except Exception:
        s2 = s

    # requested symbols: º ' ''
    return f"{sign}{d}º {m.zfill(2)}' {s2}''"


def _build_legend_en(*, sao: int, obj: dict) -> str | None:
    coords = obj.get("coordinates") or {}
    phot = obj.get("photometry") or {}
    spec = obj.get("spectral") or {}

    vmag = phot.get("v_mag")
    sptype = spec.get("type")

    ra = _fmt_ra_for_legend(coords.get("ra_hms", ""))
    dec = _fmt_dec_for_legend(coords.get("dec_dms", ""))

    if not ra or not dec:
        return None  # without coords, legend isn't useful

    chunks = [f"This is to register the star designated: SAO {sao}"]

    if vmag is not None:
        chunks.append(f"with visual magnitude: {vmag}")
    if sptype:
        chunks.append(f"spectral type: {sptype}")

    chunks.append(f"and located at the coordinates: RA: {ra}, and Dec {dec}, to be recorded in this registry as:")

    # Join with commas exactly in the style you wrote
    return ", ".join(chunks[:-1]) + ", " + chunks[-1]

def build_entry_payload(
    *,
    sao: int,
    inscription_name: str,
    inscription_motto: str | None,
    recorded_by: str | None,
    sponsor: str | None,
    recorded_at_utc: str,
    coordinates: dict[str, str] | None,
    sao_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    suffix = random_suffix(6, 10)
    entry_id = f"SAO-{sao}-{suffix}"

    payload: dict[str, Any] = {
        "id": entry_id,
        "status": "active",
        "recorded_at_utc": recorded_at_utc,
        "designation": {
            "title": f"Registry Entry — SAO {sao}",
            "type": "commemorative",
        },
        "object": {
            "catalog": [{"scheme": "SAO", "id": str(sao)}],
            "inscription": {
                "name": inscription_name.strip(),
                **({"motto": _normalize_motto(inscription_motto)} if _normalize_motto(inscription_motto) else {}),
            },
        },
        "legal": {"disclaimer_ref": "/legal/disclaimer/"},
    }

    obj = payload["object"]
    catalog = obj["catalog"]

    # Coordinates: prefer sao_meta (includes degrees)
    coords = None
    if sao_meta and isinstance(sao_meta.get("coordinates"), dict):
        coords = sao_meta["coordinates"]
    elif coordinates:
        coords = {"epoch": "J2000", "ra_hms": coordinates.get("ra_hms", ""), "dec_dms": coordinates.get("dec_dms", "")}

    if coords:
        obj["coordinates"] = {
            "epoch": "J2000",
            "ra_hms": coords.get("ra_hms", "") or "",
            "dec_dms": coords.get("dec_dms", "") or "",
            **({"ra_deg": coords.get("ra_deg")} if coords.get("ra_deg") is not None else {}),
            **({"dec_deg": coords.get("dec_deg")} if coords.get("dec_deg") is not None else {}),
        }
        payload["notes"] = [
            "Coordinates and metadata retrieved from CDS VizieR: SAO Star Catalog J2000 (I/131A)."
        ]
    else:
        obj["coordinates"] = {"epoch": "J2000", "ra_hms": "", "dec_dms": ""}
        payload["notes"] = ["Coordinates not retrieved at registration time."]

    # Enrichment blocks
    if sao_meta:
        ids = sao_meta.get("catalog_ids") if isinstance(sao_meta.get("catalog_ids"), dict) else {}
        _append_catalog_id(catalog, "DM", ids.get("DM"))
        _append_catalog_id(catalog, "HD", ids.get("HD"))
        _append_catalog_id(catalog, "GC", ids.get("GC"))

        if "photometry" in sao_meta:
            obj["photometry"] = sao_meta["photometry"]
        if "spectral" in sao_meta:
            obj["spectral"] = sao_meta["spectral"]
        if "multiplicity_variability" in sao_meta:
            obj["multiplicity_variability"] = sao_meta["multiplicity_variability"]
        if "astrometry" in sao_meta:
            obj["astrometry"] = sao_meta["astrometry"]

        ra_deg = sao_meta.get("coordinates", {}).get("ra_deg")
        dec_deg = sao_meta.get("coordinates", {}).get("dec_deg")
        if ra_deg is not None and dec_deg is not None:
            c, cerr = compute_constellation_best_effort(float(ra_deg), float(dec_deg))
            if c:
                obj["constellation"] = {**c, "method": "IAU Delporte boundaries (via astropy)"}
            else:
                obj["constellation"] = {"iau_abbr": None, "name": None, "method": "unresolved", "note": cerr}

    # Provenance
    prov: dict[str, Any] = {}
    rb = _normalize_text(recorded_by)
    sp = _normalize_text(sponsor)
    if rb:
        prov["recorded_by"] = rb
    if sp:
        prov["sponsor"] = sp
    if sao_meta:
        prov.setdefault("sources", [])
        prov["sources"].append({"service": "CDS VizieR", "catalog": "I/131A", "table": "sao"})
    if prov:
        payload["provenance"] = prov

    obj = payload["object"]

    # Prune nulls inside enrichment blocks and drop blocks that are effectively empty
    _drop_block_if_only_source(obj, "photometry")
    _drop_block_if_only_source(obj, "spectral")
    _drop_block_if_only_source(obj, "multiplicity_variability")
    _drop_block_if_only_source(obj, "astrometry")

    # Constellation: si no trae iau_abbr/name, quítalo completo
    if "constellation" in obj:
        c = _prune_none(obj["constellation"])
        if not c or (c.get("iau_abbr") is None and c.get("name") is None):
            obj.pop("constellation", None)
        else:
            obj["constellation"] = c

    payload["certificate"] = {
        "template_id": "tsrc-letter-v1",
        "lang": "en",
    }

    legend = _build_legend_en(sao=sao, obj=obj)
    if legend:
        payload["certificate"]["legend_en"] = legend
        
    return payload