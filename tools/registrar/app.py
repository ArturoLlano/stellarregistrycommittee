from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from flask import Flask, render_template, request

from registrar.entries import find_duplicates
from registrar.git_ops import GitResult, git_add_commit_push
from registrar.repo import detect_repo_context
from registrar.schema import build_entry_payload
from registrar.util import iso_utc_now, safe_int
from registrar.vizier import fetch_sao_metadata_best_effort


# Ensure repo root is on sys.path so we can import tools.tsrc.* from this app,
# even when running from tools/registrar/.venv.
REPO_ROOT = Path(__file__).resolve().parents[2]  # .../stellarregistrycommittee
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def create_app() -> Flask:
    app = Flask(__name__, static_folder="static", template_folder="templates")
    return app


app = create_app()


@app.get("/")
def index():
    # Minimal prefill support (optional)
    return render_template("index.html", error=None, form={})


@app.post("/preview")
def preview():
    ctx = detect_repo_context()
    if not ctx.ok:
        return render_template("error.html", title="Repository not detected", detail=ctx.error), 400

    form = {
        "sao": (request.form.get("sao") or "").strip(),
        "inscription_name": (request.form.get("inscription_name") or "").strip(),
        "inscription_motto": (request.form.get("inscription_motto") or "").strip(),
        "recorded_by": (request.form.get("recorded_by") or "").strip(),
        "sponsor": (request.form.get("sponsor") or "").strip(),
        # checkbox: if unchecked, it won't exist in POST => becomes ""
        "do_lookup": (request.form.get("do_lookup") or "").strip(),  # "on" or ""
    }

    sao = safe_int(form["sao"])
    if sao is None or sao <= 0:
        return render_template("index.html", error="SAO number must be a positive integer.", form=form), 400
    if not form["inscription_name"]:
        return render_template("index.html", error="Inscription name is required.", form=form), 400

    # Duplicate detection
    dups = find_duplicates(ctx, sao)
    if dups:
        # Show a clear warning and refuse to proceed
        return render_template("index.html", error=None, form=form, duplicates=dups, sao=sao), 409

    # Best-effort metadata lookup (optional)
    sao_meta = None
    coordinates = None
    lookup_error = None

    if form["do_lookup"]:
        sao_meta, lookup_error = fetch_sao_metadata_best_effort(sao)
        if sao_meta and isinstance(sao_meta.get("coordinates"), dict):
            c = sao_meta["coordinates"]
            coordinates = {
                "ra_hms": c.get("ra_hms", "") or "",
                "dec_dms": c.get("dec_dms", "") or "",
            }

    # Build preview payload + ID (no file written yet)
    # This call supports both:
    #  - new schema.py: build_entry_payload(..., sao_meta=sao_meta)
    #  - old schema.py: build_entry_payload(..., coordinates=coordinates)
    try:
        payload = build_entry_payload(
            sao=sao,
            inscription_name=form["inscription_name"],
            inscription_motto=form["inscription_motto"] or None,
            recorded_by=form["recorded_by"] or None,
            sponsor=form["sponsor"] or None,
            recorded_at_utc=iso_utc_now(),
            coordinates=coordinates,
            sao_meta=sao_meta,
        )
    except TypeError:
        payload = build_entry_payload(
            sao=sao,
            inscription_name=form["inscription_name"],
            inscription_motto=form["inscription_motto"] or None,
            recorded_by=form["recorded_by"] or None,
            sponsor=form["sponsor"] or None,
            recorded_at_utc=iso_utc_now(),
            coordinates=coordinates,
        )

    payload_json = json.dumps(payload, ensure_ascii=False, indent=2)
    payload_b64 = base64.b64encode(payload_json.encode("utf-8")).decode("ascii")

    return render_template(
        "preview.html",
        repo_root=str(ctx.repo_root),
        entries_dir=str(ctx.entries_dir),
        payload_json=payload_json,
        payload_b64=payload_b64,
        entry_id=payload["id"],
        sao=sao,
        lookup_error=lookup_error,
        form=form,
    )


