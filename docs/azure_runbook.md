# Azure Runbook

Command record for the offline embedding VM run.

## Parameters

```bash
RESOURCE_GROUP="rg-reverse-wiktionary"
LOCATION="eastus"
CONTAINER="reverse-wiktionary"
STORAGE_ACCOUNT="revwik05111434"
```

```bash
VM_NAME="vm-reverse-wiktionary-embed"
VM_SIZE="Standard_NC4as_T4_v3"
ADMIN_USER="azureuser"
```

```bash
PRODUCT_COLLECTION="reverse_wiktionary_v1"
PRODUCT_MODEL="sentence-transformers/all-mpnet-base-v2"
```

## Providers

```bash
az provider register --namespace Microsoft.Storage
az provider register --namespace Microsoft.Compute
az provider register --namespace Microsoft.Quota
```

```bash
az provider show --namespace Microsoft.Storage --query "registrationState" --output tsv
az provider show --namespace Microsoft.Compute --query "registrationState" --output tsv
az provider show --namespace Microsoft.Quota --query "registrationState" --output tsv
```

## Storage

```bash
az group create \
  --name "$RESOURCE_GROUP" \
  --location "$LOCATION"
```

```bash
az storage account create \
  --name "$STORAGE_ACCOUNT" \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --sku Standard_LRS \
  --kind StorageV2
```

```bash
az storage container create \
  --account-name "$STORAGE_ACCOUNT" \
  --name "$CONTAINER" \
  --auth-mode login
```

```bash
az storage container list \
  --account-name "$STORAGE_ACCOUNT" \
  --auth-mode login \
  --output table
```

## Blob Layout

```bash
raw/<run_id>/
raw/latest.json

processed/<run_id>/
processed/latest.json

embeddings/<run_id>/

code/<run_id>/

indexes/<run_id>/
indexes/latest.json

logs/<cloud_run_id>/
```

## Raw Upload

```bash
./scripts/download_wiktionary_dump.sh --download-new
```

```bash
./scripts/upload_raw_to_blob.sh \
  --storage-account "$STORAGE_ACCOUNT" \
  --container "$CONTAINER"
```

```bash
az storage blob download \
  --account-name "$STORAGE_ACCOUNT" \
  --container-name "$CONTAINER" \
  --name "raw/latest.json" \
  --file /tmp/raw-latest.json \
  --auth-mode login \
  --overwrite
```

```bash
jq . /tmp/raw-latest.json
```

## Optional Local Processed Upload

```bash
./scripts/run_parse_wiktionary.sh
```

```bash
./scripts/upload_processed_to_blob.sh \
  --storage-account "$STORAGE_ACCOUNT" \
  --container "$CONTAINER"
```

## VM Quota And SKU

```bash
az vm list-skus \
  --location "$LOCATION" \
  --size "$VM_SIZE" \
  --output table
```

```bash
QUOTA_SCOPE="/subscriptions/$(az account show --query id --output tsv)/providers/Microsoft.Compute/locations/$LOCATION"
```

```bash
az quota list \
  --scope "$QUOTA_SCOPE" \
  --output json \
  | jq -r '.[] | select(((.name.value // .name // "") | tostring | test("NCAS|T4"; "i"))) | [.name.value, .limit.value] | @tsv'
```

## VM Create

```bash
az vm create \
  --resource-group "$RESOURCE_GROUP" \
  --name "$VM_NAME" \
  --location "$LOCATION" \
  --image Ubuntu2204 \
  --size "$VM_SIZE" \
  --admin-username "$ADMIN_USER" \
  --generate-ssh-keys \
  --assign-identity \
  --os-disk-size-gb 512 \
  --storage-sku StandardSSD_LRS
```

```bash
az vm extension set \
  --resource-group "$RESOURCE_GROUP" \
  --vm-name "$VM_NAME" \
  --name NvidiaGpuDriverLinux \
  --publisher Microsoft.HpcCompute \
  --version 1.6
```

## VM Blob Role

```bash
PRINCIPAL_ID="$(az vm identity show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$VM_NAME" \
  --query principalId \
  --output tsv)"
```

```bash
STORAGE_ID="$(az storage account show \
  --name "$STORAGE_ACCOUNT" \
  --resource-group "$RESOURCE_GROUP" \
  --query id \
  --output tsv)"
```

```bash
az role assignment create \
  --assignee "$PRINCIPAL_ID" \
  --role "Storage Blob Data Contributor" \
  --scope "$STORAGE_ID"
```

## VM Bootstrap

```bash
az vm run-command invoke \
  --resource-group "$RESOURCE_GROUP" \
  --name "$VM_NAME" \
  --command-id RunShellScript \
  --scripts @scripts/azure/bootstrap_embedding_vm.sh
```

