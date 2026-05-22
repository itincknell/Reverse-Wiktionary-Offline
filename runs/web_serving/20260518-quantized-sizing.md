# Web Serving Smoke: Quantized Collection Sizing

Date: 2026-05-18 UTC

Collection: `reverse_wiktionary_v1`

Qdrant: `1.18.0`

Points: `3,869,247`

## Configuration

```text
vectors: on_disk=true
quantization: scalar int8
quantile: 0.99
always_ram: true
filtered search: ACORN max_selectivity=1.0
```

Manual UI inspection after quantization did not show retrieval-quality
regression.

## Benchmark Summary

Run artifacts:

```text
reverse-wiktionary/logs/web_smoke/quantized-e2-postopt-20260518T025807Z/
```

| Case | Requests | Concurrency | Throughput | API p95 | Qdrant p95 | Errors |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Unfiltered | 400 | 4 | 40.32 rps | 125.42 ms | 53.31 ms | 0 |
| English filter | 400 | 4 | 21.05 rps | 264.45 ms | 224.18 ms | 0 |
| French filter | 400 | 4 | 20.06 rps | 260.11 ms | 230.48 ms | 0 |

## Memory

Observed after quantization and benchmark on `Standard_NC4as_T4_v3`:

```text
Qdrant Docker memory: about 3.3 GiB
Redis Docker memory: about 20 MiB
VM used memory: about 4.7 GiB
VM available memory: about 22 GiB
```

The benchmark VM had more memory and CPU than the intended beta host, so this
run validates the memory reduction and quality. The next sizing check should
run on `Standard_D2as_v5`.

## Beta Target

```text
VM: Standard_D2as_v5
CPU/RAM: 2 vCPU / 8 GiB
disk: 256 GiB Standard SSD
estimated 24/7 cost: about $82/month including disk
fallback: Standard_E2as_v5 for 16 GiB memory headroom
```
