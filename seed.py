"""Sample data so the demo has something to show."""
from werkzeug.security import generate_password_hash

DEMO_ACCOUNTS = [
    ("Admin / warden", "admin@campus.edu", "admin123"),
    ("Student", "priya@campus.edu", "student123"),
    ("Student", "arjun@campus.edu", "student123"),
    ("Technician (electrical)", "ravi@campus.edu", "tech123"),
    ("Technician (plumbing)", "meena@campus.edu", "tech123"),
]


def seed(db):
    for c in ["Electrical", "Plumbing", "Wi-Fi", "Furniture", "Cleaning"]:
        db.execute("INSERT INTO Categories (category_name) VALUES (?)", (c,))

    def user(name, email, pw, role):
        return db.execute(
            "INSERT INTO Users (name, email, password_hash, role) VALUES (?,?,?,?)",
            (name, email, generate_password_hash(pw), role)).lastrowid

    admin = user("Warden Rao", "admin@campus.edu", "admin123", "admin")
    priya = user("Priya Nair", "priya@campus.edu", "student123", "student")
    arjun = user("Arjun Mehta", "arjun@campus.edu", "student123", "student")
    ravi_u = user("Ravi Kumar", "ravi@campus.edu", "tech123", "technician")
    meena_u = user("Meena Joshi", "meena@campus.edu", "tech123", "technician")
    ravi = db.execute("INSERT INTO Technicians (user_id, speciality) VALUES (?,?)", (ravi_u, "Electrical")).lastrowid
    meena = db.execute("INSERT INTO Technicians (user_id, speciality) VALUES (?,?)", (meena_u, "Plumbing")).lastrowid

    def complaint(student, cat, loc, desc, hours_ago):
        return db.execute(
            "INSERT INTO Complaints (student_id, category_id, location, description, created_at) "
            "VALUES (?,?,?,?, datetime('now', ?))", (student, cat, loc, desc, f"-{hours_ago} hours")).lastrowid

    def move(cid, status, actor, hours_ago, tech=None):
        db.execute("UPDATE Audit_Context SET user_id = ? WHERE id = 1", (actor,))
        if tech:
            db.execute("INSERT INTO Assignments (complaint_id, technician_id, assigned_by) VALUES (?,?,?)", (cid, tech, admin))
        db.execute("UPDATE Complaints SET current_status = ? WHERE complaint_id = ?", (status, cid))
        db.execute("UPDATE Status_History SET changed_at = datetime('now', ?) WHERE complaint_id = ? AND new_status = ?",
                   (f"-{hours_ago} hours", cid, status))

    c1 = complaint(priya, 1, "Hostel Block B, Room 204", "Ceiling fan not working", 30)
    move(c1, "Assigned", admin, 28, ravi); move(c1, "In Progress", ravi_u, 20)
    c2 = complaint(arjun, 2, "Hostel Block A, Washroom 2", "Leaking tap", 72)
    move(c2, "Assigned", admin, 70, meena); move(c2, "In Progress", meena_u, 60); move(c2, "Resolved", meena_u, 54)
    complaint(priya, 3, "Library, Floor 2", "Wi-Fi drops every few minutes", 10)
    complaint(arjun, 4, "Lecture Hall 3", "Broken bench in the third row", 8)
    complaint(priya, 1, "Hostel Block B, Room 204", "Tube light flickering", 5)
    complaint(arjun, 3, "Library, Floor 2", "No signal near the reading room", 3)
    c7 = complaint(arjun, 1, "Computer Lab 2", "Socket sparking near the server rack", 120)
    move(c7, "Assigned", admin, 118, ravi); move(c7, "In Progress", ravi_u, 110)
    move(c7, "Resolved", ravi_u, 100); move(c7, "Closed", arjun, 96)
    db.execute("UPDATE Audit_Context SET user_id = NULL WHERE id = 1")
