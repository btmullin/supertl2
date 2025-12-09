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

## 1. Canonical Core

### 1.1 `activity`

**Purpose:**  
One row per real-world workout, in canonical UTC time. This is the central table that the rest of the system should reference.

**Key points:**

- `start_time_utc` is the canonical time reference (ISO8601 UTC string).
- `distance_m`, `elapsed_time_s`, etc. can be derived from sources or stored canonically.
- `name` and `sport` are canonical / preferred values, not necessarily verbatim from any one source.
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
