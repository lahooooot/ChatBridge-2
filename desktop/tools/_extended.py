"""Extended tools that need more than a bare Workspace.

Each handler has signature execute(workspace, args, services) where services is
the live Desktop API object. Keeping these out of Workspace avoids coupling
file operations to Git, terminals, or network."""
from __future__ import annotations

import re
import threading
import time
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ..gittools import GitTools

MAX_HTTP_BYTES = 2 * 1024 * 1024
ALLOWED_HTTP_SCHEMES = ("http", "https")
_BLOCKED_NETS = ("10.", "127.", "172.16.", "172.17.", "172.18.", "172.19.",
                 "172.2", "172.30.", "172.31.", "192.168.", "169.254.", "0.0.0.0")


def _git(workspace, args, action):
    return GitTools(str(workspace.root)).action(action, args)


def git_status(workspace, args, services):
    return _git(workspace, {"all": True}, "status")


def git_diff(workspace, args, services):
    return _git(workspace, args, "diff")


def git_log(workspace, args, services):
    return _git(workspace, args, "log")


def git_show(workspace, args, services):
    return _git(workspace, args, "show")


def git_blame(workspace, args, services):
    return _git(workspace, args, "blame")


def git_stage(workspace, args, services):
    return _git(workspace, args, "stage")


def git_unstage(workspace, args, services):
    return _git(workspace, args, "unstage")


def git_commit(workspace, args, services):
    return _git(workspace, args, "commit")


def git_branch(workspace, args, services):
    return _git(workspace, args, "branches")


def git_checkout(workspace, args, services):
    return _git(workspace, args, "checkout")


def snapshot(workspace, args, services):
    return _git(workspace, args, "snapshot")


def rollback(workspace, args, services):
    return _git(workspace, args, "rollback")


def process_control(workspace, args, services):
    action = args.get("action", "list")
    terminal = services.terminal
    if action == "list":
        with terminal._lock:
            jobs = list(terminal._jobs.values())
        rows = []
        for job in jobs:
            rows.append({
                "id": job["id"], "cmd": job.get("cmd"), "cwd": job.get("cwd"),
                "running": job.get("running"), "exit": job.get("exit"),
                "duration": round(time.monotonic() - job["_started"], 3) if job.get("running") else job.get("duration"),
            })
        return {"processes": rows}
    ident = args.get("id")
    if not isinstance(ident, str) or not ident:
        raise ValueError("process_control needs an id for kill/result")
    if action == "kill":
        return {"killed": bool(terminal.kill(ident)), "id": ident}
    if action == "result":
        return terminal.result(ident)
    raise ValueError("process_control action must be list, kill, or result")


def run_tests(workspace, args, services):
    from ..terminal import TerminalManager
    framework = args.get("framework", "auto")
    cwd = str(workspace.resolve(args.get("cwd", ".")))
    extra = args.get("args") or []
    if not isinstance(extra, list) or not all(isinstance(item, str) for item in extra):
        raise ValueError("args must be a list of strings")
    if framework == "auto":
        if workspace.resolve("pyproject.toml").exists() or workspace.resolve("pytest.ini").exists():
            framework = "pytest"
        elif workspace.resolve("package.json").exists():
            framework = "jest"
        elif workspace.resolve("go.mod").exists():
            framework = "go"
        elif workspace.resolve("Cargo.toml").exists():
            framework = "cargo"
        else:
            raise ValueError("Could not auto-detect a test framework; pass framework explicitly")
    commands = {
        "pytest": ["python", "-m", "pytest", "-q", *extra],
        "jest": ["npx", "jest", "--silent", *extra],
        "go": ["go", "test", "./...", *extra],
        "cargo": ["cargo", "test", "--quiet", *extra],
    }
    if framework not in commands:
        raise ValueError("framework must be one of pytest, jest, go, or cargo")
    timeout = int(args.get("timeout", 600))
    complete = threading.Event()
    def sink(event):
        if event.get("type") == "terminal_exit":
            complete.set()
    manager = TerminalManager(sink)
    ident = manager.run(commands[framework], cwd, timeout=timeout)
    if not complete.wait(timeout + 15):
        manager.kill(ident)
        raise TimeoutError("Test run exceeded its deadline")
    result = manager.result(ident)
    output = (result.get("stdout") or "") + (result.get("stderr") or "")
    summary = {"framework": framework, "exit": result.get("exit"), "ok": result.get("exit") == 0,
               "duration": result.get("duration"), "truncated": result.get("truncated"),
               "stdout": result.get("stdout", ""), "stderr": result.get("stderr", "")}
    counts = {}
    for pattern, key in ((r"(\d+) passed", "passed"), (r"(\d+) failed", "failed"),
                         (r"(\d+) error(?:s)?", "errors"), (r"(\d+) skipped", "skipped")):
        match = re.search(pattern, output)
        if match:
            counts[key] = int(match.group(1))
    if counts:
        summary["counts"] = counts
    return summary


def _is_blocked_host(hostname):
    lowered = (hostname or "").lower().rstrip(".")
    if lowered in ("localhost", "::1", "0.0.0.0"):
        return True
    return any(lowered.startswith(prefix) for prefix in _BLOCKED_NETS)


def http_fetch(workspace, args, services):
    url = args.get("url")
    if not isinstance(url, str) or not url:
        raise ValueError("http_fetch needs a url")
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_HTTP_SCHEMES:
        raise ValueError("http_fetch only supports http and https URLs")
    if _is_blocked_host(parsed.hostname):
        raise PermissionError("http_fetch refuses loopback, private, and link-local hosts")
    timeout = args.get("timeout", 30)
    if type(timeout) is not int or not 1 <= timeout <= 120:
        raise ValueError("timeout must be an integer between 1 and 120 seconds")
    headers = {"User-Agent": "ChatBridge/2.50 http_fetch"}
    custom = args.get("headers")
    if custom is not None:
        if not isinstance(custom, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in custom.items()):
            raise ValueError("headers must be an object of string values")
        headers.update(custom)
    request = Request(url, headers=headers, method="GET")
    with urlopen(request, timeout=timeout) as response:
        status = getattr(response, "status", None)
        final_url = response.geturl()
        content_type = response.headers.get("Content-Type", "") if hasattr(response, "headers") else ""
        raw = response.read(MAX_HTTP_BYTES + 1)
    truncated = len(raw) > MAX_HTTP_BYTES
    body = raw[:MAX_HTTP_BYTES]
    try:
        text = body.decode("utf-8")
        binary = False
    except UnicodeDecodeError:
        text = body.decode("utf-8", errors="replace")
        binary = True
    result = {"status": status, "url": final_url, "bytes": len(body), "truncated": truncated,
              "binary": binary, "content": text[:20000]}
    if content_type:
        result["content_type"] = content_type
    return result


HANDLERS = {
    "git_status": git_status, "git_diff": git_diff, "git_log": git_log,
    "git_show": git_show, "git_blame": git_blame, "git_stage": git_stage,
    "git_unstage": git_unstage, "git_commit": git_commit, "git_branch": git_branch,
    "git_checkout": git_checkout,
    "snapshot": snapshot, "rollback": rollback,
    "process_control": process_control,
    "run_tests": run_tests,
    "http_fetch": http_fetch,
}

__all__ = ["HANDLERS", *HANDLERS]
