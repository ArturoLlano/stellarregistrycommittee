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


def _git_add_paths(repo_root: Path, rel_paths_posix: list[str]) -> None:
    """
    Stage files. If add fails (commonly because of .gitignore), retry with -f.
    Raises RuntimeError with captured stderr/stdout on failure.
    """
    r = subprocess.run(
        ["git", "add", "--", *rel_paths_posix],
        cwd=str(repo_root),
        text=True,
        capture_output=True,
        check=False,
    )
    if r.returncode == 0:
        return

    msg1 = (r.stderr or r.stdout or "").strip()

    # Retry forced add (useful if path is ignored)
    r2 = subprocess.run(
        ["git", "add", "-f", "--", *rel_paths_posix],
        cwd=str(repo_root),
        text=True,
        capture_output=True,
        check=False,
    )
    if r2.returncode == 0:
        return

    msg2 = (r2.stderr or r2.stdout or "").strip()
    raise RuntimeError(f"git add failed.\n\nFirst attempt:\n{msg1}\n\nRetry (-f):\n{msg2}")


def _open_file_best_effort(path: Path) -> None:
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
            return
        if sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
            return
        subprocess.run(["xdg-open", str(path)], check=False)
    except Exception:
        return


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
    target_path = (ctx.entries_dir / f"{entry_id}.json").resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)

    if target_path.exists():
        return render_template(
            "error.html",
            title="File already exists",
            detail=f"{target_path} already exists. Refusing to overwrite.",
        ), 409

    target_path.write_text(payload_json + "\n", encoding="utf-8")

    # -----------------------------
    # NEW: Generate certificate PDF (do not open yet)
    # -----------------------------
    try:
        from tools.tsrc.certificates.generate import generate_certificate_pdf_for_id
        from tools.tsrc.config import certificate_public_url

        pdf_path = Path(
            generate_certificate_pdf_for_id(
                entry_id=entry_id,
                force=True,
                open_after=False,  # open AFTER successful commit/push
            )
        ).resolve()

        if not pdf_path.exists():
            raise RuntimeError(f"Certificate PDF was not created: {pdf_path}")

    except Exception as e:
        # Roll back JSON write so /commit stays atomic
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

    # -----------------------------
    # Stage JSON + PDF together
    # -----------------------------
    try:
        repo_root = Path(ctx.repo_root).resolve()
        rel_json = target_path.relative_to(repo_root).as_posix()
        rel_pdf = pdf_path.relative_to(repo_root).as_posix()

        _git_add_paths(repo_root, [rel_json, rel_pdf])

    except Exception as e:
        # Roll back files to keep commit endpoint clean
        try:
            target_path.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            pdf_path.unlink(missing_ok=True)
        except Exception:
            pass

        return render_template(
            "error.html",
            title="Git staging failed (certificate)",
            detail=str(e),
        ), 500

    # -----------------------------
    # Git add/commit/push (existing behavior)
    # - git_add_commit_push will add/commit/push the entry file,
    #   and since PDF is already staged, it will be included in the same commit.
    # -----------------------------
    git_result: GitResult = git_add_commit_push(
        repo_root=ctx.repo_root,
        file_path=target_path,
        commit_message=f"Add registry entry {entry_id}",
    )

    # Open PDF AFTER successful commit/push (best effort)
    _open_file_best_effort(pdf_path)

    # Registry URLs (relative, QR-safe architecture)
    registry_url = f"/registry/{entry_id}"
    qr_url = f"/r/{entry_id}"

    # Certificate URLs
    certificate_site_path = f"/certificates/{entry_id}/certificate.pdf"
    try:
        certificate_url = certificate_public_url(entry_id)
    except Exception:
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