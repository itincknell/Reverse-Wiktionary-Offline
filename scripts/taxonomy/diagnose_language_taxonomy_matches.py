#!/usr/bin/env python3

"""Diagnose why selected Wiktionary language labels do or do not match Glottolog."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.taxonomy.build_language_taxonomy import display_branch, display_family
from src.taxonomy.glottolog_lookup import (
    GlottologLookup,
    meaningful_review_tokens,
    normalize_label,
    token_sort_label,
)


DEFAULT_LABELS = [
    "Kiautschou German Pidgin",
    "Volga German",
    "Zipser German",
    "East Franconian",
    "Rhine Franconian",
]
DEFAULT_AUTO_THRESHOLD = 0.96
DEFAULT_REVIEW_THRESHOLD = 0.75


@dataclass(frozen=True)
class CandidateScore:
    score: float
    normalized_name: str
    languoid: Any


def main() -> None:
    args = parse_args()
    lookup = GlottologLookup.from_csv(args.glottolog_csv)
    overrides = load_json(args.overrides) if args.overrides.exists() else {}
    rows_by_label = load_rows_by_label(args.serving_metadata)

    labels = args.labels or DEFAULT_LABELS
    diagnostics = [
        diagnose_label(
            label=label,
            lookup=lookup,
            overrides=overrides,
            rows=rows_by_label.get(label),
            top=args.top,
            auto_threshold=args.auto_threshold,
            review_threshold=args.review_threshold,
        )
        for label in labels
    ]

    print(json.dumps(diagnostics, ensure_ascii=False, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "labels",
        nargs="*",
        help="Language labels to diagnose. Defaults to the known Germanic misses.",
    )
    parser.add_argument(
        "--glottolog-csv",
        type=Path,
        default=Path("data/reference/glottolog/5.3/glottolog_languoid.csv"),
    )
    parser.add_argument(
        "--serving-metadata",
        type=Path,
        default=Path("data/processed/20260518T191021Z/serving_metadata.json"),
    )
    parser.add_argument(
        "--overrides",
        type=Path,
        default=Path("src/taxonomy/language_taxonomy_overrides.json"),
    )
    parser.add_argument("--top", type=int, default=8)
    parser.add_argument("--auto-threshold", type=float, default=DEFAULT_AUTO_THRESHOLD)
    parser.add_argument("--review-threshold", type=float, default=DEFAULT_REVIEW_THRESHOLD)
    return parser.parse_args()


def diagnose_label(
    *,
    label: str,
    lookup: GlottologLookup,
    overrides: dict[str, Any],
    rows: int | None,
    top: int,
    auto_threshold: float,
    review_threshold: float,
) -> dict[str, Any]:
    normalized = normalize_label(label)
    override = overrides.get(label)
    exact_candidates = lookup.by_name.get(normalized, [])
    match = lookup.match(
        label,
        auto_threshold=auto_threshold,
        review_threshold=review_threshold,
    )
    top_candidates = top_fuzzy_candidates(
        label=label,
        lookup=lookup,
        limit=top,
    )
    token_sorted = token_sort_label(normalized)
    token_sort_matches = [
        languoid
        for languoid in lookup.languoids
        if token_sort_label(normalize_label(languoid.name)) == token_sorted
    ]
    token_subset_candidates = top_token_subset_candidates(
        label=label,
        lookup=lookup,
        limit=top,
    )
    token_review_candidate = lookup.token_review_candidate(normalized)

    best_score = top_candidates[0].score if top_candidates else 0.0
    return {
        "label": label,
        "rows": rows,
        "normalized_label": normalized,
        "token_sorted_label": token_sorted,
        "override": summarize_override(override),
        "exact_match_count": len(exact_candidates),
        "token_sort_match_count": len(token_sort_matches),
        "matcher_result": {
            "method": match.match_method,
            "confidence": match.confidence,
            "candidate_name": match.candidate_name,
            "reject_reason": reject_reason(
                exact_match_count=len(exact_candidates),
                token_sort_match_count=len(token_sort_matches),
                best_score=best_score,
                auto_threshold=auto_threshold,
                review_threshold=review_threshold,
            ),
        },
        "label_features": label_features(label),
        "meaningful_review_tokens": sorted(meaningful_review_tokens(set(normalized.split()))),
        "diagnosis": diagnose_failure_mode(
            exact_match_count=len(exact_candidates),
            token_sort_matches=token_sort_matches,
            top_candidates=top_candidates,
            label=label,
        ),
        "token_review_candidate": (
            summarize_token_review_candidate(token_review_candidate)
            if token_review_candidate is not None
            else None
        ),
        "token_sort_matches": [
            summarize_languoid(languoid)
            for languoid in token_sort_matches[:top]
        ],
        "token_subset_candidates": [
            summarize_candidate(candidate)
            for candidate in token_subset_candidates
        ],
        "top_candidates": [
            summarize_candidate(candidate)
            for candidate in top_candidates
        ],
    }


def top_fuzzy_candidates(
    *,
    label: str,
    lookup: GlottologLookup,
    limit: int,
) -> list[CandidateScore]:
    normalized = normalize_label(label)
    scores = [
        CandidateScore(
            score=SequenceMatcher(
                None,
                normalized,
                normalize_label(languoid.name),
            ).ratio(),
            normalized_name=normalize_label(languoid.name),
            languoid=languoid,
        )
        for languoid in lookup.languoids
    ]
    return sorted(
        scores,
        key=lambda item: (
            -item.score,
            item.languoid.name.casefold(),
            item.languoid.glottocode,
        ),
    )[:limit]


def top_token_subset_candidates(
    *,
    label: str,
    lookup: GlottologLookup,
    limit: int,
) -> list[CandidateScore]:
    label_tokens = set(normalize_label(label).split())
    candidates = []

    for languoid in lookup.languoids:
        normalized_name = normalize_label(languoid.name)
        name_tokens = set(normalized_name.split())
        if not label_tokens or not name_tokens:
            continue
        if label_tokens <= name_tokens or name_tokens <= label_tokens:
            candidates.append(
                CandidateScore(
                    score=SequenceMatcher(None, normalize_label(label), normalized_name).ratio(),
                    normalized_name=normalized_name,
                    languoid=languoid,
                )
            )

    return sorted(
        candidates,
        key=lambda item: (
            -token_overlap(set(normalize_label(label).split()), set(item.normalized_name.split())),
            -item.score,
            item.languoid.name.casefold(),
            item.languoid.glottocode,
        ),
    )[:limit]


def summarize_candidate(candidate: CandidateScore) -> dict[str, Any]:
    languoid = candidate.languoid
    summary = summarize_languoid(languoid)
    summary.update(
        {
            "normalized_name": candidate.normalized_name,
            "score": round(candidate.score, 4),
        }
    )
    return summary


def summarize_token_review_candidate(candidate: tuple[Any, float]) -> dict[str, Any]:
    languoid, score = candidate
    summary = summarize_languoid(languoid)
    summary["score"] = round(score, 4)
    return summary


def summarize_languoid(languoid: Any) -> dict[str, Any]:
    family = display_family(languoid)
    return {
        "name": languoid.name,
        "glottocode": languoid.glottocode,
        "level": languoid.level,
        "family": family,
        "branch": display_branch(family, languoid.classification_names),
        "path": languoid.classification_names,
    }


def reject_reason(
    *,
    exact_match_count: int,
    token_sort_match_count: int,
    best_score: float,
    auto_threshold: float,
    review_threshold: float,
) -> str | None:
    if exact_match_count:
        return None
    if token_sort_match_count:
        return None
    if best_score >= auto_threshold:
        return None
    if best_score >= review_threshold:
        return "No exact normalized Glottolog name; best fuzzy score reaches review threshold only."
    return "No exact normalized Glottolog name; best fuzzy score is below review threshold."


def diagnose_failure_mode(
    *,
    exact_match_count: int,
    token_sort_matches: list[Any],
    top_candidates: list[CandidateScore],
    label: str,
) -> str:
    if exact_match_count:
        return "Exact normalized Glottolog name exists; current matcher should classify this label."

    if token_sort_matches:
        return "Same normalized tokens exist in Glottolog in a different order; token-sort matching should classify this label."

    best = top_candidates[0] if top_candidates else None
    if not best:
        return "No Glottolog candidates were available."

    label_tokens = set(normalize_label(label).split())
    best_tokens = set(best.normalized_name.split())
    if label_tokens & best_tokens and best.languoid.family == "Pidgin":
        return "Best candidate is a Pidgin-family Glottolog row, but the fuzzy score is below review threshold."
    if "franconian" in label_tokens:
        return "Best candidates are Germanic Franconian rows with extra or spelling-different qualifiers; current matcher has no synonym/parent-family rule."
    if "german" in label_tokens:
        return "Best candidates are Germanic rows, but the specific Wiktionary variety has no exact Glottolog name and fuzzy score is below review threshold."
    return "No exact match and best fuzzy score is below the configured threshold."


def label_features(label: str) -> dict[str, bool]:
    normalized = normalize_label(label)
    tokens = set(normalized.split())
    return {
        "contains_german": "german" in tokens,
        "contains_pidgin": "pidgin" in tokens,
        "contains_creole": "creole" in tokens,
        "contains_franconian": "franconian" in tokens,
        "contains_saxon": "saxon" in tokens,
    }


def token_overlap(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def summarize_override(override: Any) -> dict[str, Any] | None:
    if not isinstance(override, dict):
        return None
    return {
        "family": override.get("family"),
        "branch": override.get("branch") or override.get("subfamily"),
        "glottocode": override.get("glottocode"),
        "reason": override.get("reason"),
    }


def load_rows_by_label(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}

    metadata = load_json(path)
    rows_by_label = {}
    for item in metadata.get("languages", []):
        if not isinstance(item, dict):
            continue
        label = item.get("lang")
        if isinstance(label, str):
            rows_by_label[label] = int(item.get("rows") or 0)
    return rows_by_label


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
