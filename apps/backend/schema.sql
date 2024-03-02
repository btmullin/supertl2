-- Initialize the database

DROP TABLE IF EXISTS activity;
DROP TABLE IF EXISTS category;

CREATE TABLE activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    description TEXT,
    category_id INTEGER,
    start_time DATETIME,
    distance_m FLOAT,
    active_duration_s FLOAT,
    elapsed_duration_s FLOAT,
    elevation_m FLOAT,
    avg_hr_bpm FLOAT,
    avg_speed_mps FLOAT,
    source_hash TEXT
);

CREATE TABLE category (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent INTEGER,
    name TEXT,
    FOREIGN KEY(parent) REFERENCES category(id)
);