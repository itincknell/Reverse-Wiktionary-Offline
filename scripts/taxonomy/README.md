# Taxonomy Scripts

These scripts build optional language metadata for downstream filter trees and
audit reports. They are deliberately separate from the core embedding path:
embeddings and Qdrant indexing only require processed shards, while downstream
consumers can use the taxonomy artifacts when they are available.

## Build Inputs

```text
processed/<run_id>/serving_metadata.json
Glottolog languoid CSV
src/taxonomy/language_taxonomy_overrides.json
```

## Build Outputs

```text
processed/<run_id>/language_taxonomy.json
processed/<run_id>/language_taxonomy_unmatched.json
processed/<run_id>/language_taxonomy_report.json
```

## Normal Build

Build from a local processed metadata file:

```bash
scripts/taxonomy/build_language_taxonomy.sh \
  --serving-metadata data/processed/<run_id>/serving_metadata.json \
  --glottolog-version 5.3
```

Build from Blob and upload the artifacts back to the same processed run:

```bash
scripts/taxonomy/build_language_taxonomy_from_blob.sh \
  --storage-account <account> \
  --container <container> \
  --run-id <run_id> \
  --glottolog-version 5.3 \
  --upload
```

Default matching thresholds are:

```text
auto threshold: 0.96
review threshold: 0.75
```

Automatic matches are selectable taxonomy labels. Review matches are
non-selectable and are emitted into the unmatched/review artifact for inspection.
To tune thresholds or watch review candidates while the build runs:

```bash
scripts/taxonomy/build_language_taxonomy.sh \
  --serving-metadata data/processed/<run_id>/serving_metadata.json \
  --auto-threshold 0.96 \
  --review-threshold 0.75 \
  --stream-reviews
```

## Review Workflow

Use this workflow when a taxonomy rebuild is expensive and the goal is to
minimize both false positives and false negatives before changing overrides.

1. Run sharded experiments over the full language list:

   ```bash
   scripts/taxonomy/taxonomy_review_workflow.py \
     --serving-metadata data/processed/<run_id>/serving_metadata.json \
     --glottolog-csv data/reference/glottolog/5.3/glottolog_languoid.csv \
     --run-id <review_run_id> \
     --config review075:auto=0.96,review=0.75 \
     --config review080:auto=0.96,review=0.80 \
     --config review085:auto=0.96,review=0.85
   ```

2. Prepare review queues and experiment error estimates:

   ```bash
   scripts/taxonomy/prepare_taxonomy_override_review.py \
     --run-root data/taxonomy_review/<review_run_id> \
     --config review080
   ```

3. Inspect high-row review/unmatched cases first, then update the ledger only
   when the decision is clear. Rows below the current review cutoff can be left
   for a later pass.

4. Compile final override candidates only after the chosen matcher behavior is
   visible in experiment outputs and no further tuning pass is expected:

   ```bash
   scripts/taxonomy/compile_taxonomy_override_candidates.py \
     --prep-dir data/taxonomy_review/<review_run_id>/override_prep \
     --min-rows 25
   ```

5. Move accepted candidates into
   `src/taxonomy/language_taxonomy_overrides.json`, rebuild, and rerun the
   targeted diagnostics for any risky labels.

Useful targeted diagnostic:

```bash
scripts/taxonomy/diagnose_language_taxonomy_matches.py \
  "Kiautschou German Pidgin" "Volga German" "Zipser German"
```

## Policy Notes

- Overrides are applied before Glottolog/fuzzy matching.
- False-positive guards should generally be explicit overrides.
- Contact languages should not be forced into a source-language family merely
  because the lexifier is Indo-European. In the current taxonomy, `Pidgin` is a
  top-level family bucket with branches such as `German-based pidgin`.
- Non-selectable `Review` output is intentional; it is safer than silently
  promoting ambiguous matches.
