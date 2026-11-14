"""Git panel operations. Commands use argument arrays, never a shell."""
from __future__ import annotations

import difflib
import os
import re
import subprocess
import tempfile
import threading
from pathlib import Path

from .safety import Workspace
from .terminal import _kill_process_tree

MAX_GIT_OUTPUT = 2 * 1024 * 1024


class GitTools:
    def __init__(self, root):
        self.workspace = Workspace(root)
        self.root = self.workspace.root
        self._lock = threading.RLock()

    def _run(self, arguments, timeout=30, allowed=(0,)) -> dict:
        env = os.environ.copy()
        env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_PAGER": "cat", "LC_ALL": "C"})
        options = {"start_new_session": True} if os.name != "nt" else {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            try:
                process = subprocess.Popen(
                    ["git", "--no-pager", "-c", "core.quotepath=false", "-c", "color.ui=false", "-C", str(self.root), *arguments],
                    stdin=subprocess.DEVNULL, stdout=out, stderr=err, env=env, **options,
                )
                try:
                    code = process.wait(timeout=timeout)
                    timed_out = False
                except subprocess.TimeoutExpired:
                    _kill_process_tree(process)
                    code = process.wait(timeout=5)
                    timed_out = True
            except OSError as exc:
                return {"ok": False, "exit": None, "stdout": "", "stderr": str(exc), "error": f"Cannot run Git: {exc}"}
            out.seek(0)
            err.seek(0)
            stdout_bytes, stderr_bytes = out.read(MAX_GIT_OUTPUT + 1), err.read(MAX_GIT_OUTPUT + 1)
        stdout = stdout_bytes[:MAX_GIT_OUTPUT].decode("utf-8", errors="replace")
        stderr = stderr_bytes[:MAX_GIT_OUTPUT].decode("utf-8", errors="replace")
        result = {"ok": code in allowed and not timed_out, "exit": code, "stdout": stdout, "stderr": stderr,
                  "truncated": len(stdout_bytes) > MAX_GIT_OUTPUT or len(stderr_bytes) > MAX_GIT_OUTPUT}
        if not result["ok"]:
            result["error"] = f"Git command timed out after {timeout} seconds" if timed_out else stderr.strip() or stdout.strip() or f"Git exited with status {code}"
        return result

    def _repository(self) -> Path:
        result = self._run(["rev-parse", "--show-toplevel"])
        if not result["ok"]:
            raise ValueError(result["error"])
        return Path(result["stdout"].strip()).resolve()

    def status(self) -> dict:
        with self._lock:
            result = self._run(["status", "--porcelain=v1", "-z", "--branch", "--untracked-files=normal"])
            if not result["ok"]:
                return {**result, "branch": "", "changes": [], "is_repo": False}
            repo_root = self._repository()
            parts = result["stdout"].split("\x00")
            header = parts.pop(0) if parts and parts[0].startswith("## ") else ""
            branch_line = header[3:]
            detached = branch_line.startswith("HEAD ")
            branch = "HEAD" if detached else branch_line.split("...", 1)[0].split(" [", 1)[0]
            for prefix in ("No commits yet on ", "Initial commit on "):
                if branch.startswith(prefix):
                    branch = branch[len(prefix):]
            ahead_match, behind_match = re.search(r"ahead (\d+)", header), re.search(r"behind (\d+)", header)
            changes, index = [], 0
            while index < len(parts):
                entry = parts[index]
                index += 1
                if not entry or len(entry) < 4:
                    continue
                code, path = entry[:2], entry[3:]
                old_path = None
                if "R" in code or "C" in code:
                    if index < len(parts):
                        old_path = parts[index]
                        index += 1
                full = repo_root / path
                if not full.is_relative_to(self.root):
                    continue
                row = {"path": full.relative_to(self.root).as_posix(), "status": code,
                       "staged": code[0] not in (" ", "?"), "untracked": code == "??",
                       "index": code[0], "worktree": code[1]}
                if old_path is not None:
                    row["old_path"] = old_path
                changes.append(row)
            return {"ok": True, "branch": branch, "changes": changes, "is_repo": True,
                    "detached": detached, "ahead": int(ahead_match[1]) if ahead_match else 0,
                    "behind": int(behind_match[1]) if behind_match else 0,
                    "root": str(self.root), "repo_root": str(repo_root), "truncated": result["truncated"]}

    def _paths(self, args, repo_root, *, required=False):
        value = args.get("paths", args.get("path"))
        if value is None:
            if required and not args.get("all"):
                raise ValueError("This action needs explicit paths or all=true")
            return [":(top,literal)" + (self.root.relative_to(repo_root).as_posix() or ".")]
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list) or not value or not all(isinstance(path, str) and path for path in value):
            raise ValueError("paths must be a nonempty list of path strings")
        result = []
        for path in value:
            resolved = self.workspace.resolve(path)
            if resolved.name == ".git" or ".git" in resolved.relative_to(repo_root).parts:
                raise PermissionError("Git metadata cannot be changed through panel file actions")
            # Literal pathspec magic prevents wildcards/:(...) from selecting
            # files the user did not name, while '--' prevents option injection.
            relative = resolved.relative_to(repo_root).as_posix()
            result.append(":(top,literal)" + (relative or "."))
        return result

    def _branch(self, value):
        if not isinstance(value, str) or not value or value.startswith("-") or "\x00" in value:
            raise ValueError("A valid branch name is required")
        check = self._run(["check-ref-format", "--branch", value])
        if not check["ok"]:
            raise ValueError(f"Invalid branch name: {value}")
        return value

    def _remote_args(self, args):
        remote = args.get("remote")
        branch = args.get("branch")
        if remote is None:
            if branch is not None:
                raise ValueError("Specify a remote when specifying a remote branch")
            return []
        if not isinstance(remote, str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", remote):
            raise ValueError("remote must name a configured Git remote")
        remotes = self._run(["remote"])
        if not remotes["ok"] or remote not in remotes["stdout"].splitlines():
            raise ValueError(f"Unknown Git remote: {remote}")
        return [remote, self._branch(branch)] if branch is not None else [remote]

    def action(self, action, args=None) -> dict:
        if args is None:
            args = {}
        if not isinstance(args, dict):
            return {"ok": False, "error": "Git action arguments must be an object"}
        try:
            with self._lock:
                repo_root = self._repository()
                if action == "diff":
                    arguments = ["diff", "--no-ext-diff", "--no-textconv"]
                    if args.get("staged"):
                        arguments.append("--cached")
                    result = self._run([*arguments, "--", *self._paths(args, repo_root)])
                    # Git diff omits untracked files; show an honest new-file
                    # diff for a single explicitly requested text file instead.
                    if result["ok"] and not result["stdout"] and isinstance(args.get("path"), str) and not args.get("staged"):
                        target = self.workspace.resolve(args["path"])
                        tracked = self._run(["ls-files", "--error-unmatch", "--", *self._paths(args, repo_root)])
                        if not tracked["ok"] and target.is_file():
                            content = self.workspace.read_file(target, limit=None)["content"]
                            result["stdout"] = "".join(difflib.unified_diff([], content.splitlines(keepends=True), fromfile="/dev/null", tofile=args["path"]))[:MAX_GIT_OUTPUT]
                    result["diff"] = result["stdout"]
                    return result
                if action == "stage":
                    return self._run(["add", "--all", "--", *self._paths(args, repo_root)])
                if action == "unstage":
                    paths = self._paths(args, repo_root)
                    has_head = self._run(["rev-parse", "--verify", "HEAD"])["ok"]
                    return self._run(["restore", "--staged", "--", *paths] if has_head else ["rm", "-r", "--cached", "--ignore-unmatch", "--", *paths])
                if action == "commit":
                    message = args.get("message")
                    if not isinstance(message, str) or not message.strip() or len(message) > 8000 or "\x00" in message:
                        raise ValueError("Commit message must be a nonempty string of at most 8000 characters")
                    ticket = args.get("ticket")
                    if ticket:
                        if not isinstance(ticket, str) or not re.fullmatch(r"[A-Z][A-Z0-9]+-\d+", ticket):
                            raise ValueError("Invalid issue ticket; expected a value such as PROJ-123")
                        message = f"{ticket}: {message}"
                    return self._run(["commit", "-m", message], timeout=120)
                if action == "push":
                    return self._run(["push", *self._remote_args(args)], timeout=120)
                if action == "pull":
                    return self._run(["pull", "--ff-only", *self._remote_args(args)], timeout=120)
                if action == "discard":
                    paths = self._paths(args, repo_root, required=True)
                    value = args.get("paths", args.get("path"))
                    targets = [value] if isinstance(value, str) else value
                    if targets:
                        for target_path in targets:
                            target = self.workspace.resolve(target_path)
                            tracked = self._run(["ls-files", "--error-unmatch", "--", *self._paths({"path": target_path}, repo_root)])
                            if not tracked["ok"]:
                                if target.is_dir():
                                    raise ValueError("Discard will not recursively delete an untracked directory")
                                if target.exists():
                                    target.unlink()
                                # Remove the untracked path from the restore list.
                                paths.remove(self._paths({"path": target_path}, repo_root)[0])
                    if not paths:
                        return {"ok": True, "exit": 0, "stdout": "Untracked file discarded", "stderr": ""}
                    return self._run(["restore", "--source=HEAD", "--staged", "--worktree", "--", *paths])
                if action == "branches":
                    result = self._run(["for-each-ref", "--format=%(refname:short)\t%(HEAD)", "refs/heads/"])
                    if result["ok"]:
                        result["branches"] = [{"name": line.rsplit("\t", 1)[0], "current": line.endswith("\t*")} for line in result["stdout"].splitlines() if line]
                    return result
                if action in ("checkout", "branch"):
                    name = self._branch(args.get("branch", args.get("name")))
                    if args.get("create") or action == "branch":
                        return self._run(["switch", "-c", name])
                    return self._run(["switch", "--", name])
                if action == "log":
                    limit = args.get("limit", 50)
                    if type(limit) is not int or not 1 <= limit <= 500:
                        raise ValueError("limit must be an integer between 1 and 500")
                    return self._run(["log", "--no-color", "--format=%H%x09%an%x09%aI%x09%s", f"-n{limit}", "--"])
                if action == "show":
                    ref = args.get("ref", "HEAD")
                    if not isinstance(ref, str) or not ref or ref.startswith("-") or "\x00" in ref:
                        raise ValueError("A valid Git ref is required")
                    return self._run(["show", "--no-color", "--stat", "--patch", ref])
                if action == "blame":
                    rel = args.get("path")
                    if not isinstance(rel, str) or not rel:
                        raise ValueError("blame needs an explicit path")
                    resolved = self.workspace.resolve(rel)
                    if resolved.name == ".git" or ".git" in resolved.relative_to(repo_root).parts:
                        raise PermissionError("Git metadata cannot be blamed")
                    relative = resolved.relative_to(repo_root).as_posix()
                    return self._run(["blame", "--line-porcelain", "--", relative])
                if action == "snapshot":
                    label = args.get("label") or "chatbridge-snapshot"
                    if not isinstance(label, str) or not label.strip() or len(label) > 120 or "\x00" in label:
                        raise ValueError("snapshot label must be a short nonempty string")
                    has_head = self._run(["rev-parse", "--verify", "HEAD"])["ok"]
                    if has_head:
                        created = self._run(["stash", "create", label])
                    else:
                        created = self._run(["stash", "create", label], allowed=(0,))
                    sha = created["stdout"].strip().splitlines()[-1] if created["stdout"].strip() else ""
                    return {"ok": created["ok"], "label": label, "stash_sha": sha, "stdout": created["stdout"], "stderr": created["stderr"], "exit": created["exit"]}
                if action == "rollback":
                    sha = args.get("sha")
                    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-fA-F]{7,64}", sha):
                        raise ValueError("rollback needs a valid stash sha")
                    applied = self._run(["stash", "apply", sha])
                    if not applied["ok"]:
                        return applied
                    dropped = self._run(["stash", "drop", sha], allowed=(0, 1))
                    return {"ok": True, "applied": sha, "stdout": applied["stdout"], "stderr": applied["stderr"] + dropped["stderr"], "exit": applied["exit"]}
                raise ValueError(f"Unknown Git action: {action}")
        except (ValueError, PermissionError, OSError, TypeError) as exc:
            return {"ok": False, "error": str(exc)}
