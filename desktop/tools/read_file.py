"""Read a bounded UTF-8 file, using zero-based line offsets."""
from ._common import string_arg, workspace_and_args


def execute(workspace, args):
    workspace = workspace_and_args(workspace, args, required=("path",), allowed=("path", "offset", "limit"))
    return workspace.read_file(string_arg(args, "path"), offset=args.get("offset", 0), limit=args.get("limit", 2000))


read_file = execute
