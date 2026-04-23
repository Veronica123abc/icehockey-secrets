# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

Flask web app that visualizes SportLogIQ hockey game data. Main feature: an interactive Plotly chart of mean current shift time-on-ice (TOI) for both teams over game time, with graded scoring chances (A/B/C, 5v5 only) overlaid as markers.

## Running Locally

```bash
flask run --debug
```

Requires `.env` with at minimum `DATA_ROOT_DIR` pointing to a local directory of game data (see `.env.example`). There is no test suite and no linter configured.

To run a standalone visualization script directly (bypassing Flask):

```bash
python hockey/visualize/shift_toi.py
```

To download game data from the SportLogIQ API (requires credentials in `.env`):

```python
from hockey.data_collection.sportlogiq_api import download_complete_game
download_complete_game(game_id, root_dir="/path/to/data")
```

To update manifests after fetching new league/competition data:

```bash
python hockey/manifests/fetch_manifests.py
```

## Architecture

### Data Pipeline

```
SportLogIQ API
    ↓
hockey/data_collection/sportlogiq_api.py   # Downloads game JSON files to disk
    ↓
hockey/io/raw_game.py                      # Lazy-loads + caches JSON files
    ↓
hockey/normalize/build_game.py             # Transforms raw JSON → domain models
    ↓
hockey/model/                              # Game, Event, ToIInterval, Roster dataclasses
    ↓
hockey/derive/current_shift_series.py      # Computes per-second shift TOI series
    ↓
hockey/visualize/shift_toi.py              # Generates Plotly figure
    ↓
app.py + templates/                        # Flask routes + Jinja2 HTML
```

### The `derive/` Layer

This is the computational core between model and visualization. `current_shift_toi_series()` in `hockey/derive/current_shift_series.py` takes a list of query times and efficiently returns per-team snapshots of which players are on ice and their current shift duration. It uses a sweep-line algorithm (`find_intervals`) rather than per-second brute force.

`Game.shift_toi_series(queries)` delegates directly to this function. The visualization calls it once for the full game (`range(end_time)`) to build all three line traces.

### Manifests (static metadata)

`hockey/manifests/` contains bundled JSON files:
- `leagues.json`, `teams.json`, `all_competitions.json` — global lookups
- `{league_id}/competitions.json` — seasons and stages per league
- `{league_id}/{season}/{stage}/games.json` (or `{season}/games.json`) — game schedules

The filter API reads exclusively from these manifests, not from `DATA_ROOT_DIR`. They are updated by running `fetch_manifests.py`, which copies from `DATA_ROOT_DIR/leagues/`. Currently covers league IDs 1, 13, 17, 213.

### Three-Level Cache in `app.py`

Module-level globals: `_game_ids_cache` (list), `_game_cache` (dict by game_id), `_plotly_cache` (dict by game_id). All are invalidated together by `_invalidate_game_caches()` after a download. This is a simple in-process cache — it resets on worker restart.

### Scoring Chance Display

Only 5v5 chances are shown on the chart. The filter is applied in `shift_toi.py`:
```python
e.raw['team_skaters_on_ice'] == 5 and e.raw['opposing_team_skaters_on_ice'] == 5
```
Grades A/B/C map to colors green/orange/red. Home chances appear above the x-axis, away below.

## Key Files

| File | Role |
|------|------|
| `app.py` | Flask app, routes, three-level cache |
| `filter_api.py` | Blueprint: cascading filter API, reads from manifests |
| `hockey/io/raw_game.py` | Lazy JSON loader; `RawGame` dataclass |
| `hockey/normalize/build_game.py` | Orchestrates normalization into `Game` |
| `hockey/model/game.py` | `Game` dataclass; DataFrame exports; shift series methods |
| `hockey/derive/current_shift_series.py` | `find_intervals` sweep-line + `current_shift_toi_series` |
| `hockey/visualize/shift_toi.py` | Main visualization: 3 line traces + chance markers |
| `hockey/data_collection/sportlogiq_api.py` | `SportlogiqApi` client + `download_complete_game` |
| `hockey/config/settings.py` | `Settings.from_env()` — reads `DATA_ROOT_DIR`, `OUTPUT_DIR` |
| `hockey/manifests/fetch_manifests.py` | Copies manifests from data dir into the repo |

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `DATA_ROOT_DIR` | Path to game data folders (each subfolder = one game_id) |
| `OUTPUT_DIR` | Optional output directory (default: `./output`) |
| `SPORTLOGIQ_USERNAME` | API credentials (only needed for downloads) |
| `SPORTLOGIQ_PWD` | API credentials |

## Game Data Structure on Disk

```
<DATA_ROOT_DIR>/
  <game_id>/
    game-info.json
    playsequence.json
    playerTOI.json
    roster.json
    playsequence_compiled.json   # downloaded but not used by Flask
    shifts.json                  # downloaded but not used by Flask
```

## Filter API Endpoints

```
GET /api/leagues
GET /api/leagues/<id>/seasons
GET /api/leagues/<id>/seasons/<s>/stages
GET /api/leagues/<id>/seasons/<s>/stages/<st>/games
GET /api/leagues/<id>/seasons/<s>/games?limit=30
GET /api/leagues/<id>/games/recent?limit=30
```

Path traversal is guarded by `_is_safe_segment()` in `filter_api.py`.

## Deployment

Azure Web App (Python 3.11 Linux). CI/CD via GitHub Actions — deploys **only** from branch `claude/deploy-azure-webapp-deuB7`, not from main. Startup command:

```
gunicorn --bind=0.0.0.0:8000 --timeout 120 --workers 2 app:app
```

Game data lives in `/home/data` on Azure (persistent across restarts and redeployments).

## Other Modules

- `hockey/db/` — seed scripts for an Azure MySQL database (not used by the Flask app)
- `hockey/metrics/` — standalone analytics scripts (cross-center passes, faceoffs, pass length)
- `hockey/experiments/` — exploratory analyses (e.g. fatigue/grade correlation)
- `hockey/io/blob_upload.py` — Azure Blob Storage upload utility