@app.post("/commit")
def commit():
    ctx = detect_repo_context()
    if not ctx.ok:
        return render_template("error.html", title="Repository not detected", detail=ctx.error), 400

    payload_b64 = (request.form.get("payload_b64") or "").strip()
    if not payload_b64:
        return render_template("error.html", title="Missing payload", detail="Preview payload was not provided."), 400

    try:
        payload_json = base64.b64decode(payload_b64.encode("ascii")).decode("utf-8")
        payload = json.loads(payload_json)
    except Exception as e:
        return render_template("error.html", title="Invalid payload", detail=str(e)), 400

    entry_id = (payload.get("id") or "").strip()
    sao_str = None
    try:
        sao_str = payload["object"]["catalog"][0]["id"]
    except Exception:
        pass

    sao = safe_int(str(sao_str) if sao_str is not None else "")
    if not entry_id or sao is None:
        return render_template("error.html", title="Invalid payload", detail="Payload missing id or SAO catalog id."), 400

    # Re-check duplicates (race-safety)
    dups = find_duplicates(ctx, sao)
    if dups:
        return render_template(
            "error.html",
            title="Duplicate detected at commit time",
            detail=f"SAO {sao} already exists. Refusing to write/commit a new entry.",
            extra={"duplicates": [asdict(d) for d in dups]},
        ), 409

    # Write JSON file
    target_path = ctx.entries_dir / f"{entry_id}.json"
    target_path.parent.mkdir(parents=True, exist_ok=True)

    if target_path.exists():
        return render_template(
            "error.html",
            title="File already exists",
            detail=f"{target_path} already exists. Refusing to overwrite.",
        ), 409

    target_path.write_text(payload_json + "\n", encoding="utf-8")

    # -----------------------------
    # NEW: Generate certificate PDF
    # -----------------------------
    # This uses your TSRC certificate generator (ReportLab).
    # Requirements:
    # - ReportLab must be installed in the registrar venv.
    # - Entry JSON must be present (we just wrote it).
    try:
        from tools.tsrc.certificates.generate import generate_certificate_pdf_for_id
        from tools.tsrc.config import certificate_public_url

        pdf_path = generate_certificate_pdf_for_id(
            entry_id=entry_id,
            force=True,
            open_after=True,  # auto-open PDF ready to print (best effort)
        )
    except Exception as e:
        # Roll back the JSON write so the commit endpoint stays atomic.
        try:
            target_path.unlink(missing_ok=True)
        except Exception:
            pass

        return render_template(
            "error.html",
            title="Certificate generation failed",
            detail=(
                "The registry entry JSON was not committed because PDF generation failed.\n\n"
                f"Error: {e}\n\n"
                "Tip: ensure ReportLab is installed in the registrar virtualenv:\n"
                "  .\\.venv\\Scripts\\python -m pip install reportlab"
            ),
        ), 500

    # Stage PDF as well (so it is included in the SAME commit)
    # We stage it explicitly, then let existing git_add_commit_push handle the commit/push.
    try:
        rel_pdf = Path(pdf_path).resolve().relative_to(Path(ctx.repo_root).resolve())
        subprocess.run(
            ["git", "add", "--", rel_pdf.as_posix()],
            cwd=str(ctx.repo_root),
            check=True,
        )
    except Exception as e:
        # If staging fails, abort without committing
        try:
            target_path.unlink(missing_ok=True)
        except Exception:
            pass

        return render_template(
            "error.html",
            title="Git staging failed (certificate)",
            detail=f"Could not stage certificate PDF for commit.\n\nError: {e}",
        ), 500

    # Git add/commit/push (existing behavior; should include staged PDF too)
    git_result: GitResult = git_add_commit_push(
        repo_root=ctx.repo_root,
        file_path=target_path,
        commit_message=f"Add registry entry {entry_id}",
    )

    # Registry URLs (relative, QR-safe architecture)
    registry_url = f"/registry/{entry_id}"
    qr_url = f"/r/{entry_id}"

    # Certificate URLs
    certificate_site_path = f"/certificates/{entry_id}/certificate.pdf"
    try:
        certificate_url = certificate_public_url(entry_id)
    except Exception:
        # If config helper isn't present, we still provide the site-relative path.
        certificate_url = ""

    return render_template(
        "result.html",
        entry_id=entry_id,
        sao=sao,
        file_path=str(target_path),
        registry_url=registry_url,
        qr_url=qr_url,
        git=git_result,
        payload_json=payload_json,

        # NEW fields for your UI:
        certificate_file_path=str(pdf_path),
        certificate_site_path=certificate_site_path,
        certificate_url=certificate_url,
    )


if __name__ == "__main__":
    port = int(os.environ.get("REGISTRAR_PORT", "5055"))
    app.run(host="127.0.0.1", port=port, debug=False)