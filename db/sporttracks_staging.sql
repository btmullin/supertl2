-- sporttracks_staging.sql
-- Staging table for one-time SportTracks import (metric units)

BEGIN TRANSACTION;

CREATE TABLE IF NOT EXISTS sporttracks_activity_staging (
  activity_id                  TEXT PRIMARY KEY,          -- SportTracks activity id (store as TEXT for safety)
  start_date                   TEXT,                      -- Local date, 'YYYY-MM-DD'
  start_time                   TEXT,                      -- Local time, 'HH:MM:SS'
  distance_m                   REAL,                      -- meters
  duration_s                   REAL,                      -- seconds
  avg_pace_s_per_km            REAL,                      -- seconds per kilometer (compute from distance/time if needed)
  elev_gain_m                  REAL,                      -- meters
  avg_heartrate_bpm            REAL,                      -- bpm (integer-ish; keep REAL to allow null/partials)
  avg_power_w                  REAL,                      -- watts (nullable; only when available)
  calories_kcal                REAL,                      -- kilocalories
  category                     TEXT,                      -- SportTracks category name
  notes                        TEXT,                      -- free text
  has_tcx                      INTEGER NOT NULL DEFAULT 0 -- boolean (0/1)
    CHECK (has_tcx IN (0,1))
);

-- Optional helper indexes for faster lookups while reconciling/merging:
CREATE INDEX IF NOT EXISTS idx_staging_start_date  ON sporttracks_activity_staging(start_date);
CREATE INDEX IF NOT EXISTS idx_staging_category    ON sporttracks_activity_staging(category);

COMMIT;