```bash
az vm run-command invoke \
  --resource-group "$RESOURCE_GROUP" \
  --name "$VM_NAME" \
  --command-id RunShellScript \
  --scripts "python --version && python -m pip --version && az version && docker --version && docker compose version"
```

```bash
az vm run-command invoke \
  --resource-group "$RESOURCE_GROUP" \
  --name "$VM_NAME" \
  --command-id RunShellScript \
  --scripts "az login --identity --output none && az storage container list --account-name $STORAGE_ACCOUNT --auth-mode login --output table"
```

## Product Run

```bash
./scripts/run_embeddings_on_azure_vm.sh \
  --resource-group "$RESOURCE_GROUP" \
  --vm-name "$VM_NAME" \
  --storage-account "$STORAGE_ACCOUNT" \
  --container "$CONTAINER" \
  --collection-name "$PRODUCT_COLLECTION" \
  --model-name "$PRODUCT_MODEL" \
  --prepare-processed-if-missing
```

```bash
CLOUD_RUN_ID="<cloud_run_id_from_launcher_output>"
```

## Live Status

```bash
az storage blob download \
  --account-name "$STORAGE_ACCOUNT" \
  --container-name "$CONTAINER" \
  --name "logs/$CLOUD_RUN_ID/status.json" \
  --file "/tmp/reverse-wiktionary-$CLOUD_RUN_ID-status.json" \
  --auth-mode login \
  --overwrite
```

```bash
jq . "/tmp/reverse-wiktionary-$CLOUD_RUN_ID-status.json"
```

```bash
az storage blob download \
  --account-name "$STORAGE_ACCOUNT" \
  --container-name "$CONTAINER" \
  --name "logs/$CLOUD_RUN_ID/remote_embedding_job.log" \
  --file "/tmp/reverse-wiktionary-$CLOUD_RUN_ID.log" \
  --auth-mode login \
  --overwrite
```

```bash
tail -n 80 "/tmp/reverse-wiktionary-$CLOUD_RUN_ID.log"
```

## SSH Monitor

```bash
ssh azureuser@<vm_public_ip>
```

```bash
sudo journalctl -u "reverse-wiktionary-$CLOUD_RUN_ID" -f
```

```bash
tail -f "/tmp/reverse-wiktionary-$CLOUD_RUN_ID.log"
```

```bash
nvidia-smi
```

```bash
curl -fsS "http://localhost:6333/collections/$PRODUCT_COLLECTION" \
  | jq '{status: .result.status, points: .result.points_count, indexed: .result.indexed_vectors_count, queue: .result.update_queue.length}'
```

## Snapshot-Only Rerun

```bash
EMBEDDING_RUN_ID="<embedding_run_id>"
```

```bash
./scripts/snapshot_qdrant_on_azure_vm.sh \
  --resource-group "$RESOURCE_GROUP" \
  --vm-name "$VM_NAME" \
  --storage-account "$STORAGE_ACCOUNT" \
  --container "$CONTAINER" \
  --collection-name "$PRODUCT_COLLECTION" \
  --run-id "$EMBEDDING_RUN_ID" \
  --timeout-seconds 3600 \
  --poll-interval-seconds 5
```

```bash
./scripts/snapshot_qdrant_on_azure_vm.sh \
  --resource-group "$RESOURCE_GROUP" \
  --vm-name "$VM_NAME" \
  --storage-account "$STORAGE_ACCOUNT" \
  --container "$CONTAINER" \
  --collection-name "$PRODUCT_COLLECTION" \
  --run-id "$EMBEDDING_RUN_ID" \
  --reuse-existing
```

## Run Record

```bash
./scripts/create_offline_run_record.sh \
  --storage-account "$STORAGE_ACCOUNT" \
  --container "$CONTAINER" \
  --cloud-run-id "$CLOUD_RUN_ID"
```

## Shutdown

```bash
az vm deallocate \
  --resource-group "$RESOURCE_GROUP" \
  --name "$VM_NAME"
```

```bash
az vm get-instance-view \
  --resource-group "$RESOURCE_GROUP" \
  --name "$VM_NAME" \
  --query "instanceView.statuses[?starts_with(code, 'PowerState/')].displayStatus" \
  --output tsv
```

## 20260512 Run Notes

```bash
# 20260512T203456Z: dependency install failed from local pip-freeze requirements.
# resolution: requirements.txt contains direct runtime dependencies only.
```

```bash
# 20260512T204458Z: embeddings completed; original wrapper failed during Qdrant snapshot.
# recovery: snapshot uploaded manually under indexes/20260512T204458Z.
# follow-up: background systemd jobs, live Blob status/log upload, 3600s snapshot timeout.
```
