# Taxonomy Scripts

These scripts build optional language metadata for downstream filter trees and
audit reports. They are deliberately separate from the core embedding path:
embeddings and Qdrant indexing only require processed shards, while downstream
consumers can use the taxonomy artifacts when they are available.

Inputs:

```text
processed/<run_id>/serving_metadata.json
Glottolog languoid CSV
src/taxonomy/language_taxonomy_overrides.json
```

Outputs:

```text
processed/<run_id>/language_taxonomy.json
processed/<run_id>/language_taxonomy_unmatched.json
processed/<run_id>/language_taxonomy_report.json
```
