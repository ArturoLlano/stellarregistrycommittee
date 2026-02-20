from __future__ import annotations

from typing import Tuple
import re
import requests


# ---------- Normalization helpers ----------

def _norm_key(s: str) -> str:
    # Uppercase + remove all non-alphanumeric (handles RA.icrs, RA_ICRS, RA(ICRS), etc.)
    return re.sub(r"[^A-Z0-9]+", "", (s or "").strip().upper())


def _find_col(header: list[str], candidates: list[str]) -> int | None:
    norm = [_norm_key(h) for h in header]
    for c in candidates:
        kc = _norm_key(c)
        if kc in norm:
            return norm.index(kc)
    return None


def _is_float(s: str) -> bool:
    return bool(re.fullmatch(r"[+-]?\d+(?:\.\d+)?", (s or "").strip()))


# ---------- Formatting / conversion helpers ----------

def _format_sec(x: float) -> str:
    # Keep integer seconds as int; else 1 decimal
    if abs(x - round(x)) < 1e-9:
        return str(int(round(x)))
    return f"{x:.1f}".rstrip("0").rstrip(".")


def _deg_to_hms(ra_deg: float) -> str:
    # RA degrees -> hours
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
    # Accept "h:m:s" or "h m s" and normalize spaces
    s = (v or "").strip().replace(":", " ")
    return " ".join(s.split())


def _to_repo_dms(v: str) -> str:
    s = (v or "").strip().replace(":", " ")
    return " ".join(s.split())


# ---------- Main lookup ----------

def fetch_sao_coordinates_best_effort(sao: int) -> Tuple[dict[str, str] | None, str | None]:
    """
    Best-effort RA/Dec lookup from CDS VizieR asu-tsv (I/131A).
    - Requests all columns (-out.all) and max 1 record.
    - Detects RA/Dec columns robustly (RA.icrs / DE.icrs, RAJ2000/DEJ2000, etc.)
    - Skips VizieR "units" row like: h m s / d m s
    - If RA/Dec are in decimal degrees, converts to RA h m s and Dec d m s.
    """
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
        return None, f"Coordinate lookup failed (network): {e}"

    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if len(lines) < 2:
        return None, "Coordinate lookup returned no rows."

    header = lines[0].split("\t")

    idx_ra = _find_col(header, ["RAJ2000", "RA_ICRS", "RA.ICRS", "RA(ICRS)", "RA"])
    idx_de = _find_col(header, ["DEJ2000", "DE_ICRS", "DE.ICRS", "DE(ICRS)", "DEC", "DE"])

    if idx_ra is None or idx_de is None:
        return None, f"Coordinate lookup parse failed. Header was: {header}"

    # Find the first usable data row (skip units row like "h m s" / "d m s")
    data_ra = None
    data_de = None

    for ln in lines[1:]:
        row = ln.split("\t")
        if idx_ra >= len(row) or idx_de >= len(row):
            continue

        ra_raw = (row[idx_ra] or "").strip().strip('"')
        de_raw = (row[idx_de] or "").strip().strip('"')

        if not ra_raw or not de_raw:
            continue

        # Skip separator rows
        if set(ra_raw) <= {"-"} or set(de_raw) <= {"-"}:
            continue

        # Skip units rows: "h m s" / "d m s"
        if _norm_key(ra_raw) == "HMS" and _norm_key(de_raw) == "DMS":
            continue

        data_ra, data_de = ra_raw, de_raw
        break

    if not data_ra or not data_de:
        return None, f"Coordinate lookup returned no usable data rows. Header was: {header}"

    ra_raw = data_ra
    de_raw = data_de

    try:
        if _is_float(ra_raw) and _is_float(de_raw):
            ra_hms = _deg_to_hms(float(ra_raw))
            dec_dms = _deg_to_dms(float(de_raw))
        else:
            ra_hms = _to_repo_hms(ra_raw)
            dec_dms = _to_repo_dms(de_raw)
    except Exception as e:
        return None, f"Coordinate conversion failed: {e}"

    if not ra_hms or not dec_dms:
        return None, "Coordinate lookup returned empty coordinates."

    return {"ra_hms": ra_hms, "dec_dms": dec_dms}, None
