from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess


@dataclass
class GitResult:
    ok: bool
    steps: list[str]
    error: str | None = None
    hint: str | None = None


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, check=False)


def git_add_commit_push(*, repo_root: Path, file_path: Path, commit_message: str) -> GitResult:
    steps: list[str] = []

    # Check git availability
    try:
        v = _run(["git", "--version"], repo_root)
    except FileNotFoundError:
        return GitResult(ok=False, steps=steps, error="Git not found. Install Git and ensure it is on PATH.")

    if v.returncode != 0:
        return GitResult(ok=False, steps=steps, error=f"Git not available: {v.stderr.strip() or v.stdout.strip()}")

    # Confirm we're inside a git repo
    p = _run(["git", "rev-parse", "--is-inside-work-tree"], repo_root)
    if p.returncode != 0 or p.stdout.strip() != "true":
        return GitResult(ok=False, steps=steps, error="Not a git working tree.")

    # Block if there are unmerged paths (rebase/merge conflict)
    st = _run(["git", "status", "--porcelain"], repo_root)
    if st.returncode == 0 and any(line.startswith("UU ") or line.startswith("AA ") or line.startswith("DD ") for line in st.stdout.splitlines()):
        return GitResult(
            ok=False,
            steps=steps,
            error="Working tree has merge conflicts (unmerged paths). Resolve them before committing.",
        )

    # Ensure remote exists (origin is typical)
    rem = _run(["git", "remote"], repo_root)
    if rem.returncode != 0:
        return GitResult(ok=False, steps=steps, error="Unable to read git remotes.")

    remotes = {r.strip() for r in rem.stdout.splitlines() if r.strip()}
    if not remotes:
        return GitResult(ok=False, steps=steps, error="No git remotes configured. Add a remote (e.g., origin).")

    # Stage only the new file
    rel_path = file_path.resolve().relative_to(repo_root.resolve())
    add = _run(["git", "add", "--", str(rel_path)], repo_root)
    steps.append(f"git add -- {rel_path}")
    if add.returncode != 0:
        return GitResult(ok=False, steps=steps, error=add.stderr.strip() or add.stdout.strip())

    # Commit only that file
    commit = _run(["git", "commit", "-m", commit_message, "--", str(rel_path)], repo_root)
    steps.append(f'git commit -m "{commit_message}" -- {rel_path}')
    if commit.returncode != 0:
        msg = (commit.stderr.strip() or commit.stdout.strip())
        # Common: "nothing to commit" (shouldn't happen) or missing user.name/email
        hint = None
        if "user.name" in msg or "user.email" in msg:
            hint = 'Set git identity: git config --global user.name "Your Name" && git config --global user.email "you@example.com"'
        return GitResult(ok=False, steps=steps, error=msg, hint=hint)

    # Push (uses your existing auth: HTTPS credential manager or SSH key)
    push = _run(["git", "push"], repo_root)
    steps.append("git push")
    if push.returncode != 0:
        msg = (push.stderr.strip() or push.stdout.strip())
        hint = None
        if "set-upstream" in msg or "upstream" in msg and "git push" in msg:
            hint = "Your branch may not track a remote. Try: git push -u origin HEAD"
        elif "rejected" in msg or "fetch first" in msg or "non-fast-forward" in msg:
            hint = "Remote is ahead. Try: git pull --rebase  (then)  git push"
        return GitResult(ok=False, steps=steps, error=msg, hint=hint)

    return GitResult(ok=True, steps=steps)
