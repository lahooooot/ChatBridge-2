"""Tool argument validation and workspace coercion."""
from ..safety import Workspace


def workspace_and_args(workspace, args, *, required=(), allowed=()):
    if not isinstance(args, dict):
        raise ValueError("Tool args must be a JSON object")
    missing = [name for name in required if name not in args]
    if missing:
        raise ValueError("Missing required tool arguments: " + ", ".join(missing))
    unknown = set(args) - set(allowed)
    if unknown:
        raise ValueError("Unknown tool arguments: " + ", ".join(sorted(unknown)))
    return workspace if isinstance(workspace, Workspace) else Workspace(workspace)


def string_arg(args, name, default=None):
    value = args.get(name, default)
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return value
