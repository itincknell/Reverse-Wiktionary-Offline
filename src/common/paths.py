"""
Filesystem path helpers for versioned pipeline artifacts.

The project uses timestamped artifact folders plus a lightweight `latest`
symlink at each stage:

    data/raw/<run_id>/
    data/raw/latest -> <run_id>

    data/processed/<run_id>/
    data/processed/latest -> <run_id>

    data/embeddings/<run_id>/
    data/embeddings/latest -> <run_id>

The symlink is a pointer, not a copy, so it does not duplicate large files.
"""

from __future__ import annotations

from pathlib import Path

from .run_id import is_run_id


def ensure_dir(path: Path) -> Path:
    """
    Create a directory if needed and return the path.
    """
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_run_dirs(root: Path) -> list[Path]:
    """
    Return timestamped run directories under root, sorted ascending.

    Non-run directories and symlinks such as `latest` are ignored.
    """
    if not root.exists():
        return []

    return sorted(
        path
        for path in root.iterdir()
        if path.is_dir() and not path.is_symlink() and is_run_id(path.name)
    )


def latest_run_dir(root: Path) -> Path:
    """
    Return the newest timestamped run directory under root.

    Raises:
        FileNotFoundError: if root contains no timestamped run directories.
    """
    runs = list_run_dirs(root)

    if not runs:
        raise FileNotFoundError(f"No timestamped run directories found under {root}")

    return runs[-1]


def latest_link(root: Path) -> Path:
    """
    Return the conventional latest symlink path for an artifact root.
    """
    return root / "latest"


def update_latest_symlink(root: Path, run_id: str) -> Path:
    """
    Point root/latest at run_id.

    The symlink target is relative so the artifact tree remains movable.
    """
    ensure_dir(root)

    link = latest_link(root)

    if link.exists() or link.is_symlink():
        link.unlink()

    link.symlink_to(run_id)

    return link


def resolve_latest(root: Path) -> Path:
    """
    Resolve root/latest to an existing directory.

    Raises:
        FileNotFoundError: if latest is missing or points to a missing target.
        NotADirectoryError: if latest does not resolve to a directory.
    """
    link = latest_link(root)

    if not link.exists():
        raise FileNotFoundError(f"Latest link not found: {link}")

    resolved = link.resolve()

    if not resolved.is_dir():
        raise NotADirectoryError(f"Latest link does not resolve to a directory: {link}")

    return resolved


def read_latest_run_id(root: Path) -> str:
    """
    Return the run_id currently targeted by root/latest.
    """
    return resolve_latest(root).name


def find_shards(run_dir: Path, pattern: str = "shard_*.jsonl") -> list[Path]:
    """
    Return JSONL shard files from a processed run directory, sorted by name.
    """
    shards = sorted(run_dir.glob(pattern))

    if not shards:
        raise FileNotFoundError(f"No shard files matching {pattern} found in {run_dir}")

    return shards