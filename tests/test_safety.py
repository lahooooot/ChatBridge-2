import importlib
import json
import logging
import os
import shlex
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest

from desktop.audit import AuditLog
from desktop.chatfolder import create_chat_folder
from desktop.logging_setup import export_logs, recent_lines, setup_logging
from desktop.project import ProjectRegistry
from desktop.safety import Workspace
from desktop.tools import TOOL_NAMES, execute


def test_workspace_read_offsets_and_metadata(tmp_path):
    workspace = Workspace(tmp_path)
    workspace.write_file("file.txt", content="one\ntwo\nthree\n")
    result = workspace.read_file("file.txt", offset=1, limit=1)
    assert result["content"] == "two\n" and result["lines"] == 1
    assert result["truncated"] and result["total_lines"] == 3
    assert workspace.read_file("file.txt", offset=100)["content"] == ""
    assert workspace.read_file("file.txt", limit=None)["content"] == "one\ntwo\nthree\n"


def test_write_and_unique_patch_are_atomic(tmp_path):
    workspace = Workspace(tmp_path)
    workspace.write_file("src/app.py", content="before\nunique\nafter\n")
    result = workspace.write_file("src/app.py", search="unique", replace="replacement")
    assert result["written"] and result["lines"] == 3
    assert workspace.read_file("src/app.py")["content"] == "before\nreplacement\nafter\n"
    with pytest.raises(ValueError, match="exactly once"):
        workspace.write_file("src/app.py", search="missing", replace="bad")
    assert "bad" not in workspace.read_file("src/app.py")["content"]
    workspace.write_file("duplicates.txt", content="aa aa")
    with pytest.raises(ValueError, match="found 2"):
        workspace.write_file("duplicates.txt", search="aa", replace="b")
    workspace.write_file("overlap.txt", content="aaa")
    with pytest.raises(ValueError, match="found 2"):
        workspace.write_file("overlap.txt", search="aa", replace="b")


@pytest.mark.parametrize("kwargs", [
    {}, {"content": 5}, {"search": "", "replace": "a"},
    {"search": "a"}, {"replace": "a"}, {"content": "a", "search": "b", "replace": "c"},
])
def test_invalid_write_modes_do_not_create_file(tmp_path, kwargs):
    with pytest.raises(ValueError):
        Workspace(tmp_path).write_file("file.txt", **kwargs)
    assert not (tmp_path / "file.txt").exists()


