"""
Shared utilities for the Reverse Wiktionary pipeline.

The common package contains small helpers used by preprocessing, embedding
generation, indexing, and deployment scripts.

Modules:
    jsonl: JSONL streaming, writing, byte counting, and batching helpers.
    paths: Versioned run directory and latest-symlink helpers.
    run_id: UTC timestamp run identifiers.
    manifest: Manifest loading, writing, and update helpers.
    logging_utils: Lightweight progress and formatting helpers.
"""