from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

from tools.tsrc.config import DEFAULT_TEMPLATE_ID, expected_qr_url
from tools.tsrc.entries.model import Entry

_ID_RE = re.compile(r"^SAO-\d+-[A-Za-z0-9]+$")


class EntryValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ValidationWarning:
    code: str
    message: str


def validate_entry_or_raise(entry: Entry, *, strict_qr: bool = True) -> None:
    """
    Validates a parsed Entry model.
    """
    validate_entry_dict_or_raise(entry.to_dict(), strict_qr=strict_qr)


def validate_entry_dict_or_raise(data: Dict[str, Any], *, strict_qr: bool = True) -> None:
    """
    Validates raw JSON dict (before converting into Entry).
    Keeps dependencies light: no external schema engine is required.

    The included JSON Schema file is still provided for documentation/tooling,
    but runtime validation is done here for determinism and simplicity.
    """
    def req(key: str) -> Any:
        if key not in data:
            raise EntryValidationError(f"Missing required field: {key}")
        return data[key]

    schema_version = str(data.get("schema_version", ""))
    if schema_version and schema_version != "tsrc.entry.v1":
        raise EntryValidationError(f"Unsupported schema_version: {schema_version!r} (expected 'tsrc.entry.v1')")

    entry_id = str(req("id")).strip()
    if not _ID_RE.match(entry_id):
        raise EntryValidationError(
            "Invalid id format. Expected: SAO-<number>-<random> "
            f"(got {entry_id!r})"
        )

    sao = req("sao")
    if not isinstance(sao, int):
        # tolerate numeric strings, but require integer after conversion
        try:
            sao = int(sao)
        except Exception as e:
            raise EntryValidationError(f"'sao' must be an integer (got {type(req('sao')).__name__}): {e}")
    if sao <= 0:
        raise EntryValidationError("'sao' must be > 0")

    coords = req("coordinates")
    if not isinstance(coords, dict):
        raise EntryValidationError("'coordinates' must be an object")
    ra = str(coords.get("ra", "")).strip()
    dec = str(coords.get("dec", "")).strip()
    if not ra:
        raise EntryValidationError("coordinates.ra must be a non-empty string")
    if not dec:
        raise EntryValidationError("coordinates.dec must be a non-empty string")

    ins = req("inscription")
    if not isinstance(ins, dict):
        raise EntryValidationError("'inscription' must be an object")
    name = str(ins.get("name", "")).strip()
    motto = str(ins.get("motto", "")).strip()
    if not name:
        raise EntryValidationError("inscription.name must be a non-empty string")
    if not motto:
        raise EntryValidationError("inscription.motto must be a non-empty string")

    recorded_by = str(req("recorded_by")).strip()
    sponsor = str(req("sponsor")).strip()
    if not recorded_by:
        raise EntryValidationError("recorded_by must be a non-empty string")
    if not sponsor:
        raise EntryValidationError("sponsor must be a non-empty string")

    recorded_at = str(req("recorded_at")).strip()
    if not recorded_at:
        raise EntryValidationError("recorded_at must be a non-empty ISO 8601 string")
    _validate_iso8601_or_raise(recorded_at, field="recorded_at")

    cert = req("certificate")
    if not isinstance(cert, dict):
        raise EntryValidationError("'certificate' must be an object")

    template_id = str(cert.get("template_id", "")).strip()
    if not template_id:
        raise EntryValidationError("certificate.template_id must be a non-empty string")
    # Reasonable default allowed in JSON generation; still must be present:
    if template_id == "default":
        template_id = DEFAULT_TEMPLATE_ID

    qr_url = str(cert.get("qr_url", "")).strip()
    if not qr_url:
        raise EntryValidationError("certificate.qr_url must be present and non-empty")

    # Phase 1 strict requirement: must match expected URL
    exp = expected_qr_url(entry_id)
    if strict_qr and qr_url != exp:
        raise EntryValidationError(
            "certificate.qr_url does not match Phase 1 requirement.\n"
            f"Expected: {exp}\n"
            f"Got:      {qr_url}"
        )


def _validate_iso8601_or_raise(value: str, *, field: str) -> None:
    # Accept "Z" suffix by converting to +00:00 for fromisoformat
    v = value.replace("Z", "+00:00")
    try:
        datetime.fromisoformat(v)
    except Exception as e:
        raise EntryValidationError(f"{field} must be ISO 8601 (got {value!r}): {e}")
