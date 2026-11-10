import os
import shutil
import subprocess

import pytest

from desktop.gittools import GitTools

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="Git is not installed")


def git(root, *args, check=True):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=check)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Test User")
    git(root, "config", "user.email", "test@example.invalid")
    (root / "tracked.txt").write_text("original\n")
    git(root, "add", "--", "tracked.txt")
    git(root, "commit", "-m", "Initial commit")
    return root


def test_status_branch_tracked_untracked_and_staging(repo):
    tools = GitTools(repo)
    assert tools.status()["branch"] == "main"
    assert tools.status()["changes"] == []
    (repo / "tracked.txt").write_text("changed\n")
    (repo / "new.txt").write_text("new\n")
    status = tools.status()
    changes = {row["path"]: row for row in status["changes"]}
    assert changes["tracked.txt"]["status"] == " M"
    assert changes["new.txt"]["untracked"]
    assert tools.action("stage", {"paths": ["tracked.txt", "new.txt"]})["ok"]
    assert all(row["staged"] for row in tools.status()["changes"])
    assert tools.action("unstage", {"path": "tracked.txt"})["ok"]
    assert not next(row for row in tools.status()["changes"] if row["path"] == "tracked.txt")["staged"]


def test_diff_staged_unstaged_and_untracked(repo):
    tools = GitTools(repo)
    (repo / "tracked.txt").write_text("changed\n")
    diff = tools.action("diff", {"path": "tracked.txt"})
    assert diff["ok"] and "-original" in diff["diff"] and "+changed" in diff["diff"]
    assert tools.action("stage", {"path": "tracked.txt"})["ok"]
    assert "+changed" in tools.action("diff", {"path": "tracked.txt", "staged": True})["diff"]
    (repo / "new.txt").write_text("new content\n")
    assert "+new content" in tools.action("diff", {"path": "new.txt"})["diff"]


def test_commit_real_message_and_no_shell_injection(repo, tmp_path):
    tools = GitTools(repo)
    (repo / "tracked.txt").write_text("committed\n")
    assert tools.action("stage", {"path": "tracked.txt"})["ok"]
    sentinel = tmp_path / "INJECTION"
    message = f"Fix'; touch {sentinel}; #"
    commit = tools.action("commit", {"message": message})
    assert commit["ok"], commit
    assert git(repo, "log", "-1", "--format=%B").stdout.strip() == message
    assert not sentinel.exists()
    assert not tools.action("commit", {"message": "nothing staged"})["ok"]
    assert not tools.action("commit", {"message": ""})["ok"]


def test_ticket_commit_template(repo):
    tools = GitTools(repo)
    (repo / "new.txt").write_text("new")
    tools.action("stage", {"path": "new.txt"})
    assert tools.action("commit", {"message": "Implement feature", "ticket": "PROJ-123"})["ok"]
    assert git(repo, "log", "-1", "--format=%s").stdout.strip() == "PROJ-123: Implement feature"


def test_discard_tracked_and_untracked(repo):
    tools = GitTools(repo)
    (repo / "tracked.txt").write_text("changed")
    tools.action("stage", {"path": "tracked.txt"})
    assert tools.action("discard", {"path": "tracked.txt"})["ok"]
    assert (repo / "tracked.txt").read_text() == "original\n"
    (repo / "new.txt").write_text("untracked")
    assert tools.action("discard", {"path": "new.txt"})["ok"]
    assert not (repo / "new.txt").exists()
    assert not tools.action("discard")["ok"]
    (repo / "directory").mkdir()
    (repo / "directory" / "keep.txt").write_text("keep")
    assert not tools.action("discard", {"path": "directory"})["ok"]
    assert (repo / "directory" / "keep.txt").exists()


def test_branch_create_list_checkout_and_errors(repo):
    tools = GitTools(repo)
    assert tools.action("checkout", {"branch": "feature", "create": True})["ok"]
    assert tools.status()["branch"] == "feature"
    branches = tools.action("branches")
    assert branches["ok"]
    assert {row["name"] for row in branches["branches"]} == {"main", "feature"}
    assert next(row for row in branches["branches"] if row["name"] == "feature")["current"]
    assert tools.action("checkout", {"branch": "main"})["ok"]
    assert not tools.action("checkout", {"branch": "missing"})["ok"]
    assert not tools.action("checkout", {"branch": "--orphan"})["ok"]
    assert not tools.action("checkout", {"branch": "bad; touch file"})["ok"]
    assert not tools.action("made-up")["ok"]


