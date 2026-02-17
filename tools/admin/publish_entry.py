#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
The Stellar Registry Committee — Phase 1 Admin Publisher (local)

Crea una nueva entrada JSON en:
  public/data/entries/<ID>.json

Entradas mínimas:
  --sao   (dígitos)
  --name  (inscription.name)
  --motto (inscription.motto)

Auto:
  - Lookup RA2000 / DE2000 desde CDS VizieR, SAO catalog I/131A (tabla I/131A/sao)
  - Formato:
      ra_hms: "H M S.s"
      dec_dms: "+D M S"
      epoch:  "J2000"
  - ID: SAO-<SAO>-<RANDOM_SUFFIX> (A–Z,0–9, 6–8 chars)
  - (Opcional) git add/commit/push

Seguridad:
  - Error si SAO no existe
  - No sobreescribe archivos existentes
  - --dry-run imprime JSON sin escribir
  - --no-git escribe sin commit/push
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import secrets
import string
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

import requests

try:
    from astropy.coordinates import SkyCoord
    import astropy.units as u
except Exception:
    SkyCoord = None
    u = None


VIZIER_ASU_TSV = "https://vizier.cds.unistra.fr/viz-bin/asu-tsv"
VIZIER_TABLE = "I/131A/sao"

ALPHABET = string.ascii_uppercase + string.digits

RA_HMS_RE = re.compile(r"^\d{1,2} \d{1,2} \d{1,2}(\.\d)?$")
DEC_DMS_RE = re.compile(r"^[+-]\d{1,2} \d{1,2} \d{1,2}$")


def eprint(*args: object) -> None:
    print(*args, file=sys.stderr)


def iso_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def find_repo_root(start: Path) -> Path:
    cur = start.resolve()
    for _ in range(30):
        if (cur / ".git").exists():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    raise RuntimeError("No se encontró .git. Ejecuta esto dentro del repo.")


def generate_suffix(n: int) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(n))


def generate_id(sao: int, suffix_len: int) -> str:
    return f"SAO-{sao}-{generate_suffix(suffix_len)}"


def parse_ra_to_hours(ra_raw: str) -> float:
    """Acepta 'HH MM SS.SS' o 'HH:MM:SS.SS' o número decimal (deg u horas)."""
    v = ra_raw.strip()
    if re.fullmatch(r"[+-]?\d+(\.\d+)?", v):
        x = float(v)
        # si es >24, probablemente grados
        return (x / 15.0) % 24.0 if x > 24.0 else x % 24.0

    parts = v.split(":") if ":" in v else v.split()
    if len(parts) != 3:
        raise ValueError(f"RA no reconocida: {ra_raw!r}")

    h = float(parts[0])
    m = float(parts[1])
    s = float(parts[2])
    if not (0 <= h < 24 and 0 <= m < 60 and 0 <= s < 60.0001):
        raise ValueError(f"RA fuera de rango: {ra_raw!r}")

    return (h + m / 60.0 + s / 3600.0) % 24.0


def parse_dec_to_deg(dec_raw: str) -> float:
    """Acepta '+DD MM SS.SS' o '+DD:MM:SS.SS' o grados decimales."""
    v = dec_raw.strip()
    if re.fullmatch(r"[+-]?\d+(\.\d+)?", v):
        x = float(v)
        if not (-90.0 <= x <= 90.0):
            raise ValueError(f"Dec fuera de rango: {dec_raw!r}")
        return x

    parts = v.split(":") if ":" in v else v.split()
    if len(parts) != 3:
        raise ValueError(f"Dec no reconocida: {dec_raw!r}")

    deg_part = parts[0]
    sign = -1.0 if deg_part.startswith("-") else 1.0
    d = abs(float(deg_part))
    m = float(parts[1])
    s = float(parts[2])

    if not (0 <= d <= 90 and 0 <= m < 60 and 0 <= s < 60.0001):
        raise ValueError(f"Dec fuera de rango: {dec_raw!r}")

    return sign * (d + m / 60.0 + s / 3600.0)


def hours_to_ra_hms(hours: float, sec_precision: int = 1) -> str:
    hours = hours % 24.0
    h = int(hours)
    m_float = (hours - h) * 60.0
    m = int(m_float)
    s = (m_float - m) * 60.0

    s = round(s, sec_precision)
    if s >= 60.0:
        s -= 60.0
        m += 1
    if m >= 60:
        m -= 60
        h += 1
    if h >= 24:
        h -= 24

    return f"{h} {m} {s:.{sec_precision}f}"


