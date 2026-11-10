"""Execute an approved command in the workspace with a bounded timeout.

This intentionally executes shell command syntax; approval belongs to the API.
Confining cwd does not sandbox a shell command's capabilities.
"""
import threading

from ..terminal import TerminalManager
from ._common import string_arg, workspace_and_args


def execute(workspace, args):
    workspace = workspace_and_args(workspace, args, required=("cmd",), allowed=("cmd", "cwd", "timeout"))
    command = string_arg(args, "cmd")
    cwd = workspace.resolve(string_arg(args, "cwd", "."))
    timeout = args.get("timeout", 300)
    if type(timeout) is not int or not 1 <= timeout <= 3600:
        raise ValueError("timeout must be an integer between 1 and 3600 seconds")
    complete = threading.Event()

    def sink(event):
        if event["type"] == "terminal_exit":
            complete.set()

    manager = TerminalManager(sink)
    ident = manager.run(command, str(cwd), timeout=timeout)
    try:
        if not complete.wait(timeout + 12):
            manager.kill(ident)
            complete.wait(8)
            raise TimeoutError("Command did not finish within its cleanup deadline")
    except BaseException:
        manager.kill(ident)
        raise
    result = manager.result(ident)
    if result["exit"] is None:
        raise RuntimeError(result.get("error", "Command could not be started"))
    return {key: result[key] for key in ("exit", "stdout", "stderr", "duration", "timed_out", "cancelled", "truncated", "discarded_chars", "error") if key in result}


run_command = execute
