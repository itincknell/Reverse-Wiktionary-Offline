# Web Repo Handoff

The next serving artifact is a `reverse_wiktionary_v2` Qdrant snapshot built
from raw Wiktionary data with 512-dimensional embeddings.

## Collection Contract

Collection:

```text
reverse_wiktionary_v2
```

Payload fields:

```text
word
lang
pos
glosses
expansion
```

`expansion` is nullable or absent.

Vector configuration:

```text
size: 512
distance: Cosine
vectors_on_disk: true
on_disk_payload: true
scalar_quantization:
  type: int8
  quantile: 0.99
  always_ram: true
```

Payload indexes:

```text
lang: keyword
pos: keyword
```

The query encoder must use the same model as the offline job:

```text
sentence-transformers/distiluse-base-multilingual-cased-v2
```

## Wiktionary Result Links

Do not add a runtime Wiktionary API dependency to search serving. Result links
are computed from fields already present in the Qdrant payload.

URL shape:

```text
https://en.wiktionary.org/wiki/<page>#<section>
```

Inputs:

```text
page source: word
section source: lang
```

Rules:

- Replace spaces with underscores.
- Percent-encode Unicode and other non-URL-safe characters.
- Do not transliterate Unicode to ASCII.

Examples:

```text
word=café, lang=French
https://en.wiktionary.org/wiki/caf%C3%A9#French

word=duo, lang=Norwegian Bokmål
https://en.wiktionary.org/wiki/duo#Norwegian_Bokm%C3%A5l

word=褂, lang=Chinese
https://en.wiktionary.org/wiki/%E8%A4%82#Chinese
```

MediaWiki `action=parse&prop=tocdata` is the validation source for section
anchors. Offline QA may sample pages, match top-level sections where
`line == lang`, and compare generated fragments with `linkAnchor || anchor`.
The web app should not do that check per request.

## Deployment Follow-up

- Update web repo collection name to `reverse_wiktionary_v2`.
- Update web query model to
  `sentence-transformers/distiluse-base-multilingual-cased-v2`.
- Verify health output reports vector size `512`.
- Build result links from `word` and `lang`; do not require new payload fields.
- Restore the snapshot under `/opt/reverse-wiktionary/data`.
- Delete the downloaded snapshot after restore.

## Language Taxonomy Artifacts

The web repo can consume optional taxonomy artifacts from the processed run:

```text
processed/<run_id>/language_taxonomy.json
processed/<run_id>/language_taxonomy_unmatched.json
processed/<run_id>/language_taxonomy_report.json
```

Use `language_taxonomy.json` for browse/filter UI. Read `all_languages` as the
complete language list and `tree` as the selectable family/branch hierarchy.
Languages with `selectable: false` should remain searchable by direct text
query, but should not appear as selectable taxonomy filters.

`language_taxonomy_unmatched.json` is an operations/audit artifact, not a UI
filter source. It contains both unmatched labels and non-selectable
`fuzzy_review` candidates.

Current taxonomy policy keeps `Pidgin` as a top-level family bucket when source
taxonomy says a language is a pidgin/contact language. Do not rewrite these
labels into Indo-European or another lexifier family in the online repo.
