from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass(frozen=True)
class Coordinates:
    # Stored as strings to preserve canonical formatting, e.g.:
    # RA:  "18h 36m 56.3s"
    # Dec: "+38° 47′ 01″"
    ra: str
    dec: str


@dataclass(frozen=True)
class Inscription:
    name: str
    motto: str


@dataclass(frozen=True)
class CertificateSpec:
    template_id: str
    qr_url: str


@dataclass(frozen=True)
class Entry:
    """
    Canonical TSRC entry model for Phase 1.

    IMPORTANT:
    - Certificates must be fully regenerable from JSON only.
    - Therefore, all certificate-visible fields must be in this model.
    """
    id: str
    sao: int
    coordinates: Coordinates
    inscription: Inscription
    recorded_by: str
    sponsor: str
    recorded_at: str  # ISO 8601 string
    certificate: CertificateSpec

    # Keep forward-compatible fields here without breaking code:
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        base: Dict[str, Any] = {
            "schema_version": "tsrc.entry.v1",
            "id": self.id,
            "sao": self.sao,
            "coordinates": {"ra": self.coordinates.ra, "dec": self.coordinates.dec},
            "inscription": {"name": self.inscription.name, "motto": self.inscription.motto},
            "recorded_by": self.recorded_by,
            "sponsor": self.sponsor,
            "recorded_at": self.recorded_at,
            "certificate": {
                "template_id": self.certificate.template_id,
                "qr_url": self.certificate.qr_url,
            },
        }
        # extra fields should not overwrite canonical keys:
        for k, v in self.extra.items():
            if k not in base:
                base[k] = v
        return base
