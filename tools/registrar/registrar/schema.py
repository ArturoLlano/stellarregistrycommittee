from __future__ import annotations

from typing import Any

from .util import random_suffix


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


def build_entry_payload(
    *,
    sao: int,
    inscription_name: str,
    inscription_motto: str | None,
    recorded_by: str | None,
    sponsor: str | None,
    recorded_at_utc: str,
    coordinates: dict[str, str] | None,
) -> dict[str, Any]:
    """
    Schema matched to the current repo example (SAO-12346-YFQKUGKG.json),
    with optional provenance fields added (non-breaking).
    """
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
            "catalog": [
                {"scheme": "SAO", "id": str(sao)},
            ],
            "inscription": {
                "name": inscription_name.strip(),
                # Keep motto key present only if provided (cleaner)
                **({"motto": _normalize_motto(inscription_motto)} if _normalize_motto(inscription_motto) else {}),
            },
        },
        "legal": {
            "disclaimer_ref": "/legal/disclaimer/",
        },
    }

    # Coordinates are in your current schema; fill if we have them, else keep blank placeholders.
    if coordinates:
        payload["object"]["coordinates"] = {
            "epoch": "J2000",
            "ra_hms": coordinates["ra_hms"],
            "dec_dms": coordinates["dec_dms"],
        }
        payload["notes"] = [
            "Coordinates retrieved from CDS VizieR: SAO Star Catalog J2000 (I/131A)."
        ]
    else:
        # If lookup fails/offline, keep coordinates present but blank (matches schema presence without inventing values).
        payload["object"]["coordinates"] = {
            "epoch": "J2000",
            "ra_hms": "",
            "dec_dms": "",
        }
        payload["notes"] = [
            "Coordinates not retrieved at registration time."
        ]

    # Optional provenance (new, but safe)
    prov = {}
    rb = _normalize_text(recorded_by)
    sp = _normalize_text(sponsor)
    if rb:
        prov["recorded_by"] = rb
    if sp:
        prov["sponsor"] = sp
    if prov:
        payload["provenance"] = prov

    return payload
