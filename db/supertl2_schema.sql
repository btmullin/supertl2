-- Initialize the database

DROP TABLE IF EXISTS activity;
DROP TABLE IF EXISTS category;

-- Main table with logical FK to Strava activity and workout type
CREATE TABLE Supertl2Extra (
    activityId TEXT PRIMARY KEY,     -- matches strava.Activity.activityId
    workoutTypeId INTEGER,           -- optional, maps to WorkoutType.id
    categoryId INTEGER,              -- optional, FK to Category
    notes TEXT,                      -- optional freeform
    tags TEXT,                       -- comma-separated tags or JSON
    isTraining INTEGER DEFAULT 2,    -- tri-state flag (0 - no/1 - yes/2 - unknown)
    
    FOREIGN KEY (workoutTypeId) REFERENCES WorkoutType(id)
    FOREIGN KEY (categoryId) REFERENCES Category(id)
);

-- Table of allowable workout types
CREATE TABLE WorkoutType (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,       -- e.g., "L3", "OD"
    description TEXT                 -- optional, e.g., "Long aerobic threshold"
);

-- Heirarchical category for workout info
CREATE TABLE Category (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id INTEGER,
    name TEXT NOT NULL,
    FOREIGN KEY(parent_id) REFERENCES Category(id)
);