def test_relative_absolute_and_symlink_escape_confinement(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    workspace = Workspace(root)
    assert workspace.resolve(str(root / "new.txt")) == root / "new.txt"
    for path in ("../outside", str(outside), "../../x", "\x00", "C:\\Windows\\system.ini"):
        with pytest.raises((PermissionError, ValueError)):
            workspace.resolve(path)
    try:
        (root / "link").symlink_to(outside, target_is_directory=True)
    except OSError:
        return
    for action in (
        lambda: workspace.read_file("link/private.txt"),
        lambda: workspace.write_file("link/file.txt", content="bad"),
        lambda: workspace.list_dir("link"),
        lambda: workspace.search_files("secret", path="link"),
    ):
        with pytest.raises(PermissionError):
            action()


def test_limits_and_binary_content(tmp_path):
    workspace = Workspace(tmp_path, max_bytes=5)
    with pytest.raises(ValueError, match="limit"):
        workspace.write_file("large", content="سلام")
    with pytest.raises(ValueError, match="Binary"):
        workspace.write_file("binary", content="a\x00b")
    (tmp_path / "large").write_bytes(b"123456")
    with pytest.raises(ValueError, match="limit"):
        workspace.read_file("large")
    with pytest.raises(ValueError):
        workspace.read_file("large", offset=-1)
    with pytest.raises(ValueError):
        workspace.list_dir(depth=9)


def test_list_dir_depth_and_search_caps(tmp_path):
    workspace = Workspace(tmp_path)
    workspace.write_file("root.txt", content="needle\nneedle\n")
    workspace.write_file("src/app.txt", content="not this\nneedle 123\n")
    workspace.write_file("node_modules/noisy.txt", content="needle noisy")
    entries = workspace.list_dir(".", depth=2)["entries"]
    assert any(row["name"] == "src/app.txt" for row in entries)
    assert not any(row["name"] == "node_modules/noisy.txt" for row in entries)
    matches = workspace.search_files("needle")["matches"]
    assert len(matches) == 3
    assert all(row["file"] != "node_modules/noisy.txt" for row in matches)
    assert workspace.search_files(r"needle \d+", regex=True)["matches"] == [{"file": "src/app.txt", "line": 2, "text": "needle 123"}]
    capped = workspace.search_files("needle", max=1)
    assert len(capped["matches"]) == 1 and capped["truncated"]
    with pytest.raises(ValueError, match="Invalid regular"):
        workspace.search_files("[", regex=True)
    with pytest.raises(ValueError, match="Nested repetition"):
        workspace.search_files("(a+)+$", regex=True)
    assert len(workspace.search_files("needle", path="root.txt")["matches"]) == 2


def test_search_skips_binary_and_symlinks(tmp_path):
    workspace = Workspace(tmp_path)
    (tmp_path / "binary.bin").write_bytes(b"needle\x00")
    (tmp_path / "real.txt").write_text("needle")
    try:
        (tmp_path / "loop").symlink_to(tmp_path, target_is_directory=True)
        (tmp_path / "alias.txt").symlink_to(tmp_path / "real.txt")
    except OSError:
        pass
    result = workspace.search_files("needle")
    assert result["matches"] == [{"file": "real.txt", "line": 1, "text": "needle"}]
    assert result["skipped"] == 1


BASE_TOOLS = {"read_file", "write_file", "list_dir", "search_files", "run_command"}


def test_tool_modules_export_execute_and_use_workspace(tmp_path):
    assert BASE_TOOLS.issubset(set(TOOL_NAMES))
    for name in BASE_TOOLS:
        assert callable(importlib.import_module("desktop.tools." + name).execute)
    execute(tmp_path, "write_file", {"path": "file.txt", "content": "hello"})
    assert execute(Workspace(tmp_path), "read_file", {"path": "file.txt"})["content"] == "hello"
    assert execute(tmp_path, "search_files", {"query": "hello"})["matches"]
    assert execute(tmp_path, "list_dir", {"path": "."})["entries"]
    with pytest.raises(ValueError, match="Available tools"):
        execute(tmp_path, "shell", {"cmd": "echo hello"})


@pytest.mark.parametrize("name,args", [
    ("read_file", {}), ("read_file", {"path": 5}), ("read_file", {"path": "x", "extra": True}),
    ("write_file", {"path": "x", "content": None}), ("write_file", {"path": "x", "search": "a"}),
    ("list_dir", {}), ("search_files", {}), ("run_command", {"command": "echo x"}),
])
def test_tool_argument_contract_errors(tmp_path, name, args):
    with pytest.raises(ValueError):
        execute(tmp_path, name, args)


def python_command(code):
    if os.name == "nt":
        import subprocess
        return subprocess.list2cmdline([sys.executable, "-c", code])
    return shlex.join([sys.executable, "-c", code])


def test_run_command_result_shape_and_confined_cwd(tmp_path):
    code = "import os,sys; print(os.getcwd()); print('error',file=sys.stderr);sys.exit(3)"
    result = execute(tmp_path, "run_command", {"cmd": python_command(code), "timeout": 3})
    assert set(("exit", "stdout", "stderr", "duration")) <= set(result)
    assert result["exit"] == 3 and str(tmp_path) in result["stdout"] and "error" in result["stderr"]
    with pytest.raises(PermissionError):
        execute(tmp_path, "run_command", {"cmd": "echo x", "cwd": ".."})
    with pytest.raises(ValueError):
        execute(tmp_path, "run_command", {"cmd": "echo x", "timeout": 3601})


def test_run_command_timeout_is_truthful(tmp_path):
    result = execute(tmp_path, "run_command", {"cmd": python_command("import time;time.sleep(30)"), "timeout": 1})
    assert result["timed_out"] and result["exit"] != 0 and "timed out" in result["error"]


def test_audit_concurrent_writers_across_connections_and_json(tmp_path):
    logs = [AuditLog(tmp_path / "audit.db") for _ in range(3)]
    try:
        def record(index):
            return logs[index % len(logs)].record("read_file", {"path": f"file{index}.txt"}, index % 2 == 0, result={"content": "سلام"}, error=None if index % 2 == 0 else "denied")
        with ThreadPoolExecutor(max_workers=8) as pool:
            ids = list(pool.map(record, range(120)))
        assert len(set(ids)) == 120
        rows = logs[0].recent(200)
        assert len(rows) == 120
        assert rows[0]["id"] > rows[-1]["id"]
        assert all(row["result"] == {"content": "سلام"} for row in rows)
        assert all(isinstance(row["ok"], bool) for row in rows)
        assert logs[0].recent(1)[0]["timestamp"]
        with pytest.raises(ValueError):
            logs[0].recent(-1)
    finally:
        for log in logs:
            log.close()


def test_audit_sql_payload_is_data_not_code_and_large_payload_is_bounded(tmp_path):
    with AuditLog(tmp_path / "audit.db") as log:
        log.record("write_file", {"path": "';DROP TABLE audit;--"}, False, error="denied")
        assert log.recent()[0]["args"]["path"] == "';DROP TABLE audit;--"
        log.record("read_file", {}, True, result="a" * (2 * 1024 * 1024 + 1))
        assert log.recent()[0]["result"]["truncated"]


def test_project_registry_persists_and_deduplicates(tmp_path):
    root, base = tmp_path / "project", tmp_path / "state"
    root.mkdir()
    registry = ProjectRegistry(base)
    first = registry.attach(root)
    second = registry.attach(root)
    assert first["id"] == second["id"] and first["created"] == second["created"]
    assert second["path"] == str(root) and not second["git"]
    assert ProjectRegistry(base).list() == [second]
    with pytest.raises(FileNotFoundError):
        registry.attach(tmp_path / "missing")
    (root / "file").write_text("x")
    with pytest.raises(NotADirectoryError):
        registry.attach(root / "file")


def test_project_registry_concurrent_updates(tmp_path):
    base = tmp_path / "state"
    roots = [tmp_path / f"p{index}" for index in range(10)]
    for root in roots:
        root.mkdir()
    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(lambda root: ProjectRegistry(base).attach(root), roots))
    assert len(ProjectRegistry(base).list()) == len(roots)


