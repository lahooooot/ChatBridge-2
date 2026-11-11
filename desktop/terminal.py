"""Live background commands with bounded retained output and cancellation."""
from __future__ import annotations

import codecs
import copy
import logging
import os
import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path

log = logging.getLogger(__name__)
MAX_OUTPUT_CHARS = 1024 * 1024
MAX_TIMEOUT = 3600
MAX_COMPLETED_JOBS = 200


def _command_argv(cmd):
    if isinstance(cmd, str):
        if not cmd.strip() or "\x00" in cmd:
            raise ValueError("Command must be a nonempty string without NUL characters")
        if os.name == "nt":
            # A list lets Popen re-quote every element, and cmd.exe /s then strips
            # the outer quotes, breaking quotes inside the user command. Build the
            # full command line as one string instead so it reaches cmd.exe verbatim.
            return f'{os.environ.get("COMSPEC", "cmd.exe")} /d /s /c "{cmd}"'
        return ["/bin/sh", "-c", cmd]
    if isinstance(cmd, (list, tuple)) and cmd and all(isinstance(part, str) and "\x00" not in part for part in cmd):
        return list(cmd)
    raise ValueError("Command must be a string or a nonempty list of argument strings")


def _kill_process_tree(process) -> None:
    """Terminate the command's process group, including inherited children."""
    if os.name == "nt":
        try:
            completed = subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=5, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if completed.returncode == 0:
                return
        except (OSError, subprocess.TimeoutExpired):
            log.exception("Could not use taskkill for process %s", process.pid)
        try:
            process.kill()
        except OSError:
            pass
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError:
        process.kill()
        return
    time.sleep(0.15)
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


