"""Persistent local project registry."""
from __future__ import annotations

import copy
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

from .config import _path_lock, _read_object, atomic_json_write
from .gittools import GitTools


def project_id(path) -> str:
    return "project-" + hashlib.sha256(os.path.normcase(str(Path(path).resolve())).encode("utf-8")).hexdigest()[:20]


class ProjectRegistry:
    def __init__(self, base):
        self.base = Path(base).expanduser().resolve()
        self.path = self.base / "projects.json"
        self._lock = _path_lock(self.base)

    def attach(self, path) -> dict:
        if not path:
            raise ValueError("A project directory is required")
        root = Path(path).expanduser().resolve(strict=True)
        if not root.is_dir():
            raise NotADirectoryError(f"Project is not a directory: {root}")
        metadata = GitTools(root).status()
        now = datetime.now(timezone.utc).isoformat()
        project = {"id": project_id(root), "name": root.name or str(root), "path": str(root),
                   "git": metadata.get("is_repo", False), "branch": metadata.get("branch", ""),
                   "updated": now}
        if project["git"]:
            project["git_root"] = metadata.get("repo_root", str(root))
        with self._lock:
            data = _read_object(self.path)
            projects = data.get("projects", [])
            if not isinstance(projects, list):
                raise ValueError("Project registry must contain a projects list")
            existing = next((item for item in projects if item.get("id") == project["id"]), None)
            project["created"] = existing.get("created", now) if existing else now
            projects = [item for item in projects if item.get("id") != project["id"]]
            projects.append(project)
            atomic_json_write(self.path, {"projects": projects})
        return copy.deepcopy(project)

    def list(self) -> list:
        with self._lock:
            data = _read_object(self.path)
            projects = data.get("projects", [])
            if not isinstance(projects, list):
                raise ValueError("Project registry must contain a projects list")
            return copy.deepcopy(projects)