def deg_to_dec_dms(deg: float) -> str:
    if not (-90.0 <= deg <= 90.0):
        raise ValueError("Dec fuera de rango.")
    sign = "+" if deg >= 0 else "-"
    x = abs(deg)
    d = int(x)
    m_float = (x - d) * 60.0
    m = int(m_float)
    s = round((m_float - m) * 60.0, 0)

    if s >= 60:
        s = 0
        m += 1
    if m >= 60:
        m = 0
        d += 1
    if d > 90:
        raise ValueError("Dec inválida tras redondeo (>90).")

    return f"{sign}{d} {m} {int(s)}"


def validate_formats(ra_hms: str, dec_dms: str) -> None:
    if not RA_HMS_RE.match(ra_hms):
        raise ValueError(f"ra_hms inválida: {ra_hms!r}")
    if not DEC_DMS_RE.match(dec_dms):
        raise ValueError(f"dec_dms inválida: {dec_dms!r}")

def compute_constellation_iau(ra_hours: float, dec_deg: float) -> Optional[dict]:
    """
    Devuelve constelación IAU a partir de coordenadas (ICRS/J2000),
    usando los límites IAU (implementación Astropy).
    """
    if SkyCoord is None or u is None:
        return None

    c = SkyCoord(ra=ra_hours * u.hourangle, dec=dec_deg * u.deg, frame="icrs")
    iau_abbrev = c.get_constellation(short_name=True)   # ej: "UMi"
    full_name = c.get_constellation(short_name=False)   # ej: "Ursa Minor"
    return {"iau_abbrev": iau_abbrev, "name": full_name}

