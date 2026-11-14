"""Local tools. Each Workspace tool exports execute(workspace, args); extended
handlers (Git, terminals, HTTP) have signature execute(workspace, args, services)
where services is the live Desktop API object."""
from ._extended import HANDLERS as EXTENDED_HANDLERS
from .list_dir import execute as list_dir
from .read_file import execute as read_file
from .run_command import execute as run_command
from .search_files import execute as search_files
from .write_file import execute as write_file

WORKSPACE_HANDLERS = {
    "read_file": read_file, "write_file": write_file, "list_dir": list_dir,
    "search_files": search_files, "run_command": run_command,
}

TOOL_HANDLERS = {**WORKSPACE_HANDLERS, **EXTENDED_HANDLERS}
TOOLS = TOOL_HANDLERS
TOOL_NAMES = tuple(TOOL_HANDLERS)


def execute(workspace, tool, args, services=None):
    if not isinstance(tool, str) or tool not in TOOL_HANDLERS:
        raise ValueError("Unknown tool. Available tools: " + ", ".join(TOOL_NAMES))
    if tool in EXTENDED_HANDLERS:
        if services is None:
            raise ValueError(f"Tool {tool!r} requires the desktop services object")
        return EXTENDED_HANDLERS[tool](workspace, args, services)
    return TOOL_HANDLERS[tool](workspace, args)


execute_tool = execute
__all__ = ["execute", "execute_tool", "TOOL_HANDLERS", "WORKSPACE_HANDLERS",
           "EXTENDED_HANDLERS", "TOOLS", "TOOL_NAMES", *WORKSPACE_HANDLERS]