def test_chat_folder_sanitized_unique_and_confined(tmp_path):
    first = create_chat_folder("My Chat", base=tmp_path)
    second = create_chat_folder("My Chat", base=tmp_path)
    assert first["path"] != second["path"] and first["id"] != second["id"]
    assert os.path.isdir(first["path"]) and first["name"] == "My Chat"
    assert create_chat_folder("CON", base=tmp_path)["name"] == "_CON"
    assert create_chat_folder("سلام", base=tmp_path)["name"] == "سلام"
    for name in ("../escape", "a/b", "a\\b", "..", "", "C:\\escape"):
        with pytest.raises(ValueError):
            create_chat_folder(name, base=tmp_path)


def test_logging_setup_is_idempotent_and_export_contains_logs(tmp_path):
    path = setup_logging(tmp_path)
    setup_logging(tmp_path)
    handlers = [handler for handler in logging.getLogger().handlers if getattr(handler, "_chatbridge_path", None) == str(path)]
    assert len(handlers) == 1
    logging.getLogger("backend-test").warning("Searchable English diagnostic")
    for handler in handlers:
        handler.flush()
    assert any("Searchable English diagnostic" in line for line in recent_lines(tmp_path))
    exported = export_logs(tmp_path)
    with zipfile.ZipFile(exported) as archive:
        assert "logs/chatbridge.log" in archive.namelist()
    for handler in handlers:
        logging.getLogger().removeHandler(handler)
        handler.close()


def test_list_dir_bounds_enumeration_as_well_as_output(tmp_path, monkeypatch):
    import desktop.safety as safety
    for index in range(20):
        (tmp_path / f"file{index}.txt").write_text("x")
    monkeypatch.setattr(safety, "MAX_NODES", 4)
    result = Workspace(tmp_path).list_dir(".")
    assert len(result["entries"]) == 4 and result["truncated"]


@pytest.mark.skipif(os.name == "nt", reason="Windows paths are case-insensitive")
def test_distinct_case_sensitive_project_paths_have_distinct_ids(tmp_path):
    first, second = tmp_path / "Project", tmp_path / "project"
    first.mkdir()
    second.mkdir()
    registry = ProjectRegistry(tmp_path / "state")
    assert registry.attach(first)["id"] != registry.attach(second)["id"]
    assert len(registry.list()) == 2


def test_font_size_accepts_ui_string_values(tmp_path):
    from desktop.config import ConfigStore
    store = ConfigStore(tmp_path)
    assert store.update({"font_size": "small"})["font_size"] == "small"
