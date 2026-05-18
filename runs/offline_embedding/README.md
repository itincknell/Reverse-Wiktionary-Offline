# Offline Embedding Run Records

Run records are human-readable summaries of completed cloud embedding runs.
Machine-readable artifacts remain in Blob Storage:

```text
logs/<cloud_run_id>/status.json
logs/<cloud_run_id>/remote_embedding_job.log
embeddings/<embedding_run_id>/manifest.json
indexes/<embedding_run_id>/manifest.json
```

Record generation:

```bash
./scripts/create_offline_run_record.sh \
  --storage-account "$STORAGE_ACCOUNT" \
  --container "$CONTAINER" \
  --cloud-run-id "$CLOUD_RUN_ID"
```
