-- Initialize Category table 
INSERT INTO Category(name, parent_id) VALUES('Nordic Skiing', null);
INSERT INTO Category(name, parent_id) VALUES('Snow', 1);
INSERT INTO Category(name, parent_id) VALUES('Roller', 1);
INSERT INTO Category(name, parent_id) VALUES('Skate', 2);
INSERT INTO Category(name, parent_id) VALUES('Classic', 2);
INSERT INTO Category(name, parent_id) VALUES('Skate', 3);
INSERT INTO Category(name, parent_id) VALUES('Classic', 3);
INSERT INTO Category(name, parent_id) VALUES('Running', null);
INSERT INTO Category(name, parent_id) VALUES('Biking', null);
INSERT INTO Category(name, parent_id) VALUES('Trail', 8);
INSERT INTO Category(name, parent_id) VALUES('Road', 8);
INSERT INTO Category(name, parent_id) VALUES('Road', 9);
INSERT INTO Category(name, parent_id) VALUES('Gravel', 9);
INSERT INTO Category(name, parent_id) VALUES('Mountain', 9);
INSERT INTO Category(name, parent_id) VALUES('Strength', null);
INSERT INTO Category(name, parent_id) VALUES('SkiErg', 1);
INSERT INTO Category(name, parent_id) VALUES('Hiking', null);

-- Initialize WorkoutType table
INSERT INTO WorkoutType(name, description) VALUES('General', 'General endurance workout');
INSERT INTO WorkoutType(name, description) VALUES('L3', 'Level 3 Intervals');
INSERT INTO WorkoutType(name, description) VALUES('L4', 'Level 4 Intervals');
INSERT INTO WorkoutType(name, description) VALUES('OD', 'Over Distance');
INSERT INTO WorkoutType(name, description) VALUES('Speed', 'Neruomuscular Focused Speeds');
INSERT INTO WorkoutType(name, description) VALUES('Strength', 'Strength Focused');
INSERT INTO WorkoutType(name, description) VALUES('Race', 'Any type of race');
