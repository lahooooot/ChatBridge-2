"""Search bounded text files in a workspace."""
from ._common import string_arg, workspace_and_args


def execute(workspace, args):
    workspace = workspace_and_args(workspace, args, required=("query",), allowed=("query", "path", "regex", "max"))
    return workspace.search_files(string_arg(args, "query"), path=string_arg(args, "path", "."), regex=args.get("regex", False), max=args.get("max", 50))


search_files = execute
