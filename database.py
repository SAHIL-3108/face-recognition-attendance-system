# backend/database.py - Fixed JSON serialization
import sqlite3
import os
import csv
import io
from datetime import datetime, timedelta
import calendar

# Get the absolute path to the database
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "attendance.db")

print(f"📁 Database path: {DB_PATH}")

class Database:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        print(f"🔧 Using database: {self.db_path}")
        self.init_db()

    def connect(self):
        conn = sqlite3.connect(self.db_path, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        # Check if database file exists
        db_exists = os.path.exists(self.db_path)
        print(f"📊 Database exists: {db_exists}")
        
        conn = self.connect()
        cur = conn.cursor()
        
        # Only create tables if they don't exist
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                employee_id TEXT UNIQUE NOT NULL,
                face_encoding BLOB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                check_in TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'present',
                location TEXT DEFAULT 'Unknown',
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        
        # Count existing data
        cur.execute("SELECT COUNT(*) as count FROM users")
        user_count = cur.fetchone()["count"]
        cur.execute("SELECT COUNT(*) as count FROM attendance")
        attendance_count = cur.fetchone()["count"]
        
        print(f"👥 Existing users: {user_count}, 📝 Attendance records: {attendance_count}")
        
        # Safe migrations
        cur.execute("PRAGMA table_info(users)")
        user_cols = [r["name"] for r in cur.fetchall()]
        if "face_encoding" not in user_cols:
            cur.execute("ALTER TABLE users ADD COLUMN face_encoding BLOB")
        if "created_at" not in user_cols:
            cur.execute("ALTER TABLE users ADD COLUMN created_at TIMESTAMP")
            cur.execute("UPDATE users SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL")

        cur.execute("PRAGMA table_info(attendance)")
        att_cols = [r["name"] for r in cur.fetchall()]
        if "location" not in att_cols:
            cur.execute("ALTER TABLE attendance ADD COLUMN location TEXT DEFAULT 'Unknown'")

        # Create indexes for better performance
        cur.execute("CREATE INDEX IF NOT EXISTS idx_attendance_user_checkin ON attendance(user_id, check_in)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance(date(check_in))")
        
        conn.commit()
        conn.close()

    # Users
    def add_user(self, name: str, employee_id: str, face_encoding_bytes: bytes = None) -> int:
        conn = self.connect()
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO users (name, employee_id, face_encoding, created_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                (name, employee_id, face_encoding_bytes)
            )
            conn.commit()
            uid = cur.lastrowid
            print(f"✅ User added: {name} (ID: {uid})")
            return uid
        except sqlite3.IntegrityError:
            raise Exception(f"Employee ID {employee_id} already exists")
        finally:
            conn.close()

    def get_user_by_employee_id(self, employee_id: str):
        conn = self.connect()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE employee_id = ?", (employee_id,))
        row = cur.fetchone()
        conn.close()
        return row

    def rename_user(self, user_id: int, new_name: str) -> bool:
        conn = self.connect()
        cur = conn.cursor()
        cur.execute("UPDATE users SET name = ? WHERE id = ?", (new_name, user_id))
        conn.commit()
        updated = cur.rowcount > 0
        conn.close()
        if updated:
            print(f"✏️ User {user_id} renamed to: {new_name}")
        return updated

    def get_all_users(self):
        """Return list used by face_recognition_system - WITH encoding bytes"""
        conn = self.connect()
        cur = conn.cursor()
        cur.execute("SELECT id, name, employee_id, face_encoding AS encoding FROM users ORDER BY name")
        rows = cur.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_all_users_with_status(self):
        """Return list with last_check_in and checked_in_today - WITHOUT encoding bytes for JSON"""
        conn = self.connect()
        cur = conn.cursor()
        cur.execute("""
            SELECT 
                u.id,
                u.name,
                u.employee_id,
                (SELECT MAX(a.check_in) FROM attendance a WHERE a.user_id = u.id) AS last_check_in,
                EXISTS(SELECT 1 FROM attendance a WHERE a.user_id = u.id AND date(a.check_in) = date('now')) AS checked_in_today
            FROM users u
            ORDER BY u.name
        """)
        rows = cur.fetchall()
        conn.close()
        
        out = []
        for r in rows:
            out.append({
                "id": r["id"],
                "name": r["name"],
                "employee_id": r["employee_id"],
                "last_check_in": r["last_check_in"],
                "checked_in_today": bool(r["checked_in_today"])
            })
        return out

    # Attendance
    def has_checked_in_today(self, user_id: int) -> bool:
        conn = self.connect()
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM attendance WHERE user_id = ? AND date(check_in) = date('now') LIMIT 1", (user_id,))
        exists = cur.fetchone() is not None
        conn.close()
        return exists

    def record_attendance(self, user_id: int, status="present", location: str = "Unknown"):
        if self.has_checked_in_today(user_id):
            print(f"⏰ User {user_id} already checked in today")
            return False
        
        conn = self.connect()
        cur = conn.cursor()
        cur.execute("INSERT INTO attendance (user_id, status, location) VALUES (?, ?, ?)", 
                   (user_id, status, location))
        conn.commit()
        conn.close()
        print(f"✅ Attendance recorded: User {user_id}, Status: {status}")
        return True

    def get_today_attendance(self):
        conn = self.connect()
        cur = conn.cursor()
        cur.execute("""
            SELECT u.name, a.check_in, a.status, a.location
            FROM attendance a
            JOIN users u ON a.user_id = u.id
            WHERE DATE(a.check_in) = DATE('now')
            ORDER BY a.check_in DESC
        """)
        rows = cur.fetchall()
        conn.close()
        return [{"name": r["name"], "check_in": r["check_in"], "status": r["status"], "location": r["location"]} for r in rows]

    # Weekly counts & details
    def get_weekly_counts_and_details(self, reference_date=None):
        if reference_date is None:
            reference_date = datetime.now().date()
        monday = reference_date - timedelta(days=reference_date.weekday())
        sunday = monday + timedelta(days=6)
        
        conn = self.connect()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT date(check_in) AS d, COUNT(DISTINCT user_id) AS present_count
            FROM attendance
            WHERE date(check_in) BETWEEN ? AND ?
            GROUP BY date(check_in)
        """, (monday.isoformat(), sunday.isoformat()))
        
        rows = {r["d"]: r["present_count"] for r in cur.fetchall()}
        labels, dates, counts = [], [], []
        
        for i in range(7):
            d = monday + timedelta(days=i)
            labels.append(calendar.day_name[d.weekday()][:3])
            dates.append(d.isoformat())
            counts.append(int(rows.get(d.isoformat(), 0)))
            
        cur.execute("""
            SELECT a.check_in, a.location, u.name, u.employee_id, a.status
            FROM attendance a
            JOIN users u ON a.user_id = u.id
            WHERE date(a.check_in) BETWEEN ? AND ?
            ORDER BY a.check_in ASC
        """, (monday.isoformat(), sunday.isoformat()))
        
        details = []
        for r in cur.fetchall():
            details.append({
                "check_in": r["check_in"],
                "location": r["location"],
                "name": r["name"],
                "employee_id": r["employee_id"],
                "status": r["status"]
            })
            
        conn.close()
        
        return {"labels": labels, "dates": dates, "counts": counts, "details": details}

    # Export helpers
    def export_attendance_csv_bytes(self, since_days: int = 7) -> bytes:
        since_date = (datetime.now().date() - timedelta(days=since_days)).isoformat()
        conn = self.connect()
        cur = conn.cursor()
        
        if since_days >= 36500:  # "all"
            cur.execute("""
                SELECT a.check_in, a.location, u.name, u.employee_id, a.status
                FROM attendance a
                JOIN users u ON a.user_id = u.id
                ORDER BY a.check_in DESC
            """)
        else:
            cur.execute("""
                SELECT a.check_in, a.location, u.name, u.employee_id, a.status
                FROM attendance a
                JOIN users u ON a.user_id = u.id
                WHERE date(a.check_in) >= ?
                ORDER BY a.check_in DESC
            """, (since_date,))
            
        rows = []
        for r in cur.fetchall():
            rows.append({
                "check_in": r["check_in"],
                "location": r["location"],
                "name": r["name"],
                "employee_id": r["employee_id"],
                "status": r["status"]
            })
            
        conn.close()
        
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["check_in_time", "location", "name", "employee_id", "status"])
        writer.writeheader()
        
        for r in rows:
            ts = r.get("check_in")
            try:
                if isinstance(ts, str):
                    dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                else:
                    dt = ts
                time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                time_str = str(ts)
                
            writer.writerow({
                "check_in_time": time_str,
                "location": r.get("location", "N/A"),
                "name": r.get("name", ""),
                "employee_id": r.get("employee_id", ""),
                "status": r.get("status", "present")
            })
            
        return output.getvalue().encode("utf-8")

    # Debug endpoint data - FIXED to remove bytes
    def get_debug_data(self):
        """Get debug information about current data - Safe for JSON"""
        conn = self.connect()
        cur = conn.cursor()
        
        # Check users - exclude face_encoding bytes
        cur.execute("SELECT id, name, employee_id, created_at FROM users")
        users = []
        for row in cur.fetchall():
            users.append({
                "id": row["id"],
                "name": row["name"],
                "employee_id": row["employee_id"],
                "created_at": row["created_at"]
            })
        
        # Check attendance
        cur.execute("""
            SELECT a.id, a.user_id, a.check_in, a.status, a.location, u.name 
            FROM attendance a 
            JOIN users u ON a.user_id = u.id 
            ORDER BY a.check_in DESC LIMIT 10
        """)
        attendance = []
        for row in cur.fetchall():
            attendance.append({
                "id": row["id"],
                "user_id": row["user_id"],
                "user_name": row["name"],
                "check_in": row["check_in"],
                "status": row["status"],
                "location": row["location"]
            })
        
        # Get database info
        cur.execute("SELECT COUNT(*) as user_count FROM users")
        user_count = cur.fetchone()["user_count"]
        
        cur.execute("SELECT COUNT(*) as attendance_count FROM attendance")
        attendance_count = cur.fetchone()["attendance_count"]
        
        cur.execute("""
            SELECT COUNT(*) as today_count 
            FROM attendance 
            WHERE date(check_in) = date('now')
        """)
        today_count = cur.fetchone()["today_count"]
        
        conn.close()
        
        return {
            "database_info": {
                "total_users": user_count,
                "total_attendance_records": attendance_count,
                "today_attendance": today_count,
                "database_file": self.db_path,
                "file_size_bytes": os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0
            },
            "recent_users": users[:5],  # First 5 users
            "recent_attendance": attendance,
            "system_status": "ok"
        }