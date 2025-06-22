-- Initialize Category table 
INSERT INTO Category(name, parent_id) VALUES('nordic skiing', null);
INSERT INTO Category(name, parent_id) VALUES('snow', 1);
INSERT INTO Category(name, parent_id) VALUES('roller', 1);
INSERT INTO Category(name, parent_id) VALUES('skate', 2);
INSERT INTO Category(name, parent_id) VALUES('classic', 2);
INSERT INTO Category(name, parent_id) VALUES('skate', 3);
INSERT INTO Category(name, parent_id) VALUES('classic', 3);
INSERT INTO Category(name, parent_id) VALUES('running', null);
INSERT INTO Category(name, parent_id) VALUES('biking', null);
INSERT INTO Category(name, parent_id) VALUES('trail', 8);
INSERT INTO Category(name, parent_id) VALUES('road', 8);
INSERT INTO Category(name, parent_id) VALUES('road', 9);
INSERT INTO Category(name, parent_id) VALUES('gravel', 9);
INSERT INTO Category(name, parent_id) VALUES('mountain', 9);

-- Initialize WorkoutType table
INSERT INTO WorkoutType(name, description) VALUES('L3', 'Level 3 Intervals');
INSERT INTO WorkoutType(name, description) VALUES('L4', 'Level 4 Intervals');
INSERT INTO WorkoutType(name, description) VALUES('OD', 'Over Distance');
INSERT INTO WorkoutType(name, description) VALUES('Speed', 'Neruomuscular Focused Speeds');
