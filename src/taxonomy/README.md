# Taxonomy Modules

This package builds the offline language taxonomy artifacts from processed
serving metadata and Glottolog data.

For build commands and review-workflow operations, see
[scripts/taxonomy/README.md](../../scripts/taxonomy/README.md).

The functional artifact builders are the `build_*.py` modules:

- `build_language_taxonomy.py` creates `language_taxonomy.json`,
  `language_taxonomy_unmatched.json`, and `language_taxonomy_report.json`.
- `build_serving_metadata.py` backfills compact language/POS metadata from
  processed JSONL shards when older processed runs do not already include it.

The matching and override support code was developed with AI assistance during
an iterative taxonomy review workflow. That workflow screened mismatched
language labels, tuned automatic matching behavior, triaged high-value
ambiguous cases, and used AI-assisted web checks for large-corpus languages
with missing or uncertain identifiers.

`glottolog_lookup.py` contains the automatic matching heuristics. Treat changes
there as taxonomy-policy changes and validate them with a full review run before
shipping.

`language_taxonomy_overrides.json` is the curated override ledger used before
automatic matching. Overrides should stay reasoned, explicit, and conservative.
