"""
Qdrant filter construction for search requests.
"""

from __future__ import annotations

from qdrant_client.models import FieldCondition, Filter, MatchAny

from src.search.schemas import SearchFilters


def build_qdrant_filter(filters: SearchFilters) -> Filter | None:
    """
    Build a Qdrant filter from language and POS selections.

    Empty filter lists mean no restriction. Values within one field are ORed by
    MatchAny; language and POS filters are ANDed through Filter.must.
    """
    must: list[FieldCondition] = []

    if filters.langs:
        must.append(
            FieldCondition(
                key="lang",
                match=MatchAny(any=filters.langs),
            )
        )

    if filters.pos:
        must.append(
            FieldCondition(
                key="pos",
                match=MatchAny(any=filters.pos),
            )
        )

    if not must:
        return None

    return Filter(must=must)

