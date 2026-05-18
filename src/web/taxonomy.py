"""
Load and shape language taxonomy data for the web filter tree.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def load_language_taxonomy(path: str | Path, fallback_languages: list[str]) -> dict[str, Any]:
    """
    Return a stable tree structure for the language filter UI.

    The taxonomy artifact is optional at runtime so the web app can still start
    against a Qdrant collection before the taxonomy sidecar has been staged.
    """
    taxonomy_path = Path(path)
    if taxonomy_path.exists():
        return normalize_taxonomy(json.loads(taxonomy_path.read_text(encoding="utf-8")))

    return flat_taxonomy(fallback_languages)


def normalize_taxonomy(raw: dict[str, Any]) -> dict[str, Any]:
    families = []
    all_label_set = {
        str(language.get("label") or "").strip()
        for language in raw.get("languages", [])
        if str(language.get("label") or "").strip()
    }

    for family_index, raw_family in enumerate(raw.get("tree", [])):
        family_name = str(raw_family.get("family") or "Other")
        family_id = stable_id("family", family_name, family_index)
        branches = []

        for branch_index, raw_branch in enumerate(raw_family.get("branches", [])):
            branch_name = str(raw_branch.get("branch") or "Other")
            branch_id = stable_id("branch", family_name, branch_name, branch_index)
            languages = [
                language_node(language, family_id, branch_id, language_index)
                for language_index, language in enumerate(raw_branch.get("languages", []))
            ]
            all_label_set.update(language["label"] for language in languages if language["label"])
            branches.append(
                {
                    "id": branch_id,
                    "label": branch_name,
                    "family_id": family_id,
                    "languages": languages,
                }
            )

        families.append(
            {
                "id": family_id,
                "label": family_name,
                "sort_rows": int(raw_family.get("rows") or 0),
                "branches": branches,
            }
        )

    families.sort(key=lambda item: (-item["sort_rows"], item["label"].casefold()))
    all_labels = sorted(all_label_set, key=str.casefold)
    return {
        "families": families,
        "all_languages": language_nodes_from_labels(all_labels),
    }


def flat_taxonomy(languages: list[str]) -> dict[str, Any]:
    family_id = stable_id("family", "Languages", 0)
    branch_id = stable_id("branch", "Languages", "All", 0)
    sorted_languages = sorted(languages, key=str.casefold)
    language_nodes = [
        language_node_from_label(label, index, family_id=family_id, branch_id=branch_id)
        for index, label in enumerate(sorted_languages)
    ]
    return {
        "families": [
            {
                "id": family_id,
                "label": "Languages",
                "sort_rows": 0,
                "branches": [
                    {
                        "id": branch_id,
                        "label": "All",
                        "family_id": family_id,
                        "languages": language_nodes,
                    }
                ],
            }
        ],
        "all_languages": language_nodes_from_labels(sorted_languages),
    }


def language_node(
    language: dict[str, Any],
    family_id: str,
    branch_id: str,
    language_index: int,
) -> dict[str, str]:
    label = str(language.get("label") or "")
    return {
        "id": stable_id("language", family_id, branch_id, label, language_index),
        "label": label,
        "family_id": family_id,
        "branch_id": branch_id,
    }


def stable_id(*parts: object) -> str:
    raw = "::".join(str(part) for part in parts)
    slug = re.sub(r"[^a-z0-9]+", "-", raw.casefold()).strip("-")
    return slug or "item"


def language_nodes_from_labels(labels: list[str]) -> list[dict[str, str]]:
    return [
        language_node_from_label(label, index)
        for index, label in enumerate(labels)
    ]


def language_node_from_label(
    label: str,
    index: int,
    *,
    family_id: str = "",
    branch_id: str = "",
) -> dict[str, str]:
    return {
        "id": stable_id("language", label, index),
        "label": label,
        "family_id": family_id,
        "branch_id": branch_id,
    }
