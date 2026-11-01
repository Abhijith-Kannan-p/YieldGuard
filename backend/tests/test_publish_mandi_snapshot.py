"""devtools/publish_mandi_snapshot.py against throwaway git repositories in a temp folder (a bare "remote"
and a clone standing in for the laptop's checkout). The fetch is served from the saved real snapshot."""
import shutil
import subprocess
from functools import partial

import httpx
import pytest

from app import config
from devtools import fetch_mandi_snapshot, publish_mandi_snapshot as pub

from .conftest import load_fixture

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
SNAPSHOT = "mandi_karnataka_2026-11-01.json"


def sh(cwd, *args) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repos(tmp_path, monkeypatch):
    """remote.git (bare, with main) and repo (a clone on main with a clean working tree)."""
    monkeypatch.setattr(config, "DATAGOV_API_KEY", "f" * 56)
    monkeypatch.setattr(fetch_mandi_snapshot, "RETRY_PAUSE_S", 0)
    remote, repo = tmp_path / "remote.git", tmp_path / "repo"
    sh(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    sh(tmp_path, "clone", "-q", str(remote), str(repo))
    (repo / "app.txt").write_text("app\n", encoding="utf-8")
    sh(repo, "add", "app.txt")
    sh(repo, "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "init")
    sh(repo, "push", "-q", "origin", "main")
    return remote, repo, tmp_path / "publish.log"


def fetch_with(answer):
    transport = httpx.MockTransport(answer)
    return partial(fetch_mandi_snapshot.snapshot, transport)


def saved_snapshot(request):
    return httpx.Response(200, json=load_fixture(SNAPSHOT))


def assert_untouched(repo, main_head):
    assert sh(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main" and sh(repo, "rev-parse", "main") == main_head
    assert sh(repo, "status", "--porcelain") == ""  # no change in the working tree
    assert sh(repo, "branch", "--format=%(refname:short)").split() == ["main"]  # no data or throwaway branch
    assert len(sh(repo, "worktree", "list").splitlines()) == 1
    assert subprocess.run(["git", "config", "--local", "user.name"], cwd=repo, capture_output=True).returncode != 0


def test_first_run_starts_the_orphan_data_branch_and_pushes(repos, capsys):
    remote, repo, log = repos
    main_head = sh(repo, "rev-parse", "main")
    code = pub.main(repo=repo, fetch=fetch_with(saved_snapshot), log_file=log)
    printed = capsys.readouterr().out
    assert code == 0
    assert "written: 2026-11-01.json (newest arrival date 2026-11-01, 31 records), pushed" in printed
    assert sh(remote, "ls-tree", "-r", "--name-only", "data") == "data/mandi/2026-11-01.json"
    assert sh(remote, "log", "--format=%an <%ae> | %s", "data") == (
        "YieldGuard snapshot (laptop) <yieldguard-snapshot@noreply.invalid> | Mandi snapshot: 2026-11-01.json")
    assert sh(remote, "rev-list", "--count", "data") == "1"
    assert subprocess.run(["git", "merge-base", "main", "data"], cwd=remote, capture_output=True).returncode != 0  # orphan
    assert sh(remote, "rev-parse", "main") == main_head
    assert_untouched(repo, main_head)
    assert log.read_text(encoding="utf-8").strip().endswith("pushed")


def test_second_run_with_the_same_data_is_unchanged(repos, capsys):
    remote, repo, log = repos
    main_head = sh(repo, "rev-parse", "main")
    pub.main(repo=repo, fetch=fetch_with(saved_snapshot), log_file=log)
    code = pub.main(repo=repo, fetch=fetch_with(saved_snapshot), log_file=log)
    assert code == 0 and "unchanged: 2026-11-01.json (newest arrival date 2026-11-01" in capsys.readouterr().out
    assert sh(remote, "rev-list", "--count", "data") == "1"
    assert_untouched(repo, main_head)
    assert len(log.read_text(encoding="utf-8").splitlines()) == 2


def test_failed_fetch_pushes_nothing_and_is_logged(repos, capsys):
    remote, repo, log = repos
    main_head = sh(repo, "rev-parse", "main")
    code = pub.main(repo=repo, fetch=fetch_with(lambda r: httpx.Response(502)), log_file=log)
    printed = capsys.readouterr().err
    assert code == 1 and printed.strip().endswith("failed: HTTP 502")
    assert subprocess.run(["git", "rev-parse", "--verify", "data"], cwd=remote, capture_output=True).returncode != 0
    assert log.read_text(encoding="utf-8").strip().endswith("failed: HTTP 502")
    assert config.DATAGOV_API_KEY not in printed
    assert_untouched(repo, main_head)


def test_rejected_push_fails_and_leaves_nothing_behind(repos, capsys):
    remote, repo, log = repos
    main_head = sh(repo, "rev-parse", "main")
    hook = remote / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho rejected for a test >&2\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    code = pub.main(repo=repo, fetch=fetch_with(saved_snapshot), log_file=log)
    assert code == 1 and capsys.readouterr().err.strip().endswith("failed: git push failed")
    assert subprocess.run(["git", "rev-parse", "--verify", "data"], cwd=remote, capture_output=True).returncode != 0
    assert_untouched(repo, main_head)
