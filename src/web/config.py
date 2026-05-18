"""
Environment-driven web serving configuration.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from src.search.schemas import DEFAULT_LIMIT, MAX_LIMIT, QUERY_MAX_CHARS


@dataclass(frozen=True)
class WebSettings:
    """
    Runtime settings shared by web startup and route handlers.
    """

    app_env: str
    collection_name: str
    model_name: str
    model_device: str
    qdrant_url: str
    redis_url: str
    qdrant_hnsw_ef: int
    qdrant_acorn_max_selectivity: float
    search_exact_filtered: bool
    default_limit: int
    max_limit: int
    query_max_chars: int
    session_ttl_seconds: int
    secure_cookies: bool
    log_level: str
    language_taxonomy_path: str
    serving_metadata_path: str


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    return int(value)


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    return float(value)


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes"}


def load_settings() -> WebSettings:
    """
    Load web settings from environment variables.
    """
    app_env = os.getenv("APP_ENV", "development")

    return WebSettings(
        app_env=app_env,
        collection_name=os.getenv("COLLECTION_NAME", "reverse_wiktionary_v1"),
        model_name=os.getenv("MODEL_NAME", "sentence-transformers/all-mpnet-base-v2"),
        model_device=os.getenv("MODEL_DEVICE", "auto"),
        qdrant_url=os.getenv("QDRANT_URL", "http://localhost:6333"),
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        qdrant_hnsw_ef=_int_env("QDRANT_HNSW_EF", 512),
        qdrant_acorn_max_selectivity=_float_env("QDRANT_ACORN_MAX_SELECTIVITY", 1.0),
        search_exact_filtered=_bool_env("SEARCH_EXACT_FILTERED", False),
        default_limit=_int_env("DEFAULT_LIMIT", DEFAULT_LIMIT),
        max_limit=_int_env("MAX_LIMIT", MAX_LIMIT),
        query_max_chars=_int_env("QUERY_MAX_CHARS", QUERY_MAX_CHARS),
        session_ttl_seconds=_int_env("SESSION_TTL_SECONDS", 86_400),
        secure_cookies=_bool_env("SECURE_COOKIES", app_env == "production"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        language_taxonomy_path=os.getenv(
            "LANGUAGE_TAXONOMY_PATH",
            "data/processed/latest/language_taxonomy.json",
        ),
        serving_metadata_path=os.getenv(
            "SERVING_METADATA_PATH",
            "data/processed/latest/serving_metadata.json",
        ),
    )
