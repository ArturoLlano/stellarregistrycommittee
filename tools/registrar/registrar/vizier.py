from __future__ import annotations

from typing import Any, Tuple
import re
import requests


from typing import Tuple
import os
import requests

# ---------- Normalization helpers ----------

def _norm_key(s: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", (s or "").strip().upper())


def _find_col(header: list[str], candidates: list[str]) -> int | None:
    norm = [_norm_key(h) for h in header]
    for c in candidates:
        kc = _norm_key(c)
        if kc in norm:
            return norm.index(kc)
    return None


def _is_float(s: str) -> bool:
    return bool(re.fullmatch(r"[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", (s or "").strip()))


def _clean_str(v: str | None) -> str | None:
    s = (v or "").strip().strip('"')
    if not s:
        return None
    if set(s) <= {"-"}:
        return None
    return s


def _clean_int(v: str | None) -> int | None:
    s = _clean_str(v)
    if s is None:
        return None
    if not re.fullmatch(r"[+-]?\d+", s):
        return None
    return int(s)


def _clean_float(v: str | None, *, drop_999: bool = True) -> float | None:
    s = _clean_str(v)
    if s is None or not _is_float(s):
        return None
    x = float(s)
    if drop_999 and x >= 99.8:
        return None
    return x


# ---------- Formatting / conversion helpers ----------

def _format_sec(x: float) -> str:
    if abs(x - round(x)) < 1e-12:
        return str(int(round(x)))
    return f"{x:.3f}".rstrip("0").rstrip(".")


def _deg_to_hms(ra_deg: float) -> str:
    total_hours = (ra_deg % 360.0) / 15.0
    h = int(total_hours)
    m_float = (total_hours - h) * 60.0
    m = int(m_float)
    s = (m_float - m) * 60.0
    return f"{h} {m} {_format_sec(s)}"


def _deg_to_dms(dec_deg: float) -> str:
    sign = "+" if dec_deg >= 0 else "-"
    x = abs(dec_deg)
    d = int(x)
    m_float = (x - d) * 60.0
    m = int(m_float)
    s = (m_float - m) * 60.0
    return f"{sign}{d} {m} {_format_sec(s)}"


def _to_repo_hms(v: str) -> str:
    s = (v or "").strip().replace(":", " ")
    return " ".join(s.split())


def _to_repo_dms(v: str) -> str:
    s = (v or "").strip().replace(":", " ")
    return " ".join(s.split())


def _hms_to_deg(hms: str) -> float:
    s = _to_repo_hms(hms)
    parts = s.split()
    if len(parts) != 3:
        raise ValueError(f"Bad HMS: {hms!r}")
    h, m, sec = float(parts[0]), float(parts[1]), float(parts[2])
    return (h + (m / 60.0) + (sec / 3600.0)) * 15.0


def _dms_to_deg(dms: str) -> float:
    s = _to_repo_dms(dms)
    sign = 1.0
    if s.startswith("+"):
        s = s[1:].strip()
    elif s.startswith("-"):
        sign = -1.0
        s = s[1:].strip()
    parts = s.split()
    if len(parts) != 3:
        raise ValueError(f"Bad DMS: {dms!r}")
    d, m, sec = float(parts[0]), float(parts[1]), float(parts[2])
    return sign * (d + (m / 60.0) + (sec / 3600.0))


# ---------- SAO code dictionaries (I/131A notes) ----------

REM_MEANING: dict[int, str] = {
    0: "No additional information",
    1: "Double star (see source catalog)",
    2: "Double star in Aitken's Double Star Catalogue",
    3: "Double star in Burnham's Double Star Catalogue",
    4: "Variable star in visual magnitude (source catalog)",
    5: "Variable star in photographic magnitude (source catalog)",
    6: "Variable star in both magnitudes",
    7: "Both double and variable (source catalog)",
}

HD_MULT_MEANING: dict[int, str] = {
    0: "Single star or primary with companion > 0.3 mag (visual) fainter",
    1: "Brighter component with companion ≤ 0.3 mag fainter",
    2: "Fainter component with companion ≤ 0.3 mag brighter",
    9: "Entry refers to two consecutive HD numbers; lower HD number is given",
}


# ---------- Main lookup ----------

def fetch_sao_metadata_best_effort(sao: int) -> Tuple[dict[str, Any] | None, str | None]:
    base = "https://vizier.cds.unistra.fr/viz-bin/asu-tsv"
    params = {
        "-source": "I/131A",
        "SAO": str(sao),
        "-out.all": "",
        "-out.max": "1",
    }

    try:
        r = requests.get(base, params=params, timeout=12)
        r.raise_for_status()
        text = r.text
    except Exception as e:
        return None, f"SAO lookup failed (network): {e}"

    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if len(lines) < 2:
        return None, "SAO lookup returned no rows."

    header = lines[0].split("\t")

    idx_ra = _find_col(header, ["RA2000", "RAJ2000", "_RA.ICRS", "RA_ICRS", "RA.ICRS", "RA"])
    idx_de = _find_col(header, ["DE2000", "DEJ2000", "_DE.ICRS", "DE_ICRS", "DE.ICRS", "DEC", "DE"])
    if idx_ra is None or idx_de is None:
        return None, f"SAO lookup parse failed (missing RA/Dec). Header was: {header}"

    idx_vmag = _find_col(header, ["Vmag"])
    idx_pmag = _find_col(header, ["Pmag"])
    idx_sptype = _find_col(header, ["SpType"])
    idx_rem = _find_col(header, ["Rem"])
    idx_dm = _find_col(header, ["DM"])
    idx_hd = _find_col(header, ["HD"])
    idx_gc = _find_col(header, ["GC"])
    idx_m_hd = _find_col(header, ["m_HD", "mHD"])
    idx_pmra2000 = _find_col(header, ["pmRA2000"])
    idx_pmde2000 = _find_col(header, ["pmDE2000"])
    idx_e_pos = _find_col(header, ["e_Pos", "ePos"])

    row: list[str] | None = None
    for ln in lines[1:]:
        parts = ln.split("\t")
        if idx_ra >= len(parts) or idx_de >= len(parts):
            continue
        ra_raw = _clean_str(parts[idx_ra])
        de_raw = _clean_str(parts[idx_de])
        if not ra_raw or not de_raw:
            continue
        if _norm_key(ra_raw) == "HMS" and _norm_key(de_raw) == "DMS":
            continue
        row = parts
        break

    if row is None:
        return None, "SAO lookup returned no usable data rows."

    def get(idx: int | None) -> str | None:
        if idx is None or idx >= len(row):
            return None
        return _clean_str(row[idx])

    ra_raw = get(idx_ra)
    de_raw = get(idx_de)
    if not ra_raw or not de_raw:
        return None, "SAO lookup returned empty coordinates."

    try:
        if _is_float(ra_raw) and _is_float(de_raw):
            ra_deg = float(ra_raw)
            dec_deg = float(de_raw)
            ra_hms = _deg_to_hms(ra_deg)
            dec_dms = _deg_to_dms(dec_deg)
        else:
            ra_hms = _to_repo_hms(ra_raw)
            dec_dms = _to_repo_dms(de_raw)
            ra_deg = _hms_to_deg(ra_hms)
            dec_deg = _dms_to_deg(dec_dms)
    except Exception as e:
        return None, f"Coordinate conversion failed: {e}"

    # --- normalize floating precision (prevents long repeating decimals in JSON) ---
    ra_deg = round(ra_deg, 8)
    dec_deg = round(dec_deg, 8)

    vmag = _clean_float(get(idx_vmag))
    pmag = _clean_float(get(idx_pmag))
    sptype = get(idx_sptype)

    rem_code = _clean_int(get(idx_rem))
    m_hd_code = _clean_int(get(idx_m_hd))

    pm_ra2000 = _clean_float(get(idx_pmra2000), drop_999=False)
    pm_de2000 = _clean_float(get(idx_pmde2000), drop_999=False)
    if pm_ra2000 is not None:
        pm_ra2000 = round(pm_ra2000, 6)

    if pm_de2000 is not None:
        pm_de2000 = round(pm_de2000, 6)

    e_pos_10mas = _clean_int(get(idx_e_pos))

    out: dict[str, Any] = {
        "sao": sao,
        "coordinates": {
            "epoch": "J2000",
            "ra_hms": ra_hms,
            "dec_dms": dec_dms,
            "ra_deg": ra_deg,
            "dec_deg": dec_deg,
        },
        "catalog_ids": {
            "DM": get(idx_dm),
            "HD": get(idx_hd),
            "GC": get(idx_gc),
        },
        "photometry": {
            "v_mag": vmag,
            "p_mag": pmag,
            "source": "I/131A",
        },
        "spectral": {
            "type": sptype,
            "is_composite": (sptype == "+++") if sptype else False,
            "source": "I/131A",
        },
        "multiplicity_variability": {
            "rem_code": rem_code,
            "rem_meaning": REM_MEANING.get(rem_code) if rem_code is not None else None,
            "hd_component_code": m_hd_code,
            "hd_component_meaning": HD_MULT_MEANING.get(m_hd_code) if m_hd_code is not None else None,
            "source": "I/131A",
        },
        "astrometry": {
            "proper_motion": {
                "pm_ra2000_s_per_yr": pm_ra2000,
                "pm_dec2000_arcsec_per_yr": pm_de2000,
            },
            "errors": {
                "pos_1950_10mas": e_pos_10mas,
            },
            "source": "I/131A",
        },
    }

    return out, None



def fetch_sao_coordinates_best_effort(sao: int) -> Tuple[dict[str, str] | None, str | None]:
    """
    Best-effort SAO -> coordinates lookup via VizieR.
    Tries multiple official mirrors to avoid local/network blocks.
    Returns: (coords_dict_or_none, warning_or_error_or_none)
    """

    # Allow override via env var if you ever want to pin a specific mirror
    # Example: set TSRC_VIZIER_ASU_TSV_BASE=https://vizier.cfa.harvard.edu/viz-bin/asu-tsv
    override = (os.environ.get("TSRC_VIZIER_ASU_TSV_BASE") or "").strip()

    bases = [override] if override else [
        "https://vizier.cds.unistra.fr/viz-bin/asu-tsv",   # CDS primary :contentReference[oaicite:2]{index=2}
        "https://vizier.u-strasbg.fr/viz-bin/asu-tsv",     # legacy Strasbourg host :contentReference[oaicite:3]{index=3}
        "https://vizier.cfa.harvard.edu/viz-bin/asu-tsv",  # Harvard mirror :contentReference[oaicite:4]{index=4}
        "https://vizier.iucaa.in/viz-bin/asu-tsv",         # IUCAA mirror :contentReference[oaicite:5]{index=5}
    ]

    params = {
        "-source": "I/131A",   # SAO Catalog
        "SAO": str(sao),
        "-out.all": "",
        "-out.max": "1",
    }

    headers = {
        "User-Agent": "TSRC-Registrar/1.0 (VizieR lookup)",
        "Accept": "text/tab-separated-values,text/plain,*/*",
    }

    last_err = None

    for base in bases:
        try:
            r = requests.get(base, params=params, headers=headers, timeout=(6, 18))
            r.raise_for_status()
            text = r.text
        except Exception as e:
            last_err = f"{base} -> {e}"
            continue

        # Keep only non-comment, non-empty lines
        lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
        if len(lines) < 2:
            last_err = f"{base} -> no rows"
            continue

        header = lines[0].split("\t")
        row = lines[1].split("\t")
        data = {header[i]: row[i] if i < len(row) else "" for i in range(len(header))}

        # Normalize likely column names
        ra = (data.get("RAJ2000") or data.get("RA_ICRS") or data.get("RA") or "").strip()
        dec = (data.get("DEJ2000") or data.get("DE_ICRS") or data.get("DE") or "").strip()

        # If RA/Dec not present, still return full row for debug
        if not ra or not dec:
            return data, f"VizieR returned a row but RA/Dec columns were missing (server={base})."

        # Return only what you need (or keep full `data` if you prefer)
        return {
            "server": base,
            "RAJ2000": ra,
            "DEJ2000": dec,
        }, None

    return None, f"SAO lookup failed on all mirrors. Last error: {last_err}"


def compute_constellation_best_effort(ra_deg: float, dec_deg: float) -> Tuple[dict[str, str] | None, str | None]:
    try:
        import astropy.units as u
        from astropy.coordinates import SkyCoord
    except Exception:
        return None, "astropy not installed"

    c = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg, frame="icrs")
    return {"iau_abbr": c.get_constellation(short_name=True), "name": c.get_constellation(short_name=False)}, None