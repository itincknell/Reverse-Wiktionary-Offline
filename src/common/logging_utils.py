"""
Logging and progress helpers for command-line pipeline scripts.

The offline pipeline uses print-based progress reporting. These helpers keep
rates, byte sizes, and periodic progress lines consistent across scripts.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


def format_rate(count: int, elapsed_seconds: float) -> str:
    """
    Format an item/second rate safely.
    """
    if elapsed_seconds <= 0:
        return "0.0/s"

    return f"{count / elapsed_seconds:.1f}/s"


def format_bytes(num_bytes: int) -> str:
    """
    Format bytes using binary units.
    """
    value = float(num_bytes)

    for unit in ["B", "KiB", "MiB", "GiB", "TiB"]:
        if value < 1024 or unit == "TiB":
            return f"{value:.2f} {unit}"
        value /= 1024

    return f"{value:.2f} TiB"


@dataclass
class ProgressTimer:
    """
    Track elapsed time and periodically print progress.

    Example:
        timer = ProgressTimer(progress_every=100_000)
        ...
        if timer.should_print(records):
            timer.print_progress(records=records, rows=rows)
    """

    progress_every: int = 100_000
    start_time: float = field(default_factory=time.perf_counter)

    def elapsed(self) -> float:
        """
        Return elapsed seconds since timer creation.
        """
        return time.perf_counter() - self.start_time

    def should_print(self, count: int) -> bool:
        """
        Return True when a progress message should be printed.
        """
        return self.progress_every > 0 and count > 0 and count % self.progress_every == 0

    def print_progress(
        self,
        *,
        records: int,
        rows: int | None = None,
        bytes_written: int | None = None,
        prefix: str = "[progress]",
    ) -> None:
        """
        Print a standard progress line.
        """
        elapsed = self.elapsed()

        parts = [
            prefix,
            f"records={records:,}",
            f"elapsed={elapsed:.1f}s",
            f"records/s={format_rate(records, elapsed)}",
        ]

        if rows is not None:
            parts.append(f"rows={rows:,}")
            parts.append(f"rows/s={format_rate(rows, elapsed)}")

        if bytes_written is not None:
            parts.append(f"bytes={bytes_written:,}")
            parts.append(f"size={format_bytes(bytes_written)}")

        print(" ".join(parts))
