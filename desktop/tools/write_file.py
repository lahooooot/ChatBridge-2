"""Write or uniquely patch a workspace-confined text file."""
from ._common import string_arg, workspace_and_args


def execute(workspace, args):
    workspace = workspace_and_args(workspace, args, required=("path",), allowed=("path", "content", "search", "replace"))
    if "content" in args:
        if "search" in args or "replace" in args:
            raise ValueError("Use content or search and replace, not both")
        return workspace.write_file(string_arg(args, "path"), content=string_arg(args, "content"))
    if "search" not in args or "replace" not in args:
        raise ValueError("write_file needs content or both search and replace")
    return workspace.write_file(string_arg(args, "path"), search=string_arg(args, "search"), replace=string_arg(args, "replace"))


write_file = execute
