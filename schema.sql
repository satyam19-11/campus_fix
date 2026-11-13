-- CampusFix schema (SQLite). Mirrors the relational schema in the presentation.
CREATE TABLE Users (
  user_id        INTEGER PRIMARY KEY,
  name           TEXT NOT NULL,
  email          TEXT NOT NULL UNIQUE,
  password_hash  TEXT NOT NULL,
  role           TEXT NOT NULL CHECK (role IN ('student', 'technician', 'admin'))
);

CREATE TABLE Categories (
  category_id    INTEGER PRIMARY KEY,
  category_name  TEXT NOT NULL UNIQUE
);

CREATE TABLE Technicians (
  technician_id  INTEGER PRIMARY KEY,
  user_id        INTEGER NOT NULL UNIQUE REFERENCES Users(user_id),
  speciality     TEXT NOT NULL
);

CREATE TABLE Complaints (
  complaint_id   INTEGER PRIMARY KEY,
  student_id     INTEGER NOT NULL REFERENCES Users(user_id),
  category_id    INTEGER NOT NULL REFERENCES Categories(category_id),
  location       TEXT NOT NULL,
  description    TEXT,
  created_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
  current_status TEXT NOT NULL DEFAULT 'Reported'
    CHECK (current_status IN ('Reported','Assigned','In Progress','Resolved','Closed'))
);

CREATE TABLE Assignments (
  assignment_id  INTEGER PRIMARY KEY,
  complaint_id   INTEGER NOT NULL REFERENCES Complaints(complaint_id),
  technician_id  INTEGER NOT NULL REFERENCES Technicians(technician_id),
  assigned_by    INTEGER NOT NULL REFERENCES Users(user_id),
  assigned_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE Status_History (
  history_id     INTEGER PRIMARY KEY,
  complaint_id   INTEGER NOT NULL REFERENCES Complaints(complaint_id) ON DELETE CASCADE,
  changed_by     INTEGER REFERENCES Users(user_id),
  old_status     TEXT,
  new_status     TEXT NOT NULL,
  changed_at     DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- One-row table: the application records who is acting, so triggers can log it.
CREATE TABLE Audit_Context (
  id      INTEGER PRIMARY KEY CHECK (id = 1),
  user_id INTEGER
);
INSERT INTO Audit_Context (id, user_id) VALUES (1, NULL);

-- Indexes (B-tree) on the columns used in WHERE and JOIN.
CREATE INDEX idx_complaints_student  ON Complaints(student_id);
CREATE INDEX idx_complaints_status   ON Complaints(current_status);
CREATE INDEX idx_assignments_tech    ON Assignments(technician_id);
CREATE INDEX idx_assignments_complaint ON Assignments(complaint_id);
CREATE INDEX idx_history_complaint   ON Status_History(complaint_id);

-- Triggers: every status change is logged automatically.
CREATE TRIGGER trg_log_insert AFTER INSERT ON Complaints
BEGIN
  INSERT INTO Status_History (complaint_id, changed_by, old_status, new_status, changed_at)
  VALUES (NEW.complaint_id, NEW.student_id, NULL, NEW.current_status, NEW.created_at);
END;

CREATE TRIGGER trg_log_status AFTER UPDATE OF current_status ON Complaints
WHEN OLD.current_status <> NEW.current_status
BEGIN
  INSERT INTO Status_History (complaint_id, changed_by, old_status, new_status)
  VALUES (NEW.complaint_id,
          (SELECT user_id FROM Audit_Context WHERE id = 1),
          OLD.current_status, NEW.current_status);
END;

-- External-level view: one joined, read-only picture of a ticket.
CREATE VIEW v_complaint_detail AS
SELECT c.complaint_id, c.student_id, u.name AS student_name,
       cat.category_name, c.location, c.description, c.created_at,
       c.current_status, a.technician_id, tu.name AS technician_name,
       tu.user_id AS technician_user_id
FROM Complaints c
JOIN Users u        ON u.user_id = c.student_id
JOIN Categories cat ON cat.category_id = c.category_id
LEFT JOIN Assignments a ON a.assignment_id =
      (SELECT MAX(assignment_id) FROM Assignments WHERE complaint_id = c.complaint_id)
LEFT JOIN Technicians t ON t.technician_id = a.technician_id
LEFT JOIN Users tu      ON tu.user_id = t.user_id;
