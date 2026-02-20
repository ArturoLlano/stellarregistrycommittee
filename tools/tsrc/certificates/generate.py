from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from tools.tsrc.config import get_paths
from tools.tsrc.entries.io import read_entry_from_public
from tools.tsrc.entries.validate import validate_entry_or_raise
from tools.tsrc.certificates.layout import load_template_bundle
from tools.tsrc.certificates.render_reportlab import render_certificate_pdf


@dataclass(frozen=True)
class FailedItem:
    entry_id: str
    error: str


@dataclass(frozen=True)
class GenerateAllResult:
    generated: List[Path]
    skipped: List[Path]
    failed: List[FailedItem]


def generate_certificate_pdf_for_id(
    entry_id: str,
    *,
    force: bool = False,
    open_after: bool = True,
) -> Path:
    """
    Generate /public/certificates/<ID>/certificate.pdf from /public/data/entries/<ID>.json
    """
    paths = get_paths()
    entry = read_entry_from_public(entry_id)
    validate_entry_or_raise(entry, strict_qr=True)

    template_id = entry.certificate.template_id
    template = load_template_bundle(template_id)

    out_dir = (paths.certificates_dir / entry_id).resolve()
    out_pdf = (out_dir / "certificate.pdf").resolve()

    if out_pdf.exists() and not force:
        if open_after:
            _open_file_best_effort(out_pdf)
        return out_pdf

    render_certificate_pdf(entry=entry, template=template, out_pdf_path=out_pdf)

    if open_after:
        _open_file_best_effort(out_pdf)

    return out_pdf


def generate_all_certificates(
    *,
    force: bool = False,
    open_after: bool = False,
    only_missing: bool = True,
) -> GenerateAllResult:
    """
    Scan /public/data/entries/*.json and generate certificates.

    - only_missing=True: generate only when output PDF does not exist
    - force=True: regenerate always
    """
    paths = get_paths()
    entries_dir = paths.entries_dir
    if not entries_dir.exists():
        return GenerateAllResult(generated=[], skipped=[], failed=[FailedItem(entry_id="*", error=f"Missing entries dir: {entries_dir}")])

    generated: List[Path] = []
    skipped: List[Path] = []
    failed: List[FailedItem] = []

    for json_path in sorted(entries_dir.glob("*.json")):
        entry_id = json_path.stem
        try:
            out_dir = (paths.certificates_dir / entry_id).resolve()
            out_pdf = (out_dir / "certificate.pdf").resolve()

            if only_missing and out_pdf.exists() and not force:
                skipped.append(out_pdf)
                continue

            pdf = generate_certificate_pdf_for_id(entry_id, force=force, open_after=open_after)
            generated.append(pdf)
        except Exception as e:
            failed.append(FailedItem(entry_id=entry_id, error=str(e)))

    return GenerateAllResult(generated=generated, skipped=skipped, failed=failed)


def _open_file_best_effort(path: Path) -> None:
    """
    Cross-platform best-effort auto-open.

    - Windows: os.startfile
    - macOS:   open
    - Linux:   xdg-open
    """
    try:
        if sys.platform.startswith("win"):
            # type: ignore[attr-defined]
            import os
            os.startfile(str(path))  # noqa: E1101
            return

        if sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
            return

        # Linux and others
        subprocess.run(["xdg-open", str(path)], check=False)
    except Exception:
        # Silent failure: certificate generation must not depend on the opener.
        return
