-- ============================================================================
-- supertl2 canonical database schema (reference)
--
-- This file is meant as a clean, human-readable specification of the schema
-- for supertl2.db. It reflects the current live database structure but is
-- formatted and ordered for clarity rather than as a direct dump.
--
-- For an existing database, use migrations rather than running this verbatim.
-- ============================================================================

-- ============================================================================
-- Canonical core tables
-- ============================================================================

-- One row per real-world workout / activity, in canonical UTC time.
CREATE TABLE activity (
  id               INTEGER PRIMARY KEY,
  start_time_utc   TEXT    NOT NULL,  -- ISO8601 UTC (e.g. 2025-08-29T19:24:52Z)
  end_time_utc     TEXT,              -- ISO8601 UTC or NULL
  elapsed_time_s   INTEGER,           -- total elapsed seconds
  moving_time_s    INTEGER,           -- moving time seconds, if known
  distance_m       REAL,              -- meters
  name             TEXT,              -- canonical / preferred name
  sport            TEXT,              -- canonical sport label
  source_quality   INTEGER DEFAULT 0, -- source quality heuristic (0 = unknown)
  created_at_utc   TEXT NOT NULL
                    DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  updated_at_utc   TEXT NOT NULL
                    DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE INDEX ix_activity_start ON activity(start_time_utc);
CREATE INDEX ix_activity_sport ON activity(sport);

-- Per-source representation for each canonical activity.
-- One row per (activity, source). Sources are currently:
--   - 'strava'
--   - 'sporttracks'
CREATE TABLE activity_source (
  id                  INTEGER PRIMARY KEY,
  activity_id         INTEGER NOT NULL,
  source              TEXT NOT NULL
                        CHECK (source IN ('strava','sporttracks')),
  source_activity_id  TEXT NOT NULL,  -- StravaActivity.activityId or SportTracks id
  start_time_utc      TEXT,           -- source UTC time if known
  start_time_local    TEXT,           -- source local time if captured
  elapsed_time_s      INTEGER,
  distance_m          REAL,
  sport               TEXT,
  payload_hash        TEXT,           -- optional hash of raw payload
  ingested_at_utc     TEXT NOT NULL
                        DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  match_confidence    TEXT,           -- free-form (e.g. 'exact', 'manual')

  CONSTRAINT fk_as_activity
    FOREIGN KEY (activity_id) REFERENCES activity(id) ON DELETE CASCADE,
  CONSTRAINT uq_source_key
    UNIQUE (source, source_activity_id)
);

CREATE INDEX ix_as_activity_id ON activity_source(activity_id);
CREATE INDEX ix_as_start       ON activity_source(start_time_utc);
CREATE INDEX ix_as_elapsed     ON activity_source(elapsed_time_s);
CREATE INDEX ix_as_distance    ON activity_source(distance_m);
CREATE INDEX ix_as_sport       ON activity_source(sport);

-- Keep updated_at_utc in sync whenever activity rows change.
CREATE TRIGGER trg_activity_mtime
AFTER UPDATE ON activity
FOR EACH ROW
BEGIN
  UPDATE activity
    SET updated_at_utc = strftime('%Y-%m-%dT%H:%M:%SZ','now')
  WHERE id = NEW.id;
END;

-- ============================================================================
-- Training metadata / user annotation tables
-- ============================================================================

-- Table of allowable workout types (L3, OD, etc.).
CREATE TABLE WorkoutType (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  name        TEXT NOT NULL UNIQUE,       -- e.g., "L3", "OD"
  description TEXT                        -- optional description
);

-- Hierarchical category tree for activities (e.g., "Skiing" → "Skate").
CREATE TABLE Category (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  parent_id  INTEGER,
  name       TEXT NOT NULL,
  FOREIGN KEY (parent_id) REFERENCES Category(id)
);

-- Per-activity training annotations keyed (primarily) by source activityId.
-- For Strava this is StravaActivity.activityId; for other sources you may use
-- a synthetic key or link via canonical_activity_id.
CREATE TABLE TrainingLogData (
  activityId            TEXT PRIMARY KEY,   -- usually StravaActivity.activityId
  workoutTypeId         INTEGER,            -- optional, maps to WorkoutType.id
  categoryId            INTEGER,            -- optional, maps to Category.id
  canonical_activity_id INTEGER,            -- optional FK to activity.id

  notes                 TEXT,               -- optional freeform notes
  tags                  TEXT,               -- comma-separated or JSON tag list
  isTraining            INTEGER DEFAULT 2,  -- tri-state: 0=no, 1=yes, 2=unknown

  FOREIGN KEY (workoutTypeId)         REFERENCES WorkoutType(id),
  FOREIGN KEY (categoryId)            REFERENCES Category(id),
  FOREIGN KEY (canonical_activity_id) REFERENCES activity(id)
);

CREATE INDEX ix_tld_canonical_activity_id
  ON TrainingLogData(canonical_activity_id);

-- ============================================================================
-- Strava import / staging tables (from stats-for-strava)
-- ============================================================================

-- Clone of stats-for-strava's Activity table with minimal adaptation.
CREATE TABLE StravaActivity (
  activityId                    VARCHAR(255) NOT NULL,
  startDateTime                 DATETIME NOT NULL, -- (DC2Type:datetime_immutable)
  data                          CLOB DEFAULT NULL, -- (DC2Type:json)
  gearId                        VARCHAR(255) DEFAULT NULL,
  weather                       CLOB DEFAULT NULL, -- (DC2Type:json)
  location                      CLOB DEFAULT NULL, -- (DC2Type:json)
  sportType                     VARCHAR(255) NOT NULL,
  name                          VARCHAR(255) NOT NULL,
  description                   VARCHAR(255) DEFAULT NULL,
  distance                      INTEGER NOT NULL,
  elevation                     INTEGER NOT NULL,
  calories                      INTEGER DEFAULT NULL,
  averagePower                  INTEGER DEFAULT NULL,
  maxPower                      INTEGER DEFAULT NULL,
  averageSpeed                  DOUBLE PRECISION NOT NULL,
  maxSpeed                      DOUBLE PRECISION NOT NULL,
  averageHeartRate              INTEGER DEFAULT NULL,
  maxHeartRate                  INTEGER DEFAULT NULL,
  averageCadence                INTEGER DEFAULT NULL,
  movingTimeInSeconds           INTEGER NOT NULL,
  kudoCount                     INTEGER NOT NULL,
  deviceName                    VARCHAR(255) DEFAULT NULL,
  totalImageCount               INTEGER NOT NULL,
  localImagePaths               CLOB DEFAULT NULL,
  polyline                      CLOB DEFAULT NULL,
  gearName                      VARCHAR(255) DEFAULT NULL,
  startingCoordinateLatitude    DOUBLE PRECISION DEFAULT NULL,
  startingCoordinateLongitude   DOUBLE PRECISION DEFAULT NULL,
  isCommute                     BOOLEAN DEFAULT NULL,
  streamsAreImported            BOOLEAN DEFAULT NULL,
  workoutType                   VARCHAR(255) DEFAULT NULL,
  activityType                  VARCHAR(255) DEFAULT NULL, -- extra field

  PRIMARY KEY (activityId)
);

-- Per-activity per-stream data (HR, power, etc.) as JSON payloads.
CREATE TABLE StravaActivityStream (
  activityId      VARCHAR(255) NOT NULL,
  streamType      VARCHAR(255) NOT NULL,
  createdOn       DATETIME NOT NULL,  -- (DC2Type:datetime_immutable)
  data            CLOB NOT NULL,      -- (DC2Type:json)
  bestAverages    CLOB DEFAULT NULL,  -- (DC2Type:json)
  normalizedPower INTEGER DEFAULT NULL,

  PRIMARY KEY (activityId, streamType)
);

-- ============================================================================
-- SportTracks import / staging table
-- ============================================================================

CREATE TABLE sporttracks_activity (
  activity_id           TEXT PRIMARY KEY,  -- SportTracks activity id
  name                  TEXT,              -- activity name

  start_date            TEXT,              -- local date 'YYYY-MM-DD'
  start_time            TEXT,              -- local time 'HH:MM:SS'
  distance_m            REAL,              -- meters
  duration_s            REAL,              -- seconds
  avg_pace_s_per_km     REAL,              -- seconds/km
  elev_gain_m           REAL,              -- meters
  avg_heartrate_bpm     REAL,              -- bpm
  avg_power_w           REAL,              -- watts
  calories_kcal         REAL,              -- kilocalories
  category              TEXT,              -- SportTracks category
  notes                 TEXT,              -- free text

  has_tcx               INTEGER NOT NULL DEFAULT 0
                          CHECK (has_tcx IN (0,1))
);

CREATE INDEX idx_st_activity_start_date
  ON sporttracks_activity(start_date);

CREATE INDEX idx_st_activity_category
  ON sporttracks_activity(category);

-- ============================================================================
-- Convenience views
-- ============================================================================

-- Simple per-activity summary of how many sources are attached.
CREATE VIEW v_activity_sources AS
SELECT
  a.id                        AS activity_id,
  a.start_time_utc,
  a.sport,
  a.name,
  COUNT(*)                    AS source_count,
  SUM(s.source = 'strava')    AS has_strava,
  SUM(s.source = 'sporttracks') AS has_sporttracks
FROM activity a
LEFT JOIN activity_source s ON s.activity_id = a.id
GROUP BY a.id
/* v_activity_sources(activity_id,start_time_utc,sport,name,source_count,
                      has_strava,has_sporttracks) */;

-- "Best" per-activity view that chooses preferred values from sources.
CREATE VIEW v_activity_best AS
WITH strava AS (
  SELECT activity_id,
         MAX(start_time_local)  AS strava_local,
         MAX(start_time_utc)    AS strava_utc,
         MAX(distance_m)        AS strava_dist_m,
         MAX(elapsed_time_s)    AS strava_time_s,
         MAX(sport)             AS strava_sport
  FROM activity_source
  WHERE source = 'strava'
  GROUP BY activity_id
),
st AS (
  SELECT activity_id,
         MAX(start_time_local)  AS st_local,
         MAX(start_time_utc)    AS st_utc,
         MAX(distance_m)        AS st_dist_m,
         MAX(elapsed_time_s)    AS st_time_s,
         MAX(sport)             AS st_sport
  FROM activity_source
  WHERE source = 'sporttracks'
  GROUP BY activity_id
)
SELECT
  a.id                               AS activity_id,
  a.start_time_utc                   AS canonical_start_utc,

  -- Display start (prefer Strava local, else ST local, else canonical UTC)
  COALESCE(strava.strava_local,
           st.st_local,
           a.start_time_utc)         AS display_start_local,

  -- Display distance/time (prefer Strava, else ST, else canonical)
  COALESCE(strava.strava_dist_m,
           st.st_dist_m,
           a.distance_m)             AS display_distance_m,
  COALESCE(strava.strava_time_s,
           st.st_time_s,
           a.elapsed_time_s)         AS display_elapsed_s,

  -- Display name/sport (prefer canonical name if present)
  COALESCE(a.name, NULL)             AS display_name,
  COALESCE(a.sport,
           strava.strava_sport,
           st.st_sport)              AS display_sport,

  -- Badges
  (strava.activity_id IS NOT NULL)   AS has_strava,
  (st.activity_id     IS NOT NULL)   AS has_sporttracks
FROM activity a
LEFT JOIN strava ON strava.activity_id = a.id
LEFT JOIN st     ON st.activity_id     = a.id
/* v_activity_best(activity_id,canonical_start_utc,display_start_local,
                   display_distance_m,display_elapsed_s,display_name,
                   display_sport,has_strava,has_sporttracks) */;
