"""
Locate Kotlin, TypeScript/TSX, and Rust sources under a project root.

Traversal is **recursive** (full directory tree under ``root``). Only files whose
suffix maps to a supported language are returned; all other files are ignored.
Certain directory names (build caches, dependencies) are skipped entirely.
"""

from __future__ import annotations

import os
from pathlib import Path

SKIP_DIR_NAMES = frozenset(
    {
        ".git",
        ".svn",
        ".hg",
        "node_modules",
        "target",
        "dist",
        "build",
        ".gradle",
        ".venv",
        "__pycache__",
        ".idea",
        ".turbo",
        ".next",
        "venv",
        "vendor",
    },
)

# Path suffix (lower case) -> parser language key used by metrics.
EXTENSION_LANG: dict[str, str] = {
    ".rs": "rust",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".ts": "ts",
    ".tsx": "tsx",
}


def iter_metric_files(root: Path | str) -> list[tuple[Path, str]]:
    """Return every analyzable source file under *root*.

    Walks *root* recursively. Omits directories listed in ``SKIP_DIR_NAMES`` (at
    any depth). Only includes files whose suffix appears in ``EXTENSION_LANG``;
    all other extensions are skipped without error.
    """
    root_path = Path(root).expanduser().resolve()
    files: list[tuple[Path, str]] = []
    for dirpath, dirnames, filenames in os.walk(root_path, topdown=True):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_NAMES]
        base = Path(dirpath)
        for name in filenames:
            p = base / name
            ext = p.suffix.lower()
            lang = EXTENSION_LANG.get(ext)
            if lang:
                files.append((p, lang))
    return files
