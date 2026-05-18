"""
Stable search request and response models.

These models define the public `/api/v1/search` contract. Keep field removals
and renames behind a future API version.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from src.common.lexical_schema import ALLOWED_POS


DEFAULT_LIMIT = 25
MAX_LIMIT = 100
QUERY_MAX_CHARS = 500


class SearchFilters(BaseModel):
    """
    Filter values applied to a semantic search.

    Empty lists mean "all values" for the corresponding field.
    """

    langs: list[str] = Field(default_factory=list)
    pos: list[str] = Field(default_factory=list)

    @field_validator("langs", "pos")
    @classmethod
    def clean_values(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()

        for value in values:
            value = " ".join(value.strip().split())
            if not value or value in seen:
                continue
            cleaned.append(value)
            seen.add(value)

        return cleaned

    @field_validator("pos")
    @classmethod
    def validate_pos(cls, values: list[str]) -> list[str]:
        invalid = sorted(set(values) - set(ALLOWED_POS))

        if invalid:
            raise ValueError(f"Unsupported part of speech: {', '.join(invalid)}")

        return values


class SearchRequest(BaseModel):
    """
    Public v1 API search request.

    `offset` supports shallow result browsing for the UI's Load more behavior.
    It should not be treated as an unbounded deep-pagination guarantee.
    """

    query: str = Field(min_length=1, max_length=QUERY_MAX_CHARS)
    langs: list[str] = Field(default_factory=list)
    pos: list[str] = Field(default_factory=list)
    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)
    offset: int = Field(default=0, ge=0)

    @field_validator("query")
    @classmethod
    def clean_query(cls, value: str) -> str:
        return " ".join(value.strip().split())

    @field_validator("langs", "pos")
    @classmethod
    def clean_filter_values(cls, values: list[str]) -> list[str]:
        return SearchFilters.clean_values(values)

    @field_validator("pos")
    @classmethod
    def validate_pos(cls, values: list[str]) -> list[str]:
        return SearchFilters.validate_pos(values)

    @property
    def filters(self) -> SearchFilters:
        return SearchFilters(langs=self.langs, pos=self.pos)


class SearchTiming(BaseModel):
    """
    Millisecond timings for one search request.
    """

    embedding: float
    qdrant: float
    total: float


class SearchResult(BaseModel):
    """
    Normalized search result returned by the stable API and UI renderer.

    The API exposes `score`; the public web UI intentionally hides it.
    """

    word: str
    lang: str
    pos: str
    score: float
    glosses: list[str]
    expansion: str | None = None


class SearchResponse(BaseModel):
    """
    Public v1 API search response.
    """

    query: str
    filters: SearchFilters
    limit: int
    offset: int
    has_more: bool
    timing_ms: SearchTiming
    results: list[SearchResult]
