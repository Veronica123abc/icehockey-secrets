# Ice Hockey Analytics — Claude Context

## Purpose
Flask web app that visualizes SportLogIQ hockey game data. Main feature: interactive Plotly chart of shift time-on-ice (TOI) for both teams over game time, with scoring chances (A/B/C grades) overlaid as markers.

## Architecture: Data Pipeline

```
SportLogIQ API
    ↓
hockey/data_collection/sportlogiq_api.py   # API client, downloads game JSON files
    ↓
hockey/io/raw_game.py                      # Lazy-loads + caches JSON files from disk
    ↓
hockey/normalize/build_game.py             # Transforms raw JSON → domain models
    ↓
hockey/model/                              # Immutable dataclasses: Game, Event, ToIInterval, Roster
    ↓
hockey/visualize/shift_toi.py              # Generates Plotly figure
    ↓
app.py + templates/                        # Flask routes + Jinja2 HTML
```

## Key Files

| File | Role |
|------|------|
| `app.py` | Flask app, routes, three-level cache (game_ids / games / plotly HTML) |
| `filter_api.py` | Blueprint: cascading filter API (leagues → seasons → stages → games) |
| `hockey/io/raw_game.py` | Lazy JSON loader; auto-downloads from API if files missing |
| `hockey/normalize/build_game.py` | Normalization orchestrator |
| `hockey/model/game.py` | `Game` dataclass; exports DataFrames, computes shift series |
| `hockey/model/events.py` | `Event` dataclass (frozen, slots) |
| `hockey/model/toi.py` | `ToIInterval` dataclass (shift start/end times) |
| `hockey/visualize/shift_toi.py` | Main visualization; 3 line traces + scoring chance markers |
| `hockey/data_collection/sportlogiq_api.py` | Authenticated API client with retry logic |
| `hockey/config/settings.py` | Config from environment variables |
| `provision.py` | Standalone Azure MySQL provisioning script (not used by Flask app) |

## Templates
- `base.html` — dark theme, header/footer
- `index.html` — home page with cascading filter dropdowns and game grid
- `game.html` — game page with embedded Plotly chart
- `confirm_download.html` — modal to confirm on-demand API download

## Running Locally
```bash
flask run --debug
```
Requires `.env` with at minimum `DATA_ROOT_DIR` pointing to local game data.

## Deployment
Azure Web App (Python 3.11 Linux). CI/CD via GitHub Actions (push-triggered).
Startup command: `gunicorn --bind=0.0.0.0:8000 --timeout 120 --workers 2 app:app`
See `DEPLOYMENT.md` for full setup guide.

## Environment Variables
| Variable | Purpose |
|----------|---------|
| `DATA_ROOT_DIR` | Path to game data folders (each subfolder = one game_id) |
| `OUTPUT_DIR` | Optional output directory |
| `SPORTLOGIQ_USERNAME` | API credentials (optional, only needed for downloads) |
| `SPORTLOGIQ_PWD` | API credentials |

## Game Data Structure on Disk
```
<DATA_ROOT_DIR>/
  <game_id>/
    game-info.json
    playsequence.json
    roster.json
    playerTOI.json
    (+ one more file)
```

## Notable Patterns
- **Three-level cache** in `app.py`: game_ids list, loaded Game objects, rendered Plotly HTML
- **Frozen dataclasses** (`frozen=True, slots=True`) on Event and ToIInterval for performance
- **Cascading filter** mirrors filesystem: `leagues/<league>/<season>/<stage>/games.json`
- **Path traversal protection** in `filter_api.py` via `_is_safe_segment()`
- **On-demand download**: if game missing locally, UI prompts to fetch from API

## Filter API Endpoints
```
GET /api/leagues
GET /api/leagues/<id>/seasons
GET /api/leagues/<id>/seasons/<s>/stages
GET /api/leagues/<id>/seasons/<s>/stages/<st>/games
```
