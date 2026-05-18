#!/usr/bin/env python3

"""
Run lightweight retrieval sanity checks against a Qdrant embedding index.

The script embeds a small set of hand-written reverse-dictionary queries,
queries Qdrant, checks whether expected words appear in the top-k results, and
writes a JSON report for manual inspection.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.common.manifest import write_manifest
from src.common.run_id import utc_now_iso
from src.embeddings.utils.embedding_model import EmbeddingModel, EmbeddingModelConfig


DEFAULT_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_COLLECTION_NAME = "reverse_wiktionary_test"


@dataclass(frozen=True)
class QualityCase:
    """
    One hand-authored query expectation for retrieval sanity checks.
    """

    query: str
    expected_words: list[str]
    lang: str | None = "English"
    pos: str | None = None


DEFAULT_CASES = [
    QualityCase("large mammal with a trunk", ["elephant"], pos="noun"),
    QualityCase("reference book containing word definitions", ["dictionary"], pos="noun"),
    QualityCase("book of synonyms", ["thesaurus"], pos="noun"),
    QualityCase("word formed by combining two words", ["portmanteau"], pos="noun"),
    QualityCase("black bird associated with omens", ["raven"], pos="noun"),
    QualityCase("domesticated feline animal", ["cat"], pos="noun"),
    QualityCase("collection of written pages bound together", ["book"], pos="noun"),
    QualityCase("body of standing water smaller than a lake", ["pond"], pos="noun"),
    QualityCase("meaningless or absurd statement", ["nonsense"], pos="noun"),
    QualityCase("dark color like chocolate or coffee", ["brown"], pos="noun"),
]


def build_filter(case: QualityCase) -> Filter | None:
    """
    Build a Qdrant payload filter from a quality case.
    """
    conditions = []

    if case.lang is not None:
        conditions.append(
            FieldCondition(
                key="lang",
                match=MatchValue(value=case.lang),
            )
        )

    if case.pos is not None:
        conditions.append(
            FieldCondition(
                key="pos",
                match=MatchValue(value=case.pos),
            )
        )

    if not conditions:
        return None

    return Filter(must=conditions)


def load_cases(path: Path | None) -> list[QualityCase]:
    """
    Load quality cases from JSON, or return built-in defaults.

    JSON format:
    [
      {
        "query": "large animal with a trunk",
        "expected_words": ["elephant"],
        "lang": "English",
        "pos": "noun"
      }
    ]
    """
    if path is None:
        return DEFAULT_CASES

    with path.open("r", encoding="utf-8") as f:
        raw_cases = json.load(f)

    cases = []
    for item in raw_cases:
        cases.append(
            QualityCase(
                query=item["query"],
                expected_words=list(item["expected_words"]),
                lang=item.get("lang"),
                pos=item.get("pos"),
            )
        )

    return cases


def normalize_word(value: Any) -> str:
    """
    Normalize a word for case-insensitive exact comparison.
    """
    return str(value).strip().lower()


def evaluate_case(
    *,
    case: QualityCase,
    client: QdrantClient,
    model: EmbeddingModel,
    collection_name: str,
    top_k: int,
) -> dict[str, Any]:
    """
    Run one query and return result details plus hit metrics.
    """
    query_vector = model.encode([case.query], batch_size=1)[0].tolist()
    query_filter = build_filter(case)

    response = client.query_points(
        collection_name=collection_name,
        query=query_vector,
        query_filter=query_filter,
        limit=top_k,
        with_payload=True,
        with_vectors=False,
    )

    results = response.points

    expected = {normalize_word(word) for word in case.expected_words}

    formatted_results = []
    hit_rank = None

    for rank, point in enumerate(results, start=1):
        payload = point.payload or {}
        word = payload.get("word")
        normalized = normalize_word(word)

        if hit_rank is None and normalized in expected:
            hit_rank = rank

        formatted_results.append(
            {
                "rank": rank,
                "score": point.score,
                "word": word,
                "lang": payload.get("lang"),
                "pos": payload.get("pos"),
                "glosses": payload.get("glosses", [])[:5],
                "expansion": payload.get("expansion"),
            }
        )

    return {
        "query": case.query,
        "expected_words": case.expected_words,
        "lang_filter": case.lang,
        "pos_filter": case.pos,
        "hit": hit_rank is not None,
        "hit_rank": hit_rank,
        "top_results": formatted_results,
    }


def summarize(results: list[dict[str, Any]], top_k: int) -> dict[str, Any]:
    """
    Summarize hit-rate metrics across all quality cases.
    """
    total = len(results)
    hits = sum(1 for result in results if result["hit"])

    hit_at_1 = sum(
        1 for result in results if result["hit_rank"] is not None and result["hit_rank"] <= 1
    )
    hit_at_5 = sum(
        1 for result in results if result["hit_rank"] is not None and result["hit_rank"] <= 5
    )
    hit_at_10 = sum(
        1 for result in results if result["hit_rank"] is not None and result["hit_rank"] <= 10
    )

    return {
        "total_cases": total,
        "top_k": top_k,
        "hits": hits,
        "hit_rate": hits / total if total else 0,
        "hit_at_1": hit_at_1,
        "hit_at_5": hit_at_5,
        "hit_at_10": hit_at_10,
        "hit_at_1_rate": hit_at_1 / total if total else 0,
        "hit_at_5_rate": hit_at_5 / total if total else 0,
        "hit_at_10_rate": hit_at_10 / total if total else 0,
    }


def main() -> None:
    """
    CLI entry point for retrieval-quality smoke checks.
    """
    parser = argparse.ArgumentParser(
        description="Evaluate embedding retrieval quality with small sanity-check queries."
    )

    parser.add_argument(
        "--qdrant-url",
        default=os.environ.get("QDRANT_URL", "http://localhost:6333"),
        help="Qdrant URL. Defaults to QDRANT_URL or http://localhost:6333.",
    )

    parser.add_argument(
        "--collection-name",
        default=DEFAULT_COLLECTION_NAME,
        help="Qdrant collection name.",
    )

    parser.add_argument(
        "--model-name",
        default=DEFAULT_MODEL_NAME,
        help="SentenceTransformer model name used for query embeddings.",
    )

    parser.add_argument(
        "--device",
        default="auto",
        choices=["auto", "cpu", "cuda", "mps"],
        help="Embedding device.",
    )

    parser.add_argument(
        "--cases",
        default=None,
        help="Optional JSON file containing quality test cases.",
    )

    parser.add_argument(
        "--top-k",
        type=int,
        default=10,
        help="Number of Qdrant results to inspect per query.",
    )

    parser.add_argument(
        "--output",
        default="data/embeddings/quality_report.json",
        help="Path to output JSON quality report.",
    )

    args = parser.parse_args()

    if args.top_k <= 0:
        raise ValueError("top-k must be positive")

    cases = load_cases(Path(args.cases) if args.cases else None)

    model = EmbeddingModel(
        EmbeddingModelConfig(
            model_name=args.model_name,
            device=args.device,
            normalize_embeddings=True,
        )
    )

    client = QdrantClient(url=args.qdrant_url)

    results = [
        evaluate_case(
            case=case,
            client=client,
            model=model,
            collection_name=args.collection_name,
            top_k=args.top_k,
        )
        for case in cases
    ]

    report = {
        "created_at_utc": utc_now_iso(),
        "qdrant_url": args.qdrant_url,
        "collection_name": args.collection_name,
        "model_name": args.model_name,
        "summary": summarize(results, args.top_k),
        "results": results,
    }

    output_path = Path(args.output)
    write_manifest(output_path, report)

    print("=== Quality Summary ===")
    print(json.dumps(report["summary"], indent=2, ensure_ascii=False))
    print(f"report: {output_path}")

    print("\n=== Top Results By Query ===")
    for result in results:
        status = "HIT" if result["hit"] else "MISS"
        rank = result["hit_rank"] if result["hit_rank"] is not None else "-"

        print()
        print(f"[{status}] {result['query']}")
        print(f"expected: {result['expected_words']}")
        print(f"filters: lang={result['lang_filter']} pos={result['pos_filter']}")
        print(f"hit_rank: {rank}")

        for item in result["top_results"]:
            glosses = item.get("glosses", [])
            first_gloss = glosses[0] if glosses else ""

            print(
                f"  {item['rank']:>2}. "
                f"{item.get('word')} "
                f"({item.get('pos')}, {item.get('lang')}) "
                f"score={item.get('score'):.4f} "
                f"- {first_gloss}"
            )

    print("\n=== Misses ===")
    for result in results:
        if not result["hit"]:
            print(f"- {result['query']} -> expected {result['expected_words']}")


if __name__ == "__main__":
    main()
