"""
Search orchestration and metrics.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from src.search.encoder import QueryEncoder
from src.search.qdrant_search import QdrantSearchClient
from src.search.schemas import SearchRequest, SearchResponse, SearchTiming


@dataclass(frozen=True)
class SearchService:
    """
    Coordinates query encoding, Qdrant search, and response formatting.
    """

    encoder: QueryEncoder
    qdrant: QdrantSearchClient

    def search(self, request: SearchRequest) -> SearchResponse:
        started = perf_counter()

        embedding_started = perf_counter()
        vector = self.encoder.encode_query(request.query)
        embedding_ms = (perf_counter() - embedding_started) * 1000

        qdrant_started = perf_counter()
        results = self.qdrant.search(
            vector=vector,
            filters=request.filters,
            limit=request.limit + 1,
            offset=request.offset,
        )
        qdrant_ms = (perf_counter() - qdrant_started) * 1000

        has_more = len(results) > request.limit
        page_results = results[: request.limit]
        total_ms = (perf_counter() - started) * 1000

        return SearchResponse(
            query=request.query,
            filters=request.filters,
            limit=request.limit,
            offset=request.offset,
            has_more=has_more,
            timing_ms=SearchTiming(
                embedding=round(embedding_ms, 2),
                qdrant=round(qdrant_ms, 2),
                total=round(total_ms, 2),
            ),
            results=page_results,
        )
