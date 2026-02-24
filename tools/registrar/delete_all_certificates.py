from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path

def _repo_root_from_here() -> Path:
    # tools/registrar/delete_all_certificates.py -> repo root = parents[2]
    return Path(__file__).resolve().parents[2]

def _run_git(repo_root: Path, args: list[str]) -> tuple[int, str, str]:
    p = subprocess.run(
        ["git", *args],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    return p.returncode, (p.stdout or ""), (p.stderr or "")

def delete_all_certificates(repo_root: Path, require_yes: bool = True) -> int:
    cert_dir = (repo_root / "public" / "certificates").resolve()
    if not cert_dir.exists():
        print(f"[OK] No certificates directory found: {cert_dir}")
        return 0

    pdfs = sorted(cert_dir.glob("*.pdf"))
    legacy_dirs = sorted([p for p in cert_dir.iterdir() if p.is_dir()])  # old folder-style artifacts

    if not pdfs and not legacy_dirs:
        print("[OK] No certificates to delete.")
        return 0

    total = len(pdfs) + len(legacy_dirs)
    print(f"About to delete {len(pdfs)} PDF(s) and {len(legacy_dirs)} legacy folder(s) under:")
    print(f"  {cert_dir}")
    print()

    if require_yes:
        ans = input("Type YES to continue (anything else cancels): ").strip()
        if ans != "YES":
            print("Cancelled.")
            return 2

    # Delete PDFs
    for p in pdfs:
        try:
            p.unlink()
        except Exception as e:
            print(f"[ERR] Failed to delete {p}: {e}")
            return 1

    # Delete legacy folders
    for d in legacy_dirs:
        # delete contents then folder
        try:
            for child in d.rglob("*"):
                if child.is_file():
                    child.unlink()
            # remove empty dirs bottom-up
            for child_dir in sorted([x for x in d.rglob("*") if x.is_dir()], reverse=True):
                try:
                    child_dir.rmdir()
                except Exception:
                    pass
            d.rmdir()
        except Exception as e:
            print(f"[ERR] Failed to delete folder {d}: {e}")
            return 1

    print("[OK] Local deletion done.")

    # Commit deletion to remote (so Pages removes them)
    rc, out, err = _run_git(repo_root, ["add", "-A", "--", "public/certificates"])
    if rc != 0:
        print("[ERR] git add failed:\n", err or out)
        return 1

    # Commit only if there are changes
    rcS, outS, errS = _run_git(repo_root, ["status", "--porcelain"])
    if rcS != 0:
        print("[ERR] git status failed:\n", errS or outS)
        return 1

    if "public/certificates" not in outS:
        print("[OK] Nothing to commit for certificates.")
        return 0

    msg = f"Remove published certificates ({total} item(s))"
    rcC, outC, errC = _run_git(repo_root, ["commit", "-m", msg, "--", "public/certificates"])
    if rcC != 0:
        print("[ERR] git commit failed:\n", errC or outC)
        return 1

    rcP, outP, errP = _run_git(repo_root, ["push"])
    if rcP != 0:
        print("[ERR] git push failed:\n", errP or outP)
        print("Tip: run manually:\n  git pull --rebase origin main\n  git push")
        return 1

    print("[OK] Deleted certificates have been pushed (remote will stop serving them after deploy).")
    return 0

if __name__ == "__main__":
    repo_root = _repo_root_from_here()
    sys.exit(delete_all_certificates(repo_root, require_yes=True))