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

CREATE TABLE StravaActivity (
    activityId VARCHAR(255) NOT NULL,
    startDateTime DATETIME NOT NULL, --(DC2Type:datetime_immutable)
    data CLOB DEFAULT NULL, --(DC2Type:json)
    gearId VARCHAR(255) DEFAULT NULL,
    weather CLOB DEFAULT NULL, --(DC2Type:json)
    location CLOB DEFAULT NULL, --(DC2Type:json)
    sportType VARCHAR(255) NOT NULL,
    name VARCHAR(255) NOT NULL,
    description VARCHAR(255) DEFAULT NULL,
    distance INTEGER NOT NULL,
    elevation INTEGER NOT NULL,
    calories INTEGER DEFAULT NULL,
    averagePower INTEGER DEFAULT NULL,
    maxPower INTEGER DEFAULT NULL,
    averageSpeed DOUBLE PRECISION NOT NULL,
    maxSpeed DOUBLE PRECISION NOT NULL,
    averageHeartRate INTEGER DEFAULT NULL,
    maxHeartRate INTEGER DEFAULT NULL,
    averageCadence INTEGER DEFAULT NULL,
    movingTimeInSeconds INTEGER NOT NULL,
    kudoCount INTEGER NOT NULL,
    deviceName VARCHAR(255) DEFAULT NULL,
    totalImageCount INTEGER NOT NULL,
    localImagePaths CLOB DEFAULT NULL,
    polyline CLOB DEFAULT NULL,
    gearName VARCHAR(255) DEFAULT NULL,
    startingCoordinateLatitude DOUBLE PRECISION DEFAULT NULL,
    startingCoordinateLongitude DOUBLE PRECISION DEFAULT NULL,
    isCommute BOOLEAN DEFAULT NULL,
    streamsAreImported BOOLEAN DEFAULT NULL,
    workoutType VARCHAR(255) DEFAULT NULL,
    PRIMARY KEY(activityId)
);