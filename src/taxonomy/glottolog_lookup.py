"""
Glottolog lookup and matching helpers.

The lookup is intentionally conservative. Exact name/alias matches are accepted
directly; fuzzy matches are surfaced with confidence so low-confidence cases can
be reviewed and added to the project override map.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable


TOKEN_RE = re.compile(r"[^a-z0-9]+")


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
        self.by_name: dict[str, list[GlottologLanguoid]] = {}
        self.by_glottocode = {
            languoid.glottocode: languoid
            for languoid in self.languoids
        }

        for languoid in self.languoids:
            self.by_name.setdefault(normalize_label(languoid.name), []).append(languoid)

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
        review_threshold: float = 0.88,
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

        best_languoid: GlottologLanguoid | None = None
        best_score = 0.0

        for languoid in self.languoids:
            score = SequenceMatcher(
                None,
                normalized,
                normalize_label(languoid.name),
            ).ratio()
            if score > best_score:
                best_score = score
                best_languoid = languoid

        if best_languoid and best_score >= auto_threshold:
            return MatchResult(
                label=label,
                match_method="fuzzy_auto",
                confidence=round(best_score, 4),
                languoid=best_languoid,
                candidate_name=best_languoid.name,
            )

        if best_languoid and best_score >= review_threshold:
            return MatchResult(
                label=label,
                match_method="fuzzy_review",
                confidence=round(best_score, 4),
                languoid=best_languoid,
                candidate_name=best_languoid.name,
            )

        return MatchResult(
            label=label,
            match_method="unmatched",
            confidence=round(best_score, 4),
            languoid=None,
            candidate_name=best_languoid.name if best_languoid else None,
        )


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
    value = value.lower()
    value = re.sub(r"\([^)]*\)", " ", value)
    value = TOKEN_RE.sub(" ", value)
    return " ".join(value.split())


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
