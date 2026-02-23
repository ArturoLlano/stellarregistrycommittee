from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess


class GitError(RuntimeError):
    pass


@dataclass(frozen=True)
class GitResult:
    committed: bool
    pushed: bool
    message: str


def _run(repo_root: Path, args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo_root),
        text=True,
        capture_output=True,
        check=False,
    )


def git_add_commit_push(
    *,
    repo_root: Path,
    paths: list[Path],
    commit_message: str,
    push: bool = True,
) -> GitResult:
    """
    Adds given paths, commits if there are staged changes, and optionally pushes.

    - Safe if there is nothing to commit.
    - Raises GitError for real failures.
    """
    if not repo_root.exists():
        raise GitError(f"Repo root not found: {repo_root}")

    # git add
    rels: list[str] = []
    for p in paths:
        rp = p.resolve()
        try:
            rel = rp.relative_to(repo_root.resolve())
        except Exception:
            # fallback: still try absolute path
            rel = rp
        rels.append(rel.as_posix())

    r = _run(repo_root, ["add", "--", *rels])
    if r.returncode != 0:
        raise GitError(f"git add failed:\n{r.stderr.strip() or r.stdout.strip()}")

    # If nothing staged, stop.
    r = _run(repo_root, ["diff", "--cached", "--quiet"])
    if r.returncode == 0:
        return GitResult(committed=False, pushed=False, message="Nothing to commit.")

    # commit
    r = _run(repo_root, ["commit", "-m", commit_message])
    if r.returncode != 0:
        raise GitError(f"git commit failed:\n{r.stderr.strip() or r.stdout.strip()}")

    if not push:
        return GitResult(committed=True, pushed=False, message="Committed (push skipped).")

    # push
    r = _run(repo_root, ["push"])
    if r.returncode != 0:
        raise GitError(f"git push failed:\n{r.stderr.strip() or r.stdout.strip()}")

    return GitResult(committed=True, pushed=True, message="Committed and pushed.")
