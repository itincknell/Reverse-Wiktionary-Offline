# Web Serving Smoke: ACORN Retrieval and VM Sizing

Date: 2026-05-18 UTC

Collection: `reverse_wiktionary_v1`

Qdrant: `1.18.0`

Points: `3,869,247`

## Retrieval Finding

Plain filtered HNSW search degraded result quality when the selected language
or POS subset was small. Increasing `hnsw_ef` alone did not reliably fix the
issue. Qdrant ACORN search with `max_selectivity=1.0` matched manual quality
expectations closely enough to become the default filtered-search mode.

Production query policy:

```text
no filters: hnsw_ef=512
language or POS filters: hnsw_ef=512 + ACORN max_selectivity=1.0
diagnostic override: SEARCH_EXACT_FILTERED=true
```

## Benchmark Summary

Run artifacts:

```text
reverse-wiktionary/logs/web_smoke/acorn-benchmark-20260518T012145Z/
```

| Case | Requests | Concurrency | Throughput | API p95 | Qdrant p95 | Errors |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Unfiltered | 400 | 4 | 38.19 rps | 120.65 ms | 47.32 ms | 0 |
| English filter | 400 | 4 | 23.18 rps | 233.97 ms | 170.23 ms | 0 |
| French filter | 400 | 4 | 27.64 rps | 203.02 ms | 151.27 ms | 0 |

## Sizing Notes

The benchmark ran on `Standard_NC4as_T4_v3`. The GPU was not used for serving.

Observed memory:

```text
Qdrant container: about 12.4 GiB
Qdrant process RSS: about 13.6 GiB
one web worker/model process: about 1.5 GiB
Redis: about 9 MiB
Qdrant storage: about 13 GiB
```

Initial deployment target: a single CPU VM around 4 vCPU / 32 GiB RAM. A
16 GiB VM is likely too tight once Qdrant, the web worker model, Redis, the OS,
and operational headroom are included.
