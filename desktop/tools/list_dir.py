"""List a workspace directory without following directory symlinks."""
from ._common import string_arg, workspace_and_args


def execute(workspace, args):
    workspace = workspace_and_args(workspace, args, required=("path",), allowed=("path", "depth"))
    return workspace.list_dir(string_arg(args, "path"), depth=args.get("depth", 1))


list_dir = execute
