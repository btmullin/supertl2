-- Initialize category table 
INSERT INTO category(name, parent) VALUES('nordic skiing', null);
INSERT INTO category(name, parent) VALUES('snow', 1);
INSERT INTO category(name, parent) VALUES('roller', 1);
INSERT INTO category(name, parent) VALUES('skate', 2);
INSERT INTO category(name, parent) VALUES('classic', 2);
INSERT INTO category(name, parent) VALUES('skate', 3);
INSERT INTO category(name, parent) VALUES('classic', 3);
INSERT INTO category(name, parent) VALUES('running', null);
INSERT INTO category(name, parent) VALUES('biking', null);
INSERT INTO category(name, parent) VALUES('trail', 8);
INSERT INTO category(name, parent) VALUES('road', 8);
INSERT INTO category(name, parent) VALUES('road', 9);
INSERT INTO category(name, parent) VALUES('gravel', 9);
INSERT INTO category(name, parent) VALUES('mountain', 9);
