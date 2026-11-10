"""The five local tools. Each module exports execute(workspace, args)."""
from .list_dir import execute as list_dir
from .read_file import execute as read_file
from .run_command import execute as run_command
from .search_files import execute as search_files
from .write_file import execute as write_file

TOOL_HANDLERS = {
    "read_file": read_file, "write_file": write_file, "list_dir": list_dir,
    "search_files": search_files, "run_command": run_command,
}
TOOLS = TOOL_HANDLERS
TOOL_NAMES = tuple(TOOL_HANDLERS)


def execute(workspace, tool, args):
    if not isinstance(tool, str) or tool not in TOOL_HANDLERS:
        raise ValueError("Unknown tool. Available tools: " + ", ".join(TOOL_NAMES))
    return TOOL_HANDLERS[tool](workspace, args)


execute_tool = execute
__all__ = ["execute", "execute_tool", "TOOL_HANDLERS", "TOOLS", "TOOL_NAMES", *TOOL_NAMES]
