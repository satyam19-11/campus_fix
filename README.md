# CampusFix

A campus maintenance ticketing system built on Flask and SQLite. It is the working
project that goes with the CampusFix DBMS presentation.

## Run it

```
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000. The database (`campusfix.db`) is created with sample
data on first run. Delete the file to reset the demo.

## Demo accounts

| Role | Email | Password |
|---|---|---|
| Admin / warden | admin@campus.edu | admin123 |
| Student | priya@campus.edu | student123 |
| Student | arjun@campus.edu | student123 |
| Technician (electrical) | ravi@campus.edu | tech123 |
| Technician (plumbing) | meena@campus.edu | tech123 |

## Where each syllabus topic lives

| Syllabus topic | In the project |
|---|---|
| ER to relational, constraints (Module 1) | `schema.sql`: six tables with PRIMARY KEY, FOREIGN KEY, UNIQUE, NOT NULL, CHECK, DEFAULT |
| Three-schema architecture (Module 1) | The view `v_complaint_detail` is the external level the screens read from |
| SQL: DDL, joins, nested queries, aggregates (Module 2) | `schema.sql` and the Reports page (every report has a "Show SQL" button) |
| Triggers (Module 2) | `trg_log_insert` and `trg_log_status` write Status_History automatically |
| Indexing (Module 3) | Five B-tree indexes in `schema.sql`; the "Under the hood" page shows EXPLAIN QUERY PLAN using them |
| Transactions, TCL, concurrency (Module 3) | `transaction()` in `app.py` uses BEGIN IMMEDIATE, COMMIT and ROLLBACK. Assigning a ticket twice is rejected |
| Recovery, security (Module 4) | Admin Backup button (consistent snapshot), password hashes, parameterised queries, role checks on every route |

## Suggested demo order

1. Sign in as `priya`, report an issue (INSERT, constraints, trigger logs "Reported").
2. Sign in as `admin`, assign it to a technician (one transaction: insert assignment, update status, trigger logs history).
3. Try to assign the same ticket again: it is rejected, nothing changes (rollback and locking).
4. Sign in as `ravi`, move the ticket to In Progress, then Resolved.
5. Sign in as `priya`, open the ticket, show the history, then close it.
6. As `admin`, open Reports (SQL results) and Under the hood (indexes in use).

## Notes

- The presentation shows PL/SQL syntax. SQLite has no PL/SQL and no GRANT/REVOKE, so the
  trigger is written in SQLite syntax here and roles are enforced in the application layer.
- Set `CAMPUSFIX_SECRET` to a long random value before running anywhere other than a demo.
- Not included: CSRF tokens and email notifications. Add them before real deployment.