def test_detached_head_and_rename_status(repo):
    tools = GitTools(repo)
    git(repo, "mv", "tracked.txt", "renamed.txt")
    change = tools.status()["changes"][0]
    assert change["path"] == "renamed.txt" and change["old_path"] == "tracked.txt"
    assert change["status"] == "R "
    git(repo, "reset", "--hard", "HEAD")
    git(repo, "checkout", "--detach")
    assert tools.status()["detached"]


def test_unborn_repository_can_stage_unstage_and_commit(tmp_path):
    root = tmp_path / "unborn"
    root.mkdir()
    git(root, "init", "-b", "main")
    (root / "new.txt").write_text("new")
    tools = GitTools(root)
    assert tools.status()["branch"] == "main"
    assert tools.action("stage", {"path": "new.txt"})["ok"]
    assert tools.action("unstage", {"path": "new.txt"})["ok"]
    assert (root / "new.txt").exists()
    assert tools.status()["changes"][0]["untracked"]


def test_paths_outside_repository_and_git_metadata_are_rejected(repo, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("private")
    tools = GitTools(repo)
    for action in ("stage", "unstage", "diff", "discard"):
        result = tools.action(action, {"path": "../outside.txt"})
        assert not result["ok"] and "outside" in result["error"]
        assert not tools.action(action, {"path": ".git/config"})["ok"]
    assert outside.read_text() == "private"


def test_literal_dash_and_wildcard_file_paths(repo):
    tools = GitTools(repo)
    (repo / "-danger.txt").write_text("dash")
    assert tools.action("stage", {"path": "-danger.txt"})["ok"]
    if os.name != "nt":
        (repo / "*.txt").write_text("literal")
        (repo / "plain.txt").write_text("plain")
        assert tools.action("stage", {"path": "*.txt"})["ok"]
        changes = {row["path"]: row for row in tools.status()["changes"]}
        assert changes["*.txt"]["staged"]
        assert not changes["plain.txt"]["staged"]


def test_subdirectory_workspace_is_confined_and_paths_are_correct(repo):
    sub = repo / "sub"
    sub.mkdir()
    (sub / "file.txt").write_text("sub")
    tools = GitTools(sub)
    result = tools.action("stage", {"path": "file.txt"})
    assert result["ok"], result
    assert tools.status()["changes"][0]["path"] == "file.txt"
    assert tools.action("unstage", {"path": "file.txt"})["ok"]
    assert tools.action("stage")["ok"]
    assert not tools.action("stage", {"path": "../tracked.txt"})["ok"]


def test_push_and_pull_with_local_bare_remote(repo, tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-u", "origin", "main")
    tools = GitTools(repo)
    (repo / "pushed.txt").write_text("pushed")
    tools.action("stage", {"path": "pushed.txt"})
    tools.action("commit", {"message": "Push me"})
    assert tools.action("push", {"remote": "origin", "branch": "main"})["ok"]
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-b", "main", str(remote), str(clone)], check=True, capture_output=True)
    git(clone, "config", "user.name", "Other User")
    git(clone, "config", "user.email", "other@example.invalid")
    (clone / "pulled.txt").write_text("pulled")
    git(clone, "add", "--", "pulled.txt")
    git(clone, "commit", "-m", "Remote change")
    git(clone, "push")
    assert tools.action("pull", {"remote": "origin", "branch": "main"})["ok"]
    assert (repo / "pulled.txt").read_text() == "pulled"
    assert not tools.action("push", {"remote": "--bad"})["ok"]
    assert not tools.action("push", {"remote": "missing"})["ok"]


def test_non_repository_and_bad_arguments_are_explicit(tmp_path):
    tools = GitTools(tmp_path)
    status = tools.status()
    assert not status["ok"] and not status["is_repo"] and status["error"]
    assert not tools.action("stage")["ok"]
    assert not tools.action("diff", "wrong")["ok"]
