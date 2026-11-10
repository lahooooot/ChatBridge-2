"""Create a dedicated working folder for a chat without a project."""
from __future__ import annotations

import re
from pathlib import Path, PureWindowsPath

from .project import project_id

_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def create_chat_folder(name, base=None) -> dict:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Chat folder name must be a nonempty string")
    if "\x00" in name or "/" in name or "\\" in name or PureWindowsPath(name).drive or name.strip() in (".", ".."):
        raise ValueError("Chat folder name cannot contain a path or traversal")
    clean = re.sub(r'[<>:"|?*\x00-\x1f]', "_", name.strip()).rstrip(". ")[:100]
    if not clean:
        raise ValueError("Chat folder name contains no usable characters")
    if clean.split(".", 1)[0].upper() in _RESERVED:
        clean = "_" + clean
    root = Path(base).expanduser().resolve() if base is not None else Path.home() / "Documents" / "ChatBridge"
    root.mkdir(parents=True, exist_ok=True)
    root = root.resolve(strict=True)
    for index in range(1, 10001):
        candidate = root / (clean if index == 1 else f"{clean}-{index}")
        try:
            candidate.mkdir(exist_ok=False)
        except FileExistsError:
            continue
        return {"id": project_id(candidate), "name": candidate.name, "path": str(candidate), "git": False, "branch": ""}
    raise FileExistsError("Too many chat folders already use this name")
