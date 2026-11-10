import os
import sys
import threading
import time
from types import SimpleNamespace

import pytest

import desktop.terminal as terminal
from desktop.terminal import TerminalManager


def manager_with_events(max_output=1024 * 1024):
    events, condition = [], threading.Condition()

    def sink(event):
        with condition:
            events.append(event)
            condition.notify_all()

    return TerminalManager(sink, max_output=max_output), events, condition


def wait_for(condition, predicate, timeout=5):
    with condition:
        assert condition.wait_for(predicate, timeout), "Timed out waiting for terminal event"


def finished(manager, ident, condition, events, timeout=5):
    wait_for(condition, lambda: any(event["type"] == "terminal_exit" and event["id"] == ident for event in events), timeout)
    return manager.result(ident)


def test_stdout_stderr_stream_live_before_exit(tmp_path):
    manager, events, condition = manager_with_events()
    code = "import sys,time; print('first',flush=True); print('error-first',file=sys.stderr,flush=True); time.sleep(.4); print('last',flush=True)"
    ident = manager.run([sys.executable, "-u", "-c", code], str(tmp_path))
    wait_for(condition, lambda: any(event["type"] == "terminal_output" for event in events))
    assert manager.result(ident)["running"]
    result = finished(manager, ident, condition, events)
    assert result["exit"] == 0
    assert result["stdout"] == "first\nlast\n"
    assert result["stderr"] == "error-first\n"
    output = [event for event in events if event["type"] == "terminal_output"]
    assert {event["stream"] for event in output} == {"stdout", "stderr"}
    assert all(set(("type", "id", "stream", "text")) <= set(event) for event in output)
    assert events[-1]["type"] == "terminal_exit"
    assert events[-1]["duration"] >= .4


def test_partial_line_and_incremental_unicode_are_emitted(tmp_path):
    manager, events, condition = manager_with_events()
    code = "import os,time; os.write(1,b'partial'); time.sleep(.25); os.write(1,bytes([0xe2])); time.sleep(.1); os.write(1,bytes([0x82,0xac]));"
    ident = manager.run([sys.executable, "-u", "-c", code], str(tmp_path))
    wait_for(condition, lambda: any(event.get("text") == "partial" for event in events))
    assert manager.result(ident)["running"]
    assert finished(manager, ident, condition, events)["stdout"] == "partial€"


def test_nonzero_exit_is_preserved(tmp_path):
    manager, events, condition = manager_with_events()
    ident = manager.run([sys.executable, "-c", "import sys; print('bad',file=sys.stderr); sys.exit(7)"], str(tmp_path))
    result = finished(manager, ident, condition, events)
    assert result["exit"] == 7 and "bad" in result["stderr"]


def test_timeout_is_reported_and_process_is_reaped(tmp_path):
    manager, events, condition = manager_with_events()
    ident = manager.run([sys.executable, "-u", "-c", "import time; print('started',flush=True); time.sleep(30)"], str(tmp_path), timeout=.2)
    result = finished(manager, ident, condition, events)
    assert result["timed_out"] and not result["running"]
    assert result["exit"] != 0 and "timed out" in result["error"]
    assert events[-1]["timed_out"] is True


def test_cancel_immediately_is_nonblocking_and_final(tmp_path):
    manager, events, condition = manager_with_events()
    ident = manager.run([sys.executable, "-c", "import time;time.sleep(30)"], str(tmp_path))
    started = time.monotonic()
    assert manager.kill(ident)
    assert time.monotonic() - started < .2
    result = finished(manager, ident, condition, events)
    assert result["cancelled"] and not result["running"]
    assert manager.kill(ident) is False
    assert manager.kill("unknown") is False


@pytest.mark.skipif(os.name == "nt", reason="Linux process-group integration test")
def test_kill_terminates_child_process_tree(tmp_path):
    manager, events, condition = manager_with_events()
    code = "import subprocess,sys,time; child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); print(child.pid,flush=True); time.sleep(60)"
    ident = manager.run([sys.executable, "-u", "-c", code], str(tmp_path))
    wait_for(condition, lambda: bool(manager.result(ident)["stdout"].strip()))
    child_pid = int(manager.result(ident)["stdout"].strip())
    assert manager.kill(ident)
    finished(manager, ident, condition, events)
    stat = f"/proc/{child_pid}/stat"
    if os.path.exists(stat):
        # A zombie is already terminated; its reaping belongs to container init.
        with open(stat) as stream:
            assert stream.read().rsplit(")", 1)[1].strip().split()[0] == "Z"


