"""
Run identifier utilities.

Pipeline artifacts are stored in timestamped directories so each raw,
processed, and embedding run is reproducible and independently inspectable.
"""

from __future__ import annotations

from datetime import datetime, timezone


RUN_ID_FORMAT = "%Y%m%dT%H%M%SZ"


def utc_run_id() -> str:
    """
    Return a filesystem-safe UTC timestamp suitable for artifact directories.

    Example:
        20260506T184500Z
    """
    return datetime.now(timezone.utc).strftime(RUN_ID_FORMAT)


def utc_now_iso() -> str:
    """
    Return the current UTC time in ISO-8601 format for manifest metadata.
    """
    return datetime.now(timezone.utc).isoformat()


def is_run_id(value: str) -> bool:
    """
    Return True if value looks like a pipeline run identifier.

    This validates the timestamp shape but does not verify that the date is
    semantically valid.
    """
    if len(value) != 16:
        return False

    return (
        value[0:8].isdigit()
        and value[8] == "T"
        and value[9:15].isdigit()
        and value[15] == "Z"
    )