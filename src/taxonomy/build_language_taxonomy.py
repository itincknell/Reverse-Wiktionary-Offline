"""
Build a serving language taxonomy from processed serving metadata.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from src.common.run_id import utc_now_iso
from src.taxonomy.glottolog_lookup import GlottologLookup, MatchResult


SPECIAL_FAMILY = "Special"
UNMATCHED_FAMILY = "Unmatched"
EXCLUDED_TREE_FAMILIES = {
    "Artificial Language",
    "Bookkeeping",
    "Special",
    "Speech Register",
    "Unattested",
    "Unclassifiable",
    UNMATCHED_FAMILY,
}
EXCLUDED_TREE_BRANCHES = {
    "Other Indo-European",
}


def main() -> None:
    args = parse_args()
    serving_metadata = load_json(args.serving_metadata)
    overrides = load_json(args.overrides) if args.overrides.exists() else {}
    lookup = GlottologLookup.from_csv(args.glottolog_csv)

    languages = serving_metadata_languages(serving_metadata)
    result = build_taxonomy(
        languages=languages,
        lookup=lookup,
        overrides=overrides,
        glottolog_version=args.glottolog_version,
        processed_run_id=serving_metadata.get("processed_run_id"),
        source_path=args.serving_metadata,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.output_dir / "language_taxonomy.json", result["taxonomy"])
    write_json(args.output_dir / "language_taxonomy_unmatched.json", result["unmatched"])
    write_json(args.output_dir / "language_taxonomy_report.json", result["report"])

    print_summary(result["report"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serving-metadata", required=True, type=Path)
    parser.add_argument("--glottolog-csv", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--overrides",
        type=Path,
        default=Path("src/taxonomy/language_taxonomy_overrides.json"),
    )
    parser.add_argument("--glottolog-version", default="5.3")
    return parser.parse_args()


def build_taxonomy(
    *,
    languages: list[dict[str, Any]],
    lookup: GlottologLookup,
    overrides: dict[str, Any],
    glottolog_version: str,
    processed_run_id: str | None,
    source_path: Path,
) -> dict[str, Any]:
    enriched_languages: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    method_counts: Counter[str] = Counter()

    for language in languages:
        label = language["lang"]
        rows = int(language["rows"])
        override = overrides.get(label)

        if override and override.get("glottocode"):
            match = lookup.match_glottocode(label, override["glottocode"])
            enriched = enrich_match(label=label, rows=rows, match=match)
            enriched = apply_override_fields(enriched, override)
        elif override:
            enriched = apply_override(label=label, rows=rows, override=override)
        else:
            match = lookup.match(label)
            enriched = enrich_match(label=label, rows=rows, match=match)

        method_counts[enriched["match_method"]] += 1
        enriched_languages.append(enriched)

        if enriched["match_method"] in {"unmatched", "fuzzy_review"}:
            unmatched.append(enriched)

    tree_languages = [
        language
        for language in enriched_languages
        if is_selectable_language(language)
    ]
    tree, pruned_tree_languages = build_tree(tree_languages)
    top_families = top_counts(enriched_languages, "family")
    top_unmatched = sorted(
        unmatched,
        key=lambda item: item["rows"],
        reverse=True,
    )[:50]

    report = {
        "version": 1,
        "created_at_utc": utc_now_iso(),
        "processed_run_id": processed_run_id,
        "language_source_path": str(source_path),
        "taxonomy_source": "Glottolog",
        "glottolog_version": glottolog_version,
        "total_languages": len(enriched_languages),
        "matched_languages": sum(
            count
            for method, count in method_counts.items()
            if method not in {"unmatched", "fuzzy_review"}
        ),
        "review_languages": method_counts.get("fuzzy_review", 0),
        "unmatched_languages": method_counts.get("unmatched", 0),
        "tree_languages": len(pruned_tree_languages),
        "excluded_tree_languages": len(enriched_languages) - len(pruned_tree_languages),
        "pruned_line_family_languages": len(tree_languages) - len(pruned_tree_languages),
        "method_counts": dict(sorted(method_counts.items())),
        "top_families": top_families,
        "top_unmatched": top_unmatched,
    }

    taxonomy = {
        "version": 1,
        "created_at_utc": report["created_at_utc"],
        "source": {
            "language_source": "processed serving_metadata.json",
            "processed_run_id": processed_run_id,
            "taxonomy_source": "Glottolog",
            "glottolog_version": glottolog_version,
        },
        "tree": tree,
        "languages": sorted(enriched_languages, key=lambda item: item["label"].casefold()),
    }

    return {
        "taxonomy": taxonomy,
        "unmatched": {
            "version": 1,
            "created_at_utc": report["created_at_utc"],
            "languages": top_unmatched,
        },
        "report": report,
    }


def serving_metadata_languages(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    languages = metadata.get("languages", [])
    if not isinstance(languages, list):
        raise ValueError("serving metadata field 'languages' must be a list")

    parsed: list[dict[str, Any]] = []
    for item in languages:
        if not isinstance(item, dict):
            continue
        label = str(item.get("lang") or "").strip()
        if not label:
            continue
        parsed.append({"lang": label, "rows": int(item.get("rows") or 0)})
    return parsed


def apply_override(label: str, rows: int, override: dict[str, Any]) -> dict[str, Any]:
    family = override.get("family") or SPECIAL_FAMILY
    branch = display_fallback_branch(family, override.get("branch") or override.get("subfamily"))
    path = override.get("path") or [family, branch]

    return {
        "label": label,
        "rows": rows,
        "family": family,
        "branch": branch,
        "path": path,
        "glottocode": override.get("glottocode"),
        "candidate_name": override.get("candidate_name"),
        "match_method": "override",
        "match_confidence": 1.0,
        "selectable": bool(override.get("selectable", True)),
        "note": override.get("reason"),
    }


def apply_override_fields(language: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """
    Apply display overrides while preserving the Glottolog match payload.
    """
    updated = dict(language)
    if override.get("family"):
        updated["family"] = override["family"]
    if override.get("branch") or override.get("subfamily"):
        updated["branch"] = display_fallback_branch(
            updated["family"],
            override.get("branch") or override.get("subfamily"),
        )
    if override.get("path"):
        updated["path"] = override["path"]
    if override.get("reason"):
        updated["note"] = override["reason"]
    if "selectable" in override:
        updated["selectable"] = bool(override["selectable"])
    updated["match_method"] = "override"
    updated["match_confidence"] = 1.0
    return updated


def enrich_match(label: str, rows: int, match: MatchResult) -> dict[str, Any]:
    if match.languoid is None or match.match_method == "fuzzy_review":
        return {
            "label": label,
            "rows": rows,
            "family": UNMATCHED_FAMILY,
            "branch": "Review",
            "path": [],
            "glottocode": None,
            "candidate_name": match.candidate_name,
            "match_method": match.match_method,
            "match_confidence": match.confidence,
            "languoid_level": None,
            "selectable": False,
        }

    family = display_family(match.languoid)

    return {
        "label": label,
        "rows": rows,
        "family": family,
        "branch": display_branch(family, match.languoid.classification_names),
        "path": match.languoid.classification_names,
        "glottocode": match.languoid.glottocode,
        "candidate_name": match.candidate_name,
        "match_method": match.match_method,
        "match_confidence": match.confidence,
        "languoid_level": match.languoid.level,
        "selectable": True,
    }


def display_family(languoid: Any) -> str:
    """
    Return the family bucket used by the browse taxonomy.

    Glottolog root family rows have no parent classification, which otherwise
    makes them look like isolates. For browsing, those rows should become their
    own family buckets; true language isolates remain under `Isolates`.
    """
    if languoid.level == "family" and not languoid.classification_names:
        return languoid.name
    return languoid.family


def display_branch(family: str, path: list[str]) -> str:
    """
    Collapse deep Glottolog paths into recognizable filter branches.

    Glottolog paths are research taxonomy; the UI needs stable, familiar labels.
    This function keeps the family from Glottolog but picks a display branch from
    a curated layer of the path.
    """
    if family == "Indo-European":
        return indo_european_branch(path)

    if len(path) > 1:
        return display_fallback_branch(family, path[1])
    return display_fallback_branch(family, None)


def display_fallback_branch(family: str, branch: str | None) -> str:
    if branch and branch != "Other":
        return branch
    if family == "Isolates":
        return "Language isolate"
    return family


def indo_european_branch(path: list[str]) -> str:
    if "Slavic" in path:
        return "Slavic"
    if "Eastern Baltic" in path or "Western Baltic" in path:
        return "Baltic"
    if "Indo-Aryan" in path:
        return "Indic"
    if "Iranian" in path or "Iranian-Nuristani" in path:
        return "Iranian"

    branch_rules = [
        ("Germanic", "Germanic"),
        ("Italic", "Italic / Romance"),
        ("Romance", "Italic / Romance"),
        ("Balto-Slavic", "Balto-Slavic"),
        ("Graeco-Phrygian", "Hellenic"),
        ("Greek", "Hellenic"),
        ("Armenian", "Armenian"),
        ("Celtic", "Celtic"),
        ("Albanian", "Albanian"),
        ("Anatolian", "Anatolian"),
        ("Tokharian", "Tocharian"),
        ("Tocharian", "Tocharian"),
    ]

    for path_item in path[1:]:
        for marker, branch in branch_rules:
            if marker == path_item:
                return branch

    return "Unclassified Indo-European"


def is_selectable_language(language: dict[str, Any]) -> bool:
    if not language.get("selectable", True):
        return False
    if language["match_method"] in {"unmatched", "fuzzy_review"}:
        return False
    if language["family"] in EXCLUDED_TREE_FAMILIES:
        return False
    if language["branch"] in EXCLUDED_TREE_BRANCHES:
        return False
    if language["branch"].startswith("Unclassified"):
        return False
    return True


def build_tree(languages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Build the browse tree and remove strict one-family/one-branch/one-language lines.

    The flat taxonomy still keeps every language for direct search and
    select-all behavior. The visible tree is only for useful browsing groups,
    so isolated lineages with no real grouping value are pruned from it.
    """
    families: dict[str, dict[str, Any]] = {}

    for language in languages:
        family_name = language["family"]
        branch_name = language["branch"]
        family = families.setdefault(
            family_name,
            {"family": family_name, "rows": 0, "language_count": 0, "branches": {}},
        )
        branch = family["branches"].setdefault(
            branch_name,
            {"branch": branch_name, "rows": 0, "language_count": 0, "languages": []},
        )

        family["rows"] += language["rows"]
        family["language_count"] += 1
        branch["rows"] += language["rows"]
        branch["language_count"] += 1
        branch["languages"].append(compact_language(language))

    tree: list[dict[str, Any]] = []
    retained_labels: set[str] = set()
    for family in families.values():
        branches = list(family["branches"].values())
        if len(branches) == 1 and len(branches[0]["languages"]) == 1:
            continue

        for branch in branches:
            branch["languages"].sort(key=lambda item: item["label"].casefold())
            retained_labels.update(language["label"] for language in branch["languages"])
        branches.sort(key=lambda item: item["branch"].casefold())
        tree.append(
            {
                "family": family["family"],
                "rows": family["rows"],
                "language_count": family["language_count"],
                "branches": branches,
            }
        )

    tree.sort(key=lambda item: (-item["rows"], item["family"].casefold()))
    retained_languages = [
        language
        for language in languages
        if language["label"] in retained_labels
    ]
    return tree, retained_languages


def compact_language(language: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": language["label"],
        "rows": language["rows"],
        "glottocode": language.get("glottocode"),
        "match_method": language["match_method"],
        "match_confidence": language["match_confidence"],
        "path": language.get("path", []),
    }


def top_counts(languages: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    counts: dict[str, dict[str, int]] = defaultdict(lambda: {"rows": 0, "language_count": 0})

    for language in languages:
        value = language[key]
        counts[value]["rows"] += language["rows"]
        counts[value]["language_count"] += 1

    return [
        {"name": name, **value}
        for name, value in sorted(
            counts.items(),
            key=lambda item: (-item[1]["rows"], item[0].casefold()),
        )[:25]
    ]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def print_summary(report: dict[str, Any]) -> None:
    print("=== Language Taxonomy Summary ===")
    print(f"processed run: {report['processed_run_id']}")
    print(f"total languages: {report['total_languages']}")
    print(f"matched: {report['matched_languages']}")
    print(f"review: {report['review_languages']}")
    print(f"unmatched: {report['unmatched_languages']}")
    print("method counts:")
    for method, count in report["method_counts"].items():
        print(f"  {method}: {count}")
    print("top unmatched:")
    for item in report["top_unmatched"][:10]:
        print(
            f"  {item['label']} rows={item['rows']} "
            f"candidate={item.get('candidate_name')} confidence={item['match_confidence']}"
        )


if __name__ == "__main__":
    main()