class TerminalManager:
    def __init__(self, sink, max_output=MAX_OUTPUT_CHARS, max_history=MAX_COMPLETED_JOBS):
        if not callable(sink):
            raise ValueError("Terminal sink must be callable")
        if type(max_output) is not int or not 1 <= max_output <= 32 * 1024 * 1024:
            raise ValueError("max_output must be between 1 and 33554432 characters")
        if type(max_history) is not int or not 1 <= max_history <= 10000:
            raise ValueError("max_history must be between 1 and 10000")
        self.sink = sink
        self.max_output = max_output
        self.max_history = max_history
        self._jobs = {}
        self._lock = threading.RLock()
        self._sink_lock = threading.RLock()

    def _emit(self, event):
        try:
            with self._sink_lock:
                self.sink(event)
        except Exception:
            log.exception("Terminal event sink failed")

    def _prune_history(self):
        completed = sorted((job for job in self._jobs.values() if not job["running"]), key=lambda job: job["_completed"])
        for job in completed[:-self.max_history]:
            self._jobs.pop(job["id"], None)

    def run(self, cmd, cwd, timeout=300) -> str:
        argv = _command_argv(cmd)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= MAX_TIMEOUT:
            raise ValueError(f"timeout must be greater than zero and at most {MAX_TIMEOUT} seconds")
        directory = Path(cwd or os.getcwd()).expanduser().resolve(strict=True)
        if not directory.is_dir():
            raise NotADirectoryError(f"Command cwd is not a directory: {directory}")
        ident = f"term-{uuid.uuid4().hex}"
        job = {
            "id": ident, "cmd": copy.deepcopy(cmd), "cwd": str(directory),
            "stdout": "", "stderr": "", "exit": None, "duration": 0.0,
            "running": True, "cancelled": False, "timed_out": False,
            "truncated": False, "discarded_chars": 0,
            "_process": None, "_stop": threading.Event(), "_started": time.monotonic(),
        }
        with self._lock:
            self._jobs[ident] = job
        threading.Thread(target=self._worker, args=(job, argv, timeout), name=ident, daemon=True).start()
        return ident

    def _output(self, job, stream, text):
        if not text:
            return
        # Windows pipes emit CRLF; normalize so callers and tests compare against \n.
        text = text.replace("\r\n", "\n")
        with self._lock:
            job[stream] += text
            excess = len(job["stdout"]) + len(job["stderr"]) - self.max_output
            if excess > 0:
                job["truncated"] = True
                job["discarded_chars"] += excess
                other = "stderr" if stream == "stdout" else "stdout"
                remove_other = min(excess, len(job[other]))
                job[other] = job[other][remove_other:]
                excess -= remove_other
                if excess:
                    job[stream] = job[stream][excess:]
        self._emit({"type": "terminal_output", "id": job["id"], "stream": stream, "text": text})

    def _reader(self, job, stream, pipe):
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        try:
            while True:
                data = os.read(pipe.fileno(), 4096)
                if not data:
                    break
                self._output(job, stream, decoder.decode(data))
            self._output(job, stream, decoder.decode(b"", final=True))
        except (OSError, ValueError):
            log.debug("Terminal pipe closed for %s", job["id"], exc_info=True)
        finally:
            pipe.close()

    def _worker(self, job, argv, timeout):
        process, readers, error = None, [], None
        try:
            options = ({"start_new_session": True} if os.name != "nt"
                       else {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "CREATE_NO_WINDOW", 0)})
            process = subprocess.Popen(
                argv, cwd=job["cwd"], stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0, **options,
            )
            with self._lock:
                job["_process"] = process
            for stream in ("stdout", "stderr"):
                reader = threading.Thread(target=self._reader, args=(job, stream, getattr(process, stream)), daemon=True)
                reader.start()
                readers.append(reader)
            deadline = job["_started"] + timeout
            while process.poll() is None:
                if job["_stop"].is_set():
                    _kill_process_tree(process)
                    break
                if time.monotonic() >= deadline:
                    with self._lock:
                        job["timed_out"] = True
                    _kill_process_tree(process)
                    break
                job["_stop"].wait(min(0.05, max(0, deadline - time.monotonic())))
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _kill_process_tree(process)
                process.wait(timeout=5)
            while any(reader.is_alive() for reader in readers):
                if job["_stop"].is_set() or time.monotonic() >= deadline:
                    if not job["_stop"].is_set():
                        with self._lock:
                            job["timed_out"] = True
                    _kill_process_tree(process)
                    break
                for reader in readers:
                    reader.join(timeout=0.025)
            for reader in readers:
                reader.join(timeout=1)
        except Exception as exc:
            error = f"Command failed: {exc}"
            log.exception("Terminal command failed")
            if process is not None:
                _kill_process_tree(process)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
            self._output(job, "stderr", error + "\n")
        finally:
            with self._lock:
                job["exit"] = process.returncode if process is not None and process.returncode is not None else -1
                job["duration"] = round(time.monotonic() - job["_started"], 6)
                job["_completed"] = time.monotonic()
                job["running"] = False
                if error:
                    job["error"] = error
                elif job["timed_out"]:
                    job["error"] = f"Command timed out after {timeout} seconds"
                elif job["cancelled"]:
                    job["error"] = "Command cancelled"
                event = {"type": "terminal_exit", "id": job["id"], "exit": job["exit"], "duration": job["duration"], "cancelled": job["cancelled"], "timed_out": job["timed_out"]}
                if "error" in job:
                    event["error"] = job["error"]
                self._prune_history()
            self._emit(event)

    def kill(self, id) -> bool:
        with self._lock:
            job = self._jobs.get(id)
            if job is None or not job["running"]:
                return False
            job["cancelled"] = True
            job["_stop"].set()
        return True

    def result(self, id) -> dict:
        with self._lock:
            if id not in self._jobs:
                raise KeyError(f"Unknown terminal command: {id}")
            job = self._jobs[id]
            snapshot = {key: copy.deepcopy(value) for key, value in job.items() if not key.startswith("_")}
            if job["running"]:
                snapshot["duration"] = round(time.monotonic() - job["_started"], 6)
            return snapshot
