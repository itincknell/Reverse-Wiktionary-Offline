"""
Glottolog lookup and matching helpers.

The lookup is intentionally conservative. Exact name/alias matches are accepted
directly; fuzzy matches are surfaced with confidence so low-confidence cases can
be reviewed and added to the project override map.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable


TOKEN_RE = re.compile(r"[^a-z0-9]+")
HISTORICAL_PREFIX_TOKENS = {
    "ancient",
    "classical",
    "early",
    "middle",
    "old",
}
GENERIC_REVIEW_TOKENS = {
    "ancient",
    "central",
    "classical",
    "creole",
    "early",
    "east",
    "eastern",
    "far",
    "greater",
    "high",
    "late",
    "lesser",
    "low",
    "lower",
    "middle",
    "modern",
    "near",
    "new",
    "north",
    "northeast",
    "northeastern",
    "northwest",
    "northwestern",
    "northern",
    "old",
    "pidgin",
    "proto",
    "south",
    "southeast",
    "southeastern",
    "southwest",
    "southwestern",
    "southern",
    "standard",
    "upper",
    "west",
    "western",
}
TOKEN_ALIASES = {
    "apabhramsa": "apabhramsic",
    "arawak": "arawakan",
    "bikol": "bicolano",
    "bontoc": "bontok",
    "luxembourgish": "luxemburgish",
    "mordvinic": "mordvin",
    "punjabi": "panjabi",
    "rhine": "rhenish",
    "sami": "saami",
    "tocharian": "tokharian",
    "yaghnobi": "yagnobi",
}
EXCLUDED_REVIEW_FAMILIES = {
    "Artificial Language",
    "Bookkeeping",
    "Speech Register",
    "Unattested",
    "Unclassifiable",
}
FAMILY_REVIEW_TOKENS = {
    "arabic",
    "aramaic",
    "armenian",
    "assamese",
    "batak",
    "bikol",
    "creole",
    "dutch",
    "franconian",
    "french",
    "gaelic",
    "german",
    "greek",
    "guarani",
    "hmong",
    "inuktitut",
    "kriol",
    "nahuatl",
    "norse",
    "norwegian",
    "pidgin",
    "prakrit",
    "romani",
    "sami",
    "scots",
    "turkic",
    "yiddish",
    "zapotec",
}


@dataclass(frozen=True)
class GlottologLanguoid:
    """One Glottolog languoid row plus its classification path."""

    glottocode: str
    name: str
    level: str
    iso639p3code: str | None
    family_id: str | None
    classification_ids: list[str]
    classification_names: list[str]

    @property
    def family(self) -> str:
        if self.classification_names:
            return self.classification_names[0]
        return "Isolates"

    @property
    def branch(self) -> str:
        if len(self.classification_names) > 1:
            return self.classification_names[1]
        return "Other"


@dataclass(frozen=True)
class MatchResult:
    """Result of matching one Wiktionary language label to Glottolog."""

    label: str
    match_method: str
    confidence: float
    languoid: GlottologLanguoid | None
    candidate_name: str | None = None


class GlottologLookup:
    """Lookup table for Glottolog language, family, and dialect rows."""

    def __init__(self, languoids: Iterable[GlottologLanguoid]) -> None:
        self.languoids = list(languoids)
        self.normalized_languoids = [
            (languoid, normalize_label(languoid.name))
            for languoid in self.languoids
        ]
        self.by_name: dict[str, list[GlottologLanguoid]] = {}
        self.by_compact_name: dict[str, list[GlottologLanguoid]] = {}
        self.by_token_sort_name: dict[str, list[GlottologLanguoid]] = {}
        self.by_alias_name: dict[str, list[GlottologLanguoid]] = {}
        self.by_compact_alias_name: dict[str, list[GlottologLanguoid]] = {}
        self.by_token_sort_alias_name: dict[str, list[GlottologLanguoid]] = {}
        self.by_first_char: dict[str, list[tuple[GlottologLanguoid, str]]] = {}
        self.by_meaningful_token: dict[str, list[tuple[GlottologLanguoid, str]]] = {}
        self.by_glottocode = {
            languoid.glottocode: languoid
            for languoid in self.languoids
        }

        for languoid, normalized_name in self.normalized_languoids:
            self.by_name.setdefault(normalized_name, []).append(languoid)
            self.by_compact_name.setdefault(compact_label(normalized_name), []).append(languoid)
            self.by_token_sort_name.setdefault(token_sort_label(normalized_name), []).append(languoid)
            alias_name = alias_label(normalized_name)
            self.by_alias_name.setdefault(alias_name, []).append(languoid)
            self.by_compact_alias_name.setdefault(compact_label(alias_name), []).append(languoid)
            self.by_token_sort_alias_name.setdefault(token_sort_label(alias_name), []).append(languoid)
            if normalized_name:
                self.by_first_char.setdefault(normalized_name[0], []).append((languoid, normalized_name))
            for token in meaningful_review_tokens(set(alias_name.split())):
                self.by_meaningful_token.setdefault(token, []).append((languoid, normalized_name))

    @classmethod
    def from_csv(cls, path: Path) -> "GlottologLookup":
        rows = read_glottolog_csv(path)
        names_by_id = {
            row["id"]: row["name"]
            for row in rows
            if row.get("id") and row.get("name")
        }
        rows_by_id = {
            row["id"]: row
            for row in rows
            if row.get("id")
        }

        languoids: list[GlottologLanguoid] = []

        for row in rows:
            if row.get("level") not in {"language", "family", "dialect"}:
                continue

            classification_ids = ancestor_ids(row, rows_by_id)
            classification_names = [
                names_by_id[classification_id]
                for classification_id in classification_ids
                if classification_id in names_by_id
            ]
            languoids.append(
                GlottologLanguoid(
                    glottocode=row["id"],
                    name=row["name"],
                    level=row["level"],
                    iso639p3code=none_if_empty(row.get("iso639P3code")),
                    family_id=none_if_empty(row.get("family_id")),
                    classification_ids=classification_ids,
                    classification_names=classification_names,
                )
            )

        return cls(languoids)

    def match_glottocode(self, label: str, glottocode: str) -> MatchResult:
        languoid = self.by_glottocode.get(glottocode)
        if languoid is None:
            raise ValueError(f"Glottocode not found in Glottolog data: {glottocode}")
        return MatchResult(
            label=label,
            match_method="override",
            confidence=1.0,
            languoid=languoid,
            candidate_name=languoid.name,
        )

    def match(
        self,
        label: str,
        *,
        auto_threshold: float = 0.96,
        review_threshold: float = 0.75,
    ) -> MatchResult:
        normalized = normalize_label(label)
        exact = self.by_name.get(normalized)

        if exact:
            return MatchResult(
                label=label,
                match_method="exact_name",
                confidence=1.0,
                languoid=prefer_languoid(exact),
                candidate_name=prefer_languoid(exact).name,
            )

        compact_exact = self.by_compact_name.get(compact_label(normalized))
        if compact_exact:
            preferred = prefer_languoid(compact_exact)
            return MatchResult(
                label=label,
                match_method="compact_name",
                confidence=1.0,
                languoid=preferred,
                candidate_name=preferred.name,
            )

        token_sort_exact = self.by_token_sort_name.get(token_sort_label(normalized))
        if token_sort_exact:
            preferred = prefer_languoid(token_sort_exact)
            return MatchResult(
                label=label,
                match_method="token_sort_name",
                confidence=1.0,
                languoid=preferred,
                candidate_name=preferred.name,
            )

        aliased = alias_label(normalized)
        if aliased != normalized:
            alias_exact = self.by_alias_name.get(aliased)
            if alias_exact:
                preferred = prefer_languoid(alias_exact)
                return MatchResult(
                    label=label,
                    match_method="alias_name",
                    confidence=1.0,
                    languoid=preferred,
                    candidate_name=preferred.name,
                )

            alias_compact_exact = self.by_compact_alias_name.get(compact_label(aliased))
            if alias_compact_exact:
                preferred = prefer_languoid(alias_compact_exact)
                return MatchResult(
                    label=label,
                    match_method="alias_compact_name",
                    confidence=1.0,
                    languoid=preferred,
                    candidate_name=preferred.name,
                )

            alias_token_sort_exact = self.by_token_sort_alias_name.get(token_sort_label(aliased))
            if alias_token_sort_exact:
                preferred = prefer_languoid(alias_token_sort_exact)
                return MatchResult(
                    label=label,
                    match_method="alias_token_sort_name",
                    confidence=1.0,
                    languoid=preferred,
                    candidate_name=preferred.name,
                )

        best_languoid: GlottologLanguoid | None = None
        best_score = 0.0

        for languoid, normalized_name in self.fuzzy_candidates(normalized):
            score = SequenceMatcher(
                None,
                normalized,
                normalized_name,
            ).ratio()
            if score > best_score:
                best_score = score
                best_languoid = languoid

        if (
            best_languoid
            and best_score >= auto_threshold
            and allow_fuzzy_auto(normalized, best_languoid)
        ):
            return MatchResult(
                label=label,
                match_method="fuzzy_auto",
                confidence=round(best_score, 4),
                languoid=best_languoid,
                candidate_name=best_languoid.name,
            )

        review_candidates: list[tuple[GlottologLanguoid, float]] = []
        if best_languoid is not None:
            review_candidates.append((best_languoid, best_score))
        prefix_review = self.prefix_review_candidate(normalized)
        if prefix_review is not None:
            review_candidates.append(prefix_review)

        token_review = self.token_review_candidate(normalized)
        if token_review is not None:
            review_candidates.append(token_review)

        review_languoid, review_score = best_allowed_review_candidate(
            normalized_label=normalized,
            candidates=review_candidates,
            review_threshold=review_threshold,
        )
        if review_languoid is not None:
            return MatchResult(
                label=label,
                match_method="fuzzy_review",
                confidence=round(review_score, 4),
                languoid=review_languoid,
                candidate_name=review_languoid.name,
            )

        return MatchResult(
            label=label,
            match_method="unmatched",
            confidence=round(best_score, 4),
            languoid=None,
            candidate_name=best_languoid.name if best_languoid else None,
        )

    def fuzzy_candidates(self, normalized_label: str) -> list[tuple[GlottologLanguoid, str]]:
        if not normalized_label:
            return []
        return self.by_first_char.get(normalized_label[0], self.normalized_languoids)

    def prefix_review_candidate(
        self,
        normalized_label: str,
    ) -> tuple[GlottologLanguoid, float] | None:
        tokens = normalized_label.split()
        if len(tokens) < 2:
            return None

        if tokens[0] == "proto":
            remainder = " ".join(tokens[1:])
        elif tokens[0] in HISTORICAL_PREFIX_TOKENS:
            remainder = " ".join(tokens[1:])
        else:
            return None

        aliased_remainder = alias_label(remainder)
        for candidate_key in {
            remainder,
            aliased_remainder,
            token_sort_label(remainder),
            token_sort_label(aliased_remainder),
        }:
            candidates = (
                self.by_name.get(candidate_key)
                or self.by_alias_name.get(candidate_key)
                or self.by_token_sort_name.get(candidate_key)
                or self.by_token_sort_alias_name.get(candidate_key)
            )
            if candidates:
                return prefer_languoid(candidates), 1.0
        return None

    def token_review_candidate(
        self,
        normalized_label: str,
    ) -> tuple[GlottologLanguoid, float] | None:
        aliased_label = alias_label(normalized_label)
        label_tokens = set(aliased_label.split())
        meaningful_label_tokens = meaningful_review_tokens(label_tokens)
        if not meaningful_label_tokens:
            return None

        best_languoid: GlottologLanguoid | None = None
        best_score = 0.0

        candidates_by_code: dict[str, tuple[GlottologLanguoid, str]] = {}
        for token in meaningful_label_tokens:
            for languoid, normalized_name in self.by_meaningful_token.get(token, []):
                candidates_by_code[languoid.glottocode] = (languoid, normalized_name)

        for languoid, normalized_name in candidates_by_code.values():
            aliased_name = alias_label(normalized_name)
            name_tokens = set(aliased_name.split())
            meaningful_name_tokens = meaningful_review_tokens(name_tokens)
            shared = meaningful_label_tokens & meaningful_name_tokens
            if not shared:
                continue

            label_contains_name = name_tokens <= label_tokens
            name_contains_label = label_tokens <= name_tokens
            shares_family_token = bool(shared & FAMILY_REVIEW_TOKENS)
            if not (label_contains_name or name_contains_label or shares_family_token or len(shared) >= 2):
                continue

            token_score = len(shared) / max(len(meaningful_label_tokens), len(meaningful_name_tokens))
            sequence_score = SequenceMatcher(None, normalized_label, normalized_name).ratio()
            score = max(sequence_score, token_score)
            if shares_family_token:
                score = max(score, 0.8)
                if label_contains_name:
                    score = max(score, 0.84)
            if len(shared) >= 2:
                score = max(score, 0.82)
            if name_contains_label and shared:
                score = max(score, 0.82)

            if score > best_score:
                best_score = score
                best_languoid = languoid

        if best_languoid is None:
            return None
        return best_languoid, best_score


def read_glottolog_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def ancestor_ids(row: dict[str, str], rows_by_id: dict[str, dict[str, str]]) -> list[str]:
    ids: list[str] = []
    current_id = none_if_empty(row.get("parent_id"))
    seen: set[str] = set()

    while current_id and current_id not in seen:
        seen.add(current_id)
        parent = rows_by_id.get(current_id)
        if parent is None:
            break
        ids.append(current_id)
        current_id = none_if_empty(parent.get("parent_id"))

    return list(reversed(ids))


def normalize_label(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = value.lower()
    value = re.sub(r"\([^)]*\)", " ", value)
    value = TOKEN_RE.sub(" ", value)
    return " ".join(value.split())


def token_sort_label(normalized_label: str) -> str:
    return " ".join(sorted(normalized_label.split()))


def compact_label(normalized_label: str) -> str:
    return normalized_label.replace(" ", "")


def alias_label(normalized_label: str) -> str:
    return " ".join(
        TOKEN_ALIASES.get(token, token)
        for token in normalized_label.split()
    )


def meaningful_review_tokens(tokens: set[str]) -> set[str]:
    return {
        token
        for token in tokens
        if len(token) >= 4 and token not in GENERIC_REVIEW_TOKENS
    }


def allow_fuzzy_auto(normalized_label: str, languoid: GlottologLanguoid) -> bool:
    tokens = normalized_label.split()
    if not tokens:
        return False
    if tokens[0] == "proto" or tokens[0] in HISTORICAL_PREFIX_TOKENS:
        return False
    if len(normalized_label) <= 5:
        return False
    return has_meaningful_overlap(normalized_label, normalize_label(languoid.name))


def allow_fuzzy_review(
    normalized_label: str,
    languoid: GlottologLanguoid,
    score: float,
) -> bool:
    normalized_name = normalize_label(languoid.name)
    if has_meaningful_overlap(normalized_label, normalized_name):
        return True

    tokens = normalized_label.split()
    name_tokens = normalized_name.split()
    if len(tokens) == 1 and len(name_tokens) == 1:
        if len(normalized_label) >= 6:
            return score >= 0.88

    return False


def best_allowed_review_candidate(
    *,
    normalized_label: str,
    candidates: list[tuple[GlottologLanguoid, float]],
    review_threshold: float,
) -> tuple[GlottologLanguoid | None, float]:
    allowed = [
        (languoid, score)
        for languoid, score in candidates
        if (
            score >= review_threshold
            and reviewable_languoid(languoid)
            and allow_fuzzy_review(normalized_label, languoid, score)
        )
    ]
    if not allowed:
        return None, 0.0
    return max(
        allowed,
        key=lambda item: (
            token_overlap_score(normalized_label, normalize_label(item[0].name)),
            item[1],
            -languoid_level_rank(item[0]),
            item[0].name.casefold(),
        ),
    )


def token_overlap_score(left: str, right: str) -> float:
    left_tokens = meaningful_review_tokens(set(alias_label(left).split()))
    right_tokens = meaningful_review_tokens(set(alias_label(right).split()))
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / max(len(left_tokens), len(right_tokens))


def has_meaningful_overlap(left: str, right: str) -> bool:
    left_tokens = meaningful_review_tokens(set(alias_label(left).split()))
    right_tokens = meaningful_review_tokens(set(alias_label(right).split()))
    return bool(left_tokens & right_tokens)


def reviewable_languoid(languoid: GlottologLanguoid) -> bool:
    family = languoid.name if languoid.level == "family" and not languoid.classification_names else languoid.family
    return family not in EXCLUDED_REVIEW_FAMILIES


def languoid_level_rank(languoid: GlottologLanguoid) -> int:
    return {
        "family": 0,
        "language": 1,
        "dialect": 2,
    }.get(languoid.level, 3)


def none_if_empty(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def prefer_languoid(candidates: list[GlottologLanguoid]) -> GlottologLanguoid:
    level_order = {"language": 0, "family": 1, "dialect": 2}
    return sorted(
        candidates,
        key=lambda candidate: (
            level_order.get(candidate.level, 3),
            not bool(candidate.classification_names),
            candidate.name,
        ),
    )[0]