def vizier_lookup_sao(sao: int, timeout_s: int = 20, retries: int = 2) -> Tuple[str, str]:
    """
    Consulta VizieR ASU TSV en I/131A/sao por SAO exacto.
    Regresa (RA2000, DE2000) crudos.
    Robusto contra líneas de unidades/metadatos.
    """
    params = {
        "-source": VIZIER_TABLE,
        "-out": "SAO,RA2000,DE2000",
        "-out.max": "5",
        "-out.meta": "h",   # <-- SOLO header, sin unidades (evita la fila "h")
        "SAO": str(sao),
    }

    last: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(
                VIZIER_ASU_TSV,
                params=params,
                timeout=timeout_s,
                headers={"User-Agent": "StellarRegistryCommittee-AdminPublisher/1.0"},
            )
            r.raise_for_status()

            # En TSV, VizieR puede incluir líneas no-dato; ignoramos comentarios '#'
            lines = [ln for ln in r.text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
            if not lines:
                return ("", "")

            reader = csv.reader(lines, delimiter="\t")
            header = next(reader, None)
            if not header:
                return ("", "")

            idx = {name.strip(): i for i, name in enumerate(header)}
            for needed in ("RA2000", "DE2000", "SAO"):
                if needed not in idx:
                    raise RuntimeError(f"Respuesta inesperada de VizieR (falta {needed}). Header: {header}")

            # Busca la primera fila "real" y parseable
            for row in reader:
                try:
                    sao_cell = row[idx["SAO"]].strip()
                    ra_raw = row[idx["RA2000"]].strip()
                    dec_raw = row[idx["DE2000"]].strip()
                except Exception:
                    continue

                # Filas vacías / no-dato
                if not sao_cell or not ra_raw or not dec_raw:
                    continue

                # Debe coincidir con el SAO solicitado
                if not sao_cell.isdigit() or int(sao_cell) != sao:
                    continue

                # Si hay letras (p.ej. "h", "d"), es metadato/unidades, no dato
                if re.search(r"[A-Za-z]", ra_raw) or re.search(r"[A-Za-z]", dec_raw):
                    continue

                # Verifica que se puedan convertir (si no, sigue buscando)
                try:
                    _ = parse_ra_to_hours(ra_raw)
                    _ = parse_dec_to_deg(dec_raw)
                except Exception:
                    continue

                return (ra_raw, dec_raw)

            return ("", "")

        except Exception as ex:
            last = ex
            if attempt < retries:
                continue
            raise RuntimeError(f"Fallo consulta VizieR: {ex}") from ex

    raise RuntimeError(f"Fallo consulta VizieR: {last}")


def build_entry(
    entry_id: str,
    sao: int,
    name: str,
    motto: str,
    ra_hms: str,
    dec_dms: str,
    constellation: Optional[dict],
) -> dict:
    entry = {
        "id": entry_id,
        "status": "active",
        "recorded_at_utc": iso_utc_now(),
        "designation": {"title": f"Registry Entry — SAO {sao}", "type": "commemorative"},
        "object": {
            "catalog": [{"scheme": "SAO", "id": str(sao)}],
            "inscription": {"name": name, "motto": motto},
            "coordinates": {"epoch": "J2000", "ra_hms": ra_hms, "dec_dms": dec_dms},
        },
        "notes": ["Coordinates retrieved from CDS VizieR: SAO Star Catalog J2000 (I/131A)."],
        "legal": {"disclaimer_ref": "/legal/disclaimer/"},
    }

    # Agrega constelación solo si existe (mantiene JSON limpio)
    if constellation:
        entry["object"]["context"] = {"constellation": constellation}

    return entry



def run_git(repo_root: Path, args: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )


def git_commit_push(repo_root: Path, rel_file: str, entry_id: str, sao: int) -> None:
    r = run_git(repo_root, ["add", rel_file])
    if r.returncode != 0:
        raise RuntimeError(f"git add falló:\n{r.stderr or r.stdout}")

    msg = f"Add registry entry {entry_id} (SAO {sao})"
    r = run_git(repo_root, ["commit", "-m", msg])
    if r.returncode != 0:
        raise RuntimeError(f"git commit falló:\n{r.stderr or r.stdout}")

    r = run_git(repo_root, ["push"])
    if r.returncode != 0:
        raise RuntimeError(f"git push falló:\n{r.stderr or r.stdout}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sao", required=True, help="SAO (dígitos). Ej: 12345")
    ap.add_argument("--name", required=True, help="inscription.name")
    ap.add_argument("--motto", required=True, help="inscription.motto")
    ap.add_argument("--suffix-len", type=int, default=8, help="6–8 recomendado. Default 8.")
    ap.add_argument("--dry-run", action="store_true", help="Imprime JSON; no escribe archivo.")
    ap.add_argument("--no-git", action="store_true", help="Escribe archivo; no hace git add/commit/push.")
    args = ap.parse_args()

    if not re.fullmatch(r"\d+", args.sao.strip()):
        eprint("Error: --sao debe ser solo dígitos.")
        return 2
    sao = int(args.sao)
    if sao <= 0:
        eprint("Error: --sao inválido.")
        return 2

    name = args.name.strip()
    motto = args.motto.strip()
    if not name:
        eprint("Error: --name vacío.")
        return 2
    if not motto:
        eprint("Error: --motto vacío.")
        return 2

    if args.suffix_len < 6 or args.suffix_len > 12:
        eprint("Error: --suffix-len debe estar entre 6 y 12.")
        return 2

    ra_raw, dec_raw = vizier_lookup_sao(sao)
    if not ra_raw or not dec_raw:
        eprint(f"Error: SAO {sao} no encontrado en {VIZIER_TABLE}.")
        return 3

    ra_hours = parse_ra_to_hours(ra_raw)
    dec_deg = parse_dec_to_deg(dec_raw)
    constellation = compute_constellation_iau(ra_hours, dec_deg)
    ra_hms = hours_to_ra_hms(ra_hours, sec_precision=1)
    dec_dms = deg_to_dec_dms(dec_deg)
    validate_formats(ra_hms, dec_dms)

    repo_root = find_repo_root(Path(__file__).resolve())
    entries_dir = repo_root / "public" / "data" / "entries"
    entries_dir.mkdir(parents=True, exist_ok=True)

    # genera ID sin colisiones, sin overwrite
    entry_id = ""
    file_path: Optional[Path] = None
    for _ in range(12):
        entry_id = generate_id(sao, args.suffix_len)
        p = entries_dir / f"{entry_id}.json"
        if not p.exists():
            file_path = p
            break
    if file_path is None:
        eprint("Error: no pude generar un ID único.")
        return 4

    entry = build_entry(entry_id, sao, name, motto, ra_hms, dec_dms, constellation)
    json_text = json.dumps(entry, ensure_ascii=False, indent=2) + "\n"

    if args.dry_run:
        print(json_text, end="")
        return 0

    file_path.write_text(json_text, encoding="utf-8")

    rel_file = file_path.relative_to(repo_root).as_posix()
    print(f"Created entry: {entry_id}")
    print(f"File: {rel_file}")
    print(f"Coordinates: RA {ra_hms} | Dec {dec_dms} | Epoch J2000")
    print("Public URLs:")
    print(f"  /registry/{entry_id}")
    print(f"  /r/{entry_id}  (should 301 → /registry/{entry_id})")

    if args.no_git:
        print("Git: skipped (--no-git).")
        return 0

    try:
        git_commit_push(repo_root, rel_file, entry_id, sao)
        print("Git: committed and pushed.")
    except Exception as ex:
        eprint(str(ex))
        eprint("El archivo JSON ya existe localmente. Puedes hacer push manual:")
        eprint(f"  git add {rel_file}")
        eprint(f"  git commit -m \"Add registry entry {entry_id} (SAO {sao})\"")
        eprint("  git push")
        return 5

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
