from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess


@dataclass(frozen=True)
class RepoContext:
    ok: bool
    repo_root: Path | None = None
    entries_dir: Path | None = None
    error: str | None = None


def _find_repo_root_by_walking(start: Path) -> Path | None:
    cur = start.resolve()
    for _ in range(20):
        if (cur / ".git").exists():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return None


def _find_repo_root_by_git(start: Path) -> Path | None:
    try:
        p = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(start),
            capture_output=True,
            text=True,
            check=False,
        )
        if p.returncode == 0:
            return Path(p.stdout.strip()).resolve()
    except FileNotFoundError:
        return None
    except Exception:
        return None
    return None


def detect_repo_context() -> RepoContext:
    start = Path.cwd()

    repo_root = _find_repo_root_by_git(start) or _find_repo_root_by_walking(start)
    if not repo_root:
        return RepoContext(
            ok=False,
            error="Could not detect repo root. Run this tool from inside your git repository.",
        )

    entries_dir = repo_root / "public" / "data" / "entries"
    if not entries_dir.exists():
        # Not fatal: tool can create it on commit, but warn via UI? Keep ok=True.
        pass

    return RepoContext(ok=True, repo_root=repo_root, entries_dir=entries_dir)
