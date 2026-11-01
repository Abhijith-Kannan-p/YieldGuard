"""Fetch the Karnataka mandi snapshot on this computer and push it to the orphan "data" branch.

    cd C:\\Users\\Madhav\\YieldGuard\\backend
    ..\\.venv\\Scripts\\python.exe -m devtools.publish_mandi_snapshot

data.gov.in refuses connections from cloud servers (Render, GitHub Actions), so this runs on a home
connection, e.g. every 6 hours from Windows Task Scheduler. It:
- checks out "data" (or starts it as an orphan) in a temporary worktree under a throwaway local branch,
- runs devtools/fetch_mandi_snapshot.py into it, so an unchanged snapshot keeps the existing file,
- commits only if something changed, as "YieldGuard snapshot (laptop)", and pushes it to origin "data",
- always removes the worktree and the throwaway branch. main and your working tree are never touched.
Prints one line, appends it to backend/.cache/mandi_publish.log, and exits non-zero on any failure.
Git output is never printed (it can hold remote URLs); the fetch never prints the key.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from app import config
from app.timeutil import iso, now_local
from devtools import fetch_mandi_snapshot

REPO = Path(__file__).resolve().parents[2]
LOG_FILE = config.CACHE_DIR / "mandi_publish.log"
BRANCH = "data"
AUTHOR = ("YieldGuard snapshot (laptop)", "yieldguard-snapshot@noreply.invalid")
GIT_TIMEOUT_S = 120


class PublishError(Exception):
    """A short cause that is safe to print."""


def git(repo: Path, *args: str, check: bool = True, timeout: float = GIT_TIMEOUT_S) -> subprocess.CompletedProcess:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}  # a scheduled run must never wait for a password prompt
    cmd = next((a for a in args if not a.startswith("-") and "=" not in a), "command")  # e.g. "commit", not "-c"
    try:
        r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, env=env, timeout=timeout)
    except FileNotFoundError:
        raise PublishError("git is not installed") from None
    except subprocess.TimeoutExpired:
        raise PublishError(f"git {cmd} timed out") from None
    if check and r.returncode != 0:
        raise PublishError(f"git {cmd} failed")
    return r


def publish(repo: Path = REPO, remote: str = "origin", fetch=fetch_mandi_snapshot.snapshot) -> str:
    """Fetch into a temporary checkout of the data branch, commit if changed, push. Returns the result line."""
    stamp = now_local().strftime("%Y%m%d-%H%M%S")
    temp_branch = f"mandi-publish-{stamp}-{os.getpid()}"
    tmp = Path(tempfile.mkdtemp(prefix="yieldguard-data-"))
    worktree = tmp / "data"
    added = False
    try:
        exists = git(repo, "ls-remote", "--exit-code", "--heads", remote, BRANCH, check=False)
        if exists.returncode == 0:
            # No --depth: a shallow fetch would mark the whole repository as shallow.
            git(repo, "fetch", remote, f"+refs/heads/{BRANCH}:refs/remotes/{remote}/{BRANCH}")
            git(repo, "worktree", "add", "-b", temp_branch, str(worktree), f"refs/remotes/{remote}/{BRANCH}")
        elif exists.returncode == 2:  # the remote has no data branch yet
            git(repo, "worktree", "add", "--orphan", "-b", temp_branch, str(worktree))
        else:
            raise PublishError("git ls-remote failed")
        added = True

        try:
            r = fetch(out_dir=worktree / "data" / "mandi")
        except fetch_mandi_snapshot.SnapshotError as e:
            raise PublishError(str(e)) from None
        what = f"{r['name']} (newest arrival date {r['date']}, {r['records']} records)"

        git(worktree, "add", "data/mandi")
        if git(worktree, "diff", "--cached", "--quiet", check=False).returncode == 0:
            return f"unchanged: {what}"
        # Author and no signing for this one commit only; the global git config is not changed.
        git(worktree, "-c", f"user.name={AUTHOR[0]}", "-c", f"user.email={AUTHOR[1]}", "-c", "commit.gpgsign=false",
            "commit", "-m", f"Mandi snapshot: {r['name']}")
        git(worktree, "push", remote, f"HEAD:refs/heads/{BRANCH}")
        extra = ", index updated" if r["status"] == "unchanged" and r.get("index") == "written" else ""
        return f"{r['status']}: {what}{extra}, pushed"
    finally:
        if added:
            git(repo, "worktree", "remove", "--force", str(worktree), check=False)
        git(repo, "worktree", "prune", check=False)
        git(repo, "branch", "-D", temp_branch, check=False)
        shutil.rmtree(tmp, ignore_errors=True)


def log(line: str, log_file: Path = LOG_FILE) -> None:
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with log_file.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass  # the printed line still reports the result


def main(repo: Path = REPO, remote: str = "origin", fetch=fetch_mandi_snapshot.snapshot,
         log_file: Path = LOG_FILE) -> int:
    try:
        line, code = publish(repo, remote, fetch), 0
    except PublishError as e:
        line, code = f"failed: {e}", 1
    except Exception as e:  # anything unexpected: the type only, never the text
        line, code = f"failed: {type(e).__name__}", 1
    line = f"{iso(now_local())} {line}"
    print(line, file=sys.stderr if code else sys.stdout)
    log(line, log_file)
    return code


if __name__ == "__main__":
    sys.exit(main())