@pytest.mark.skipif(os.name == "nt", reason="Linux inherited-pipe integration test")
def test_timeout_stops_children_after_parent_has_exited(tmp_path):
    manager, events, condition = manager_with_events()
    code = "import subprocess,sys; subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']); print('parent done')"
    ident = manager.run([sys.executable, "-u", "-c", code], str(tmp_path), timeout=.3)
    result = finished(manager, ident, condition, events)
    assert result["timed_out"] and result["duration"] < 3


def test_retained_output_is_capped_but_sink_receives_live_complete_output(tmp_path):
    manager, events, condition = manager_with_events(max_output=256)
    code = "import os; os.write(1,b'a'*10000); os.write(2,b'b'*10000)"
    ident = manager.run([sys.executable, "-c", code], str(tmp_path))
    result = finished(manager, ident, condition, events)
    assert len(result["stdout"]) + len(result["stderr"]) <= 256
    assert result["truncated"] and result["discarded_chars"] == 20000 - 256
    assert sum(len(event["text"]) for event in events if event["type"] == "terminal_output") == 20000


def test_spawn_error_is_explicit_and_exit_is_emitted(tmp_path):
    manager, events, condition = manager_with_events()
    ident = manager.run([str(tmp_path / "missing-executable")], str(tmp_path))
    result = finished(manager, ident, condition, events)
    assert result["exit"] == -1 and result["error"]
    assert "Command failed" in result["stderr"]


@pytest.mark.parametrize("command,timeout", [("", 1), ("\x00", 1), ([], 1), ("echo x", 0), ("echo x", 3601), ("echo x", True)])
def test_invalid_input_rejected_before_start(tmp_path, command, timeout):
    with pytest.raises(ValueError):
        TerminalManager(lambda _: None).run(command, str(tmp_path), timeout)


def test_invalid_cwd_and_unknown_result_are_explicit(tmp_path):
    manager = TerminalManager(lambda _: None)
    with pytest.raises(FileNotFoundError):
        manager.run("echo hello", str(tmp_path / "missing"))
    with pytest.raises(KeyError, match="Unknown"):
        manager.result("unknown")


def test_sink_exceptions_do_not_break_cleanup(tmp_path):
    def broken_sink(event):
        raise RuntimeError("UI unavailable")
    manager = TerminalManager(broken_sink)
    ident = manager.run([sys.executable, "-c", "print('hello')"], str(tmp_path))
    deadline = time.monotonic() + 5
    while manager.result(ident)["running"] and time.monotonic() < deadline:
        time.sleep(.02)
    assert not manager.result(ident)["running"]
    assert manager.result(ident)["exit"] == 0


def test_windows_taskkill_uses_pid_and_tree_flags_without_shell(monkeypatch):
    calls = []
    process = SimpleNamespace(pid=123, kill=lambda: calls.append("fallback"))
    monkeypatch.setattr(terminal, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(terminal.subprocess, "run", lambda args, **kwargs: calls.append((args, kwargs)) or SimpleNamespace(returncode=0))
    terminal._kill_process_tree(process)
    assert calls[0][0] == ["taskkill", "/PID", "123", "/T", "/F"]
    assert not calls[0][1].get("shell", False)
    assert "fallback" not in calls


def test_windows_taskkill_failure_falls_back_to_kill(monkeypatch):
    calls = []
    process = SimpleNamespace(pid=123, kill=lambda: calls.append("fallback"))
    monkeypatch.setattr(terminal, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(terminal.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=1))
    terminal._kill_process_tree(process)
    assert calls == ["fallback"]


def test_completed_history_is_bounded_and_keeps_newest_results(tmp_path):
    events, condition = [], threading.Condition()

    def sink(event):
        with condition:
            events.append(event)
            condition.notify_all()

    manager = TerminalManager(sink, max_history=3)
    ids = []
    for index in range(7):
        ident = manager.run([sys.executable, "-c", f"print({index})"], str(tmp_path))
        ids.append(ident)
        finished(manager, ident, condition, events)
    assert len(manager._jobs) == 3
    for ident in ids[:-3]:
        with pytest.raises(KeyError):
            manager.result(ident)
    assert manager.result(ids[-1])["stdout"] == "6\n"
    assert TerminalManager(lambda _: None).max_history == 200


def test_history_pruning_never_removes_running_jobs(tmp_path):
    events, condition = [], threading.Condition()

    def sink(event):
        with condition:
            events.append(event)
            condition.notify_all()

    manager = TerminalManager(sink, max_history=1)
    active = manager.run([sys.executable, "-c", "import time;time.sleep(20)"], str(tmp_path))
    for _ in range(3):
        ident = manager.run([sys.executable, "-c", "pass"], str(tmp_path))
        finished(manager, ident, condition, events)
    assert manager.result(active)["running"]
    assert len(manager._jobs) == 2
    manager.kill(active)
    finished(manager, active, condition, events)
    assert len(manager._jobs) == 1
