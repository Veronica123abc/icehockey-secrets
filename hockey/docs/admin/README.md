# Admin Guide

This guide covers the operational workflows for maintaining the hockey analytics app in production.

## Architecture Overview

Data is loaded through a three-level hierarchy:

```
1. Azure MySQL DB        — fastest; used when available and game is ingested
2. DATA_ROOT_DIR         — filesystem fallback; game JSON files on Azure Files (/home/data)
3. SportlogIQ API        — last resort; user is prompted to trigger a download
```

The front page filter (leagues → seasons → stages → games) is served entirely from
in-memory manifests loaded at startup from `DATA_ROOT_DIR/leagues/`. This avoids
repeated reads from the Azure Files network share. The cache is refreshed via the
`/admin/refresh-manifests` endpoint without restarting the app.

All downloads and DB ingestions are performed from a local **maintenance computer**,
not from the production server.

---

## Environment Variables

| Variable | Where set | Purpose |
|----------|-----------|---------|
| `DATA_ROOT_DIR` | Azure App Config + local `.env` | Root of game data and manifests |
| `DATABASE_HOST_AZURE` | Azure App Config + local `.env` | Enables DB-backed game loading |
| `ADMIN_SECRET` | Azure App Config + local `.env` | Protects `/admin/refresh-manifests` |
| `SPORTLOGIQ_USERNAME` | local `.env` only | API credentials for downloads |
| `SPORTLOGIQ_PWD` | local `.env` only | API credentials for downloads |

Connection strings and credentials belong in `.dev-notes/` (gitignored), not here.

---

## Updating Game Schedules (Manifests)

Run this after new games are scheduled or results are published.

**1. Fetch latest schedules locally**
```bash
python hockey/data_collection/fetch_schedules.py
```
This writes updated JSON files to `DATA_ROOT_DIR/leagues/`.

**2. Sync to Azure Files**
```bash
az storage file upload-batch \
  --source <DATA_ROOT_DIR>/leagues \
  --destination <share-name>/leagues \
  --account-name <storage-account-name> \
  --account-key <storage-account-key>
```
Storage account details are in the Azure Portal under the App Service →
Configuration → Path Mappings, or in `.dev-notes/`.

**3. Refresh the running app**
```bash
curl -X POST https://hockeystats-demo-eneffkg6gbh4gcgg.azurewebsites.net/admin/refresh-manifests \
     -H "X-Admin-Secret: $ADMIN_SECRET"
```
Returns `{"ok": true}` on success. The app reloads all manifests from Azure Files
into memory without restarting.

---

## Downloading and Ingesting Game Data

Run this to make a specific game available via the DB (fastest load path).

**1. Download game files from SportlogIQ**
```python
from hockey.data_collection.sportlogiq_api import download_complete_game
download_complete_game(game_id, root_dir="<DATA_ROOT_DIR>")
```

**2. Ingest into the Azure MySQL DB**
```bash
python hockey/db/seed/ingest_events.py --game-id <game_id>
```
Repeat for other ingest scripts as needed (`ingest_shifts.py`, etc.).

Games not yet ingested will fall back to loading from `DATA_ROOT_DIR` JSON files,
or prompt the user to download if neither source is available.

---

## Deploying Code Changes

CI/CD is handled by GitHub Actions. Deployments trigger automatically on push to:

```
claude/deploy-azure-webapp-deuB7
```

The production app is: `hockeystats-demo-eneffkg6gbh4gcgg` (Azure Web App, Sweden Central).

To deploy:
```bash
git push origin <your-branch>:claude/deploy-azure-webapp-deuB7
```

Monitor the deploy under the **Actions** tab in GitHub.

---

## Restarting the App

A restart is rarely needed (use `/admin/refresh-manifests` for manifest updates instead),
but if required:

```bash
az webapp restart \
  --name hockeystats-demo-eneffkg6gbh4gcgg \
  --resource-group <resource-group>
```

On restart, the app re-warms all manifest caches from Azure Files automatically.
