# supertl2.db – Canonical Database Overview

This document describes the **canonical training log database** (`supertl2.db`).

The design has three main layers:

1. **Canonical core**  
   - `activity` – one row per real-world workout  
   - `activity_source` – one row per source per workout  
   - Views (`v_activity_sources`, `v_activity_best`)

2. **Training metadata / annotations**  
   - `WorkoutType` – controlled vocabulary of workout types  
   - `Category` – hierarchical activity categories  
   - `TrainingLogData` – per-activity metadata (notes, tags, training flag, canonical link)

3. **Source / staging tables**  
   - `StravaActivity`, `StravaActivityStream` – clone of stats-for-strava tables  
   - `sporttracks_activity` – SportTracks import table

---

## Time and Timezone Semantics

### Canonical rule (invariant)
All activities are stored using **canonical UTC timestamps**.

- `activity.start_time_utc` is the authoritative time reference.
- `activity.end_time_utc` (when present) is also stored in UTC.
- No timestamps are ever stored in viewer-local time.

UTC is used to guarantee:
- consistent ordering
- stable identity
- correct cross-timezone comparisons

### Activity-local time (for grouping)
For calendar, daily, weekly, monthly, and seasonal aggregations, activities are grouped by the
**activity-local date**, not the viewer’s local date.

Activity-local date is defined as:
1. Convert `activity.start_time_utc` into the activity’s timezone (`activity.tz_name`)
2. Take the resulting local calendar date

This ensures correct behavior when:
- activities occur while traveling
- the viewer is in a different timezone than the activity location
- UTC midnight boundaries would otherwise shift activities to the wrong day

### Timezone fields
The `activity` table stores the timezone needed to interpret UTC timestamps locally:

- `tz_name` (TEXT)  
  IANA timezone identifier (e.g. `America/Chicago`, `America/Denver`)

- `utc_offset_minutes` (INTEGER)  
  UTC offset at activity start (e.g. `-360`, `-300`).  
  This value is **derived** from (`tz_name`, `start_time_utc`) and is stored mainly for
  debugging, diagnostics, and convenience.

- `tz_source` (TEXT)  
  Provenance of the timezone assignment (e.g. `strava`, `gps`, `manual`, `fallback`)

### Display vs grouping
The UI may display timestamps in:
- activity-local time (recommended default), or
- viewer-local time (optional convenience)

However, **all grouping and aggregation logic must use activity-local time**.

## 1. Canonical Core

### 1.1 `activity`

**Purpose:**  
One row per real-world workout. Stores canonical values and authoritative timestamps in UTC,
with sufficient timezone metadata to derive activity-local dates.

**Key points:**

- `start_time_utc` is the authoritative timestamp for the activity.
- Timezone fields allow correct derivation of activity-local time for grouping.
- Canonical fields (name, sport, distance/time) represent preferred values and may differ from any individual source.
- `source_quality` can be used as a heuristic on how “trustworthy” the canonical values are.

**Schema (summary):**

- `id INTEGER PRIMARY KEY`
- `start_time_utc TEXT NOT NULL`
- `end_time_utc TEXT`
- `elapsed_time_s INTEGER`
- `moving_time_s INTEGER`
- `distance_m REAL`
- `name TEXT`
- `sport TEXT`
- `source_quality INTEGER DEFAULT 0`
- `created_at_utc TEXT NOT NULL DEFAULT utcnow`
- `updated_at_utc TEXT NOT NULL DEFAULT utcnow`

**Timezone fields**
- `tz_name` TEXT — IANA timezone for the activity location
- `utc_offset_minutes` INTEGER — offset at start time (derived, DST-aware)
- `tz_source` TEXT — source of timezone assignment

**Maintenance fields:**

- `created_at_utc` TEXT NOT NULL DEFAULT utcnow
- `updated_at_utc` TEXT NOT NULL DEFAULT utcnow

**Indexes:**

- `ix_activity_start` on `(start_time_utc)`
- `ix_activity_sport` on `(sport)`

**Trigger:**

- `trg_activity_mtime` updates `updated_at_utc` on every row update.

---

### 1.2 `activity_source`

**Purpose:**  
Represents how a given real-world activity appears in each source system (Strava, SportTracks, etc.). There is typically:

- 0–1 Strava rows per `activity`
- 0–1 SportTracks rows per `activity`
- Possibly other sources in the future.

**Key points:**

- `source` is currently constrained to `('strava','sporttracks')`.
- `source_activity_id` is the original source key:
  - Strava: `StravaActivity.activityId`
  - SportTracks: `sporttracks_activity.activity_id`
- There is a **unique constraint** on `(source, source_activity_id)` to prevent duplicates.
- The table includes optional fields (`distance_m`, `elapsed_time_s`, `sport`, etc.) to allow quick comparisons and merging logic.

**Schema (summary):**

- `id INTEGER PRIMARY KEY`
- `activity_id INTEGER NOT NULL` → `activity.id`
- `source TEXT NOT NULL CHECK (source IN ('strava','sporttracks'))`
- `source_activity_id TEXT NOT NULL`
- `start_time_utc TEXT`
- `start_time_local TEXT`
- `elapsed_time_s INTEGER`
- `distance_m REAL`
- `sport TEXT`
- `payload_hash TEXT`
- `ingested_at_utc TEXT NOT NULL DEFAULT utcnow`
- `match_confidence TEXT`
- `UNIQUE (source, source_activity_id)`
- `FOREIGN KEY (activity_id) REFERENCES activity(id) ON DELETE CASCADE`

**Indexes:**

- `ix_as_activity_id` on `(activity_id)`
- `ix_as_start` on `(start_time_utc)`
- `ix_as_elapsed` on `(elapsed_time_s)`
- `ix_as_distance` on `(distance_m)`
- `ix_as_sport` on `(sport)`

---

### 1.3 Views

#### `v_activity_sources`

**Purpose:**  
Quickly show how many sources each canonical activity has, plus basic flags for Strava and SportTracks coverage.

**Columns (derived):**

- `activity_id`
- `start_time_utc`
- `sport`
- `name`
- `source_count`
- `has_strava` (0/1)
- `has_sporttracks` (0/1)

**Definition (conceptual):**

```sql
SELECT
  a.id AS activity_id,
  a.start_time_utc,
  a.sport,
  a.name,
  COUNT(*) AS source_count,
  SUM(s.source='strava')      AS has_strava,
  SUM(s.source='sporttracks') AS has_sporttracks
FROM activity a
LEFT JOIN activity_source s ON s.activity_id = a.id
GROUP BY a.id;
```

### Notes on views and time handling

Some views expose a `display_start_local` field derived from source-provided local timestamps
(e.g. Strava or SportTracks).

These fields are intended **for display only**.

They must not be used as authoritative inputs for:
- calendar placement
- daily/weekly/monthly grouping
- season boundaries

All grouping logic should be based on:
- `activity.start_time_utc`
- interpreted using `activity.tz_name`
