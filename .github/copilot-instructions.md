# Project Guidelines

## Code Style
- Python style in this repo uses `snake_case` for functions and methods, `CamelCase` for classes, and explicit imports (see `apps/backend/app/services/analytics.py`).
- Prefer full type hints using `typing` aliases (`Optional`, `Iterable`, `Dict`, `List`, `Tuple`) as seen across service and util modules.
- Keep docstrings on public modules/functions (example: `apps/backend/app/services/timezones.py`).
- SQLAlchemy models inherit from `BaseModel` in `apps/backend/app/db/base.py`; use `relationship(..., back_populates=...)` patterns from `apps/backend/app/models/`.
- Timestamps are stored as UTC ISO8601 plus timezone metadata (`tz_name`, `utc_offset_minutes`, `tz_source`) in canonical activity records (`apps/backend/app/models/activity.py`).
- Templates extend `apps/backend/app/templates/base.html`; frontend styling is modular via `apps/backend/app/static/css/main.css`.

## Architecture
- Flask app factory and config live in `apps/backend/app/__init__.py`; primary routes/blueprint are in `apps/backend/app/views.py`.
- Business logic belongs in `apps/backend/app/services/`; route handlers should stay thin and delegate there.
- ORM entities are in `apps/backend/app/models/`; DB helpers/base are in `apps/backend/app/db/`.
- `util/` scripts are operational tooling: `util/canonical/` (backfills), `util/quality/` (integrity/merge checks), `util/sporttracks/` (imports/ETL), `util/backups/` (snapshots).
- Core flow is: views -> services -> SQLAlchemy models/DB.

## Build and Test
- Build container: `docker compose build`.
- Start app: `docker compose up` (Flask runs from `command: flask run --host=0.0.0.0` in `docker-compose.yml`).
- Open app at `http://localhost:5000`.
- Shell into container: `docker compose exec app sh` (also in `shell.bat`).
- Database schema/data reference files are `db/supertl2_schema.sql` and `db/supertl2_data.sql`.
- No formal automated test suite is present; validate by targeted route/script execution.

## Project Conventions
- Canonical truth is the `activity` table, with source linkage through `activity_source` (see `db/supertl2_schema.sql`).
- New ingestion/backfill work should follow existing scripts in `util/canonical/` (e.g., `backfill_new_strava_to_canonical.py`).
- Timezone normalization is first-class; reuse service/util timezone helpers rather than ad-hoc datetime math.
- Put new route handlers in `views.py`, domain logic in `services/<domain>.py`, and one-off data repair scripts in `util/quality/`.

## Integration Points
- Strava-derived data comes from a mounted `statistics-for-strava` SQLite DB at `/stravadb/strava.db` (configured in `docker-compose.yml`).
- SportTracks imports and backfills are under `util/sporttracks/` and `util/canonical/backfill_sporttracks_to_canonical.py`.
- FIT file parsing uses `garmin_fit_sdk` from `requirements.txt`.
- Frontend libraries are CDN-based Bootstrap, plus Leaflet and Chart.js in templates.

## Security
- `SECRET_KEY` is hardcoded in `apps/backend/app/__init__.py`; treat as development-only and prefer env-var override for production-like work.
- There is no auth/authorization layer; assume single-user trusted environment unless implementing security features.
- Uploads are restricted to `.fit` via `ALLOWED_EXTENSIONS`, with files written under `/data/uploads`.
- SQLite is file-based (`/app/db/supertl2.db` in container), so backup/restore scripts in `util/backups/` are operationally important.
