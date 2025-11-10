# backend/app.py - Optimized for Raspberry Pi (FIXED DUPLICATE ROUTES)
from flask import Flask, request, jsonify, Response, send_from_directory, send_file, make_response
from flask_cors import CORS
import cv2, threading, time, os, io, csv, sqlite3
from datetime import datetime, time as dt_time
import numpy as np

# optional xlsx support
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
    print("✅ Pandas available for Excel export")
except Exception:
    PANDAS_AVAILABLE = False
    print("⚠️ Pandas not available, using CSV export only")

from database import Database
from face_recognition_system import FaceRecognitionSystem

BASE_DIR = os.path.dirname(__file__)
FRONTEND_DIR = os.path.abspath(os.path.join(BASE_DIR, "../frontend"))

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="/")
CORS(app)

# Initialize DB and recognition system
print("🔄 Initializing database...")
db = Database()
print("🔄 Initializing face recognition system...")
frs = FaceRecognitionSystem(db)

# camera (index env CAMERA_INDEX or default 0)
CAM_INDEX = int(os.environ.get("CAMERA_INDEX", "0"))
print(f"📷 Initializing camera index: {CAM_INDEX}")
video_capture = cv2.VideoCapture(CAM_INDEX)
if not video_capture.isOpened():
    print(f"❌ Warning: camera {CAM_INDEX} could not be opened.")

recognition_active = False
recognition_thread = None
_last_seen = {}  # uid -> timestamp to throttle DB writes

# Late time configuration (default: 9:00 AM)
LATE_TIME_HOUR = 9
LATE_TIME_MINUTE = 0

def placeholder_jpg(w=320, h=240):
    """Create placeholder image when camera fails"""
    img = (255 * np.zeros((h, w, 3), dtype="uint8"))
    cv2.putText(img, "NO CAMERA", (50, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (100, 100, 100), 2)
    ret, buf = cv2.imencode(".jpg", img)
    return buf.tobytes() if ret else b""

def generate_frames():
    """Yield MJPEG frames with optional recognition overlays."""
    frame_count = 0
    while True:
        ok, frame = video_capture.read()
        frame_count += 1
        
        if not ok or frame is None:
            data = placeholder_jpg()
            yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + data + b"\r\n")
            time.sleep(0.1)
            continue

        if recognition_active:
            try:
                boxes, names, uids = frs.recognize(frame)
                # Add status-based colors
                for (top, right, bottom, left), name, uid in zip(boxes, names, uids):
                    if name == "Unknown":
                        color = (0, 0, 200)  # Red for unknown
                        status = "unknown"
                    else:
                        # Check if this user is late today
                        attendance_data = db.get_today_attendance()
                        user_attendance = [a for a in attendance_data if a.get('name') == name]
                        if user_attendance and user_attendance[0].get('status') == 'late':
                            color = (255, 165, 0)  # Orange for late
                            status = "late"
                        else:
                            color = (0, 200, 0)  # Green for present
                            status = "present"
                    
                    # Draw bounding box
                    cv2.rectangle(frame, (left, top), (right, bottom), color, 2)
                    cv2.rectangle(frame, (left, bottom-35), (right, bottom), color, cv2.FILLED)
                    cv2.putText(frame, f"{name} ({status})", (left+6, bottom-6), 
                               cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255), 1)
            except Exception as e:
                print(f"❌ Recognition error: {e}")
                # Draw error message on frame
                cv2.putText(frame, "Recognition Error", (10, 30), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

        # Add timestamp
        cv2.putText(frame, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 
                   (10, frame.shape[0]-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,255), 1)
        
        # Add status indicator
        status_color = (0, 255, 0) if recognition_active else (0, 0, 255)
        status_text = "RECOGNITION ACTIVE" if recognition_active else "RECOGNITION INACTIVE"
        cv2.putText(frame, status_text, (frame.shape[1]-200, 30), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, status_color, 2)

        ret, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ret:
            time.sleep(0.01)
            continue
            
        yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n")
        
        # Limit frame rate for Raspberry Pi
        time.sleep(0.03)  # ~30 FPS

def is_late(check_in_time_str):
    """Check if the check-in time is after the configured late time."""
    global LATE_TIME_HOUR, LATE_TIME_MINUTE
    
    if not check_in_time_str:
        return False
        
    try:
        # Parse the check-in time
        if isinstance(check_in_time_str, str):
            check_in_dt = datetime.strptime(check_in_time_str, "%Y-%m-%d %H:%M:%S")
        else:
            check_in_dt = check_in_time_str
            
        # Create today's late time threshold
        late_time_today = check_in_dt.replace(
            hour=LATE_TIME_HOUR, 
            minute=LATE_TIME_MINUTE, 
            second=0, 
            microsecond=0
        )
        
        # Check if check-in is after late time
        is_late_result = check_in_dt > late_time_today
        print(f"⏰ Late check: {check_in_dt} > {late_time_today} = {is_late_result}")
        return is_late_result
        
    except Exception as e:
        print(f"❌ Error checking late time: {e}")
        return False

@app.route("/video_feed")
def video_feed():
    return Response(generate_frames(), mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/register_face", methods=["POST"])
def register_face():
    """Register an employee with an uploaded face image."""
    name = request.form.get("name", "").strip()
    employee_id = request.form.get("employee_id", "").strip()
    file = request.files.get("image")
    
    if not name or not employee_id or not file:
        return jsonify({"success": False, "message": "Name, employee_id and image are required"}), 400
        
    print(f"👤 Registering face: {name} ({employee_id})")
    
    image_bytes = file.read()
    ok, msg = frs.register_face_bytes(image_bytes, name, employee_id, num_jitters=1)
    
    if ok:
        frs.reload_cache()
        return jsonify({"success": True, "message": msg})
    else:
        return jsonify({"success": False, "message": msg}), 400

@app.route("/attendance")
def attendance():
    """Return today's attendance records with late status."""
    try:
        rows = db.get_today_attendance()
        print(f"📊 Today's attendance records: {len(rows)}")
        
        # Add late status to each record
        for row in rows:
            if row.get('check_in'):
                row['is_late'] = is_late(row['check_in'])
                print(f"👤 {row['name']}: {row['check_in']} - Late: {row['is_late']}")
            else:
                row['is_late'] = False
                
        return jsonify(rows)
    except sqlite3.OperationalError as e:
        return jsonify({"error": "database error", "detail": str(e)}), 500

@app.route("/attendance_weekly")
def attendance_weekly():
    """Return weekly labels, counts and details for charting."""
    date_str = request.args.get("date")
    ref = None
    if date_str:
        try:
            ref = datetime.strptime(date_str, "%Y-%m-%d").date()
        except Exception:
            return jsonify({"error": "invalid date; use YYYY-MM-DD"}), 400
            
    try:
        data = db.get_weekly_counts_and_details(ref)
        # Add late counts to weekly data
        if 'details' in data:
            for day_data in data['details']:
                late_count = 0
                for record in day_data.get('records', []):
                    if record.get('check_in_time'):
                        record['is_late'] = is_late(record['check_in_time'])
                        if record['is_late']:
                            late_count += 1
                    else:
                        record['is_late'] = False
                day_data['late_count'] = late_count
        return jsonify(data)
    except sqlite3.OperationalError as e:
        return jsonify({"error": "database error", "detail": str(e)}), 500

@app.route("/export_attendance")
def export_attendance():
    """Export attendance as XLSX (pandas) or CSV. Query: ?range=week|all"""
    rng = request.args.get("range", "week")
    print(f"📤 Exporting attendance data: {rng}")
    
    try:
        if rng == "all":
            csv_bytes = db.export_attendance_csv_bytes(since_days=36500)
        else:
            csv_bytes = db.export_attendance_csv_bytes(since_days=7)
    except sqlite3.OperationalError as e:
        return jsonify({"error": "database error", "detail": str(e)}), 500

    if PANDAS_AVAILABLE:
        # Convert to Excel
        s = csv_bytes.decode("utf-8").splitlines()
        reader = csv.DictReader(s)
        rows = list(reader)
        
        # Add late status column
        for row in rows:
            if row.get('check_in_time'):
                row['is_late'] = 'Yes' if is_late(row['check_in_time']) else 'No'
            else:
                row['is_late'] = 'No'
        
        df = pd.DataFrame(rows)
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="attendance")
        out.seek(0)
        filename = f"attendance_{rng}_{datetime.now().date().isoformat()}.xlsx"
        return send_file(out, as_attachment=True, download_name=filename,
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    else:
        # Return CSV
        resp = make_response(csv_bytes)
        filename = f"attendance_{rng}_{datetime.now().date().isoformat()}.csv"
        resp.headers["Content-Type"] = "text/csv"
        resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        return resp

def recognition_loop():
    """Background thread to process camera frames and write attendance."""
    global recognition_active, _last_seen
    throttle_seconds = 60  # Only record once per minute per user
    
    print("🎯 Starting recognition loop...")
    
    while recognition_active:
        ok, frame = video_capture.read()
        if not ok or frame is None:
            time.sleep(0.05)
            continue
            
        try:
            boxes, names, uids = frs.recognize(frame)
        except Exception as e:
            print(f"❌ Recognition error in loop: {e}")
            boxes, names, uids = [], [], []
            
        now = time.time()
        current_time = datetime.now()
        
        for name, uid in zip(names, uids):
            if name == "Unknown" or uid is None or uid < 0:
                continue
                
            last = _last_seen.get(uid, 0)
            if (now - last) > throttle_seconds:
                try:
                    # Determine if this check-in is late
                    late_time_today = current_time.replace(
                        hour=LATE_TIME_HOUR, 
                        minute=LATE_TIME_MINUTE, 
                        second=0, 
                        microsecond=0
                    )
                    status = "late" if current_time > late_time_today else "present"
                    
                    print(f"✅ Recording: {name} (UID:{uid}) - Status: {status}")
                    
                    success = db.record_attendance(uid, status=status, location="Main Entrance")
                    if success:
                        _last_seen[uid] = now
                        
                except Exception as e:
                    print(f"❌ Error recording attendance for {name}: {e}")
                    
        time.sleep(0.1)  # Reduce CPU usage

@app.route("/start_recognition")
def start_recognition():
    global recognition_active, recognition_thread
    if recognition_active:
        return jsonify({"status": "already_running"})
        
    recognition_active = True
    recognition_thread = threading.Thread(target=recognition_loop, daemon=True)
    recognition_thread.start()
    
    print("🎬 Face recognition STARTED")
    return jsonify({"status": "started"})

@app.route("/stop_recognition")
def stop_recognition():
    global recognition_active
    recognition_active = False
    
    print("⏹️ Face recognition STOPPED")
    return jsonify({"status": "stopped"})

@app.route("/employees")
def employees():
    """Return list of employees and status - Safe for JSON"""
    try:
        rows = db.get_all_users_with_status()  # This now excludes encoding bytes
        
        # Get today's attendance to determine late status
        attendance_data = db.get_today_attendance()
        attendance_map = {a['name']: a for a in attendance_data}
        
        safe = []
        for r in rows:
            user_attendance = attendance_map.get(r.get("name"))
            is_late_today = user_attendance and user_attendance.get('status') == 'late'
            
            safe.append({
                "id": r.get("id"),
                "name": r.get("name"),
                "employee_id": r.get("employee_id"),
                "last_check_in": r.get("last_check_in"),
                "checked_in_today": bool(r.get("checked_in_today", False)),
                "is_late_today": is_late_today
            })
            
        print(f"👥 Returning {len(safe)} employees")
        return jsonify(safe)
        
    except sqlite3.OperationalError as e:
        return jsonify({"error": "database error", "detail": str(e)}), 500
    except Exception as e:
        return jsonify({"error": "unexpected error", "detail": str(e)}), 500

@app.route("/rename_user", methods=["POST"])
def rename_user():
    payload = request.get_json() or {}
    uid = payload.get("id")
    name = payload.get("name")
    
    if not uid or not name:
        return jsonify({"success": False, "message": "id and name required"}), 400
        
    ok = db.rename_user(int(uid), name)
    if ok:
        frs.reload_cache()
        return jsonify({"success": True})
        
    return jsonify({"success": False, "message": "user not found"}), 404

@app.route("/set_late_time", methods=["POST"])
def set_late_time():
    """Set the late time threshold (hour and minute)."""
    global LATE_TIME_HOUR, LATE_TIME_MINUTE
    payload = request.get_json() or {}
    hour = payload.get("hour")
    minute = payload.get("minute")
    
    if hour is None or minute is None:
        return jsonify({"success": False, "message": "hour and minute required"}), 400
    
    if not (0 <= hour <= 23) or not (0 <= minute <= 59):
        return jsonify({"success": False, "message": "hour must be 0-23, minute must be 0-59"}), 400
    
    LATE_TIME_HOUR = hour
    LATE_TIME_MINUTE = minute
    
    print(f"⏰ Late time set to: {hour:02d}:{minute:02d}")
    
    return jsonify({
        "success": True, 
        "message": f"Late time set to {hour:02d}:{minute:02d}",
        "late_time": f"{hour:02d}:{minute:02d}"
    })

@app.route("/get_late_time")
def get_late_time():
    """Get the current late time configuration."""
    return jsonify({
        "hour": LATE_TIME_HOUR,
        "minute": LATE_TIME_MINUTE,
        "late_time": f"{LATE_TIME_HOUR:02d}:{LATE_TIME_MINUTE:02d}"
    })

@app.route("/debug_data")
def debug_data():
    """Enhanced debug endpoint to check current data - Safe for JSON"""
    try:
        data = db.get_debug_data()
        
        # Add system information
        try:
            import psutil
            import platform
            
            system_info = {
                "system": platform.system(),
                "processor": platform.processor(),
                "python_version": platform.python_version(),
                "memory_usage": f"{psutil.virtual_memory().percent}%",
                "cpu_usage": f"{psutil.cpu_percent()}%",
                "disk_usage": f"{psutil.disk_usage('/').percent}%"
            }
        except ImportError:
            system_info = {
                "system": "psutil not available",
                "python_version": "unknown"
            }
        
        # Add face recognition system info
        frs_info = {
            "known_faces": len(frs.known_face_encodings),
            "tolerance": frs.tolerance,
            "model": frs.model,
            "scale": frs.scale
        }
        
        # Add camera status
        camera_ok, _ = video_capture.read()
        camera_info = {
            "camera_available": camera_ok,
            "camera_index": CAM_INDEX,
            "recognition_active": recognition_active
        }
        
        # Add late time configuration
        late_time_info = {
            "late_time_hour": LATE_TIME_HOUR,
            "late_time_minute": LATE_TIME_MINUTE,
            "current_late_threshold": f"{LATE_TIME_HOUR:02d}:{LATE_TIME_MINUTE:02d}"
        }
        
        response_data = {
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "system": system_info,
            "face_recognition": frs_info,
            "camera": camera_info,
            "late_time_config": late_time_info,
            "database": data
        }
        
        return jsonify(response_data)
        
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }), 500

@app.route("/test_json")
def test_json():
    """Simple test endpoint to verify JSON serialization works"""
    test_data = {
        "status": "ok",
        "message": "JSON serialization test",
        "numbers": [1, 2, 3],
        "nested": {
            "field1": "value1",
            "field2": "value2"
        },
        "timestamp": datetime.now().isoformat()
    }
    return jsonify(test_data)

@app.route("/health")
def health():
    ok, _ = video_capture.read()
    return jsonify({
        "camera_ok": bool(ok), 
        "known_faces": len(frs.known_face_encodings),
        "late_time": f"{LATE_TIME_HOUR:02d}:{LATE_TIME_MINUTE:02d}",
        "recognition_active": recognition_active,
        "database_path": db.db_path
    })

@app.route("/")
def serve_frontend():
    return send_from_directory(FRONTEND_DIR, "index.html")

if __name__ == "__main__":
    print("\n" + "="*50)
    print("🚀 Starting Face Recognition Attendance System")
    print("="*50)
    print(f"📁 Database: {db.db_path}")
    print(f"⏰ Default late time: {LATE_TIME_HOUR:02d}:{LATE_TIME_MINUTE:02d}")
    print(f"📷 Camera index: {CAM_INDEX}")
    print(f"👤 Known faces: {len(frs.known_face_encodings)}")
    print("="*50)
    
    # Check if frontend exists
    if not os.path.exists(FRONTEND_DIR):
        print(f"❌ Frontend directory not found: {FRONTEND_DIR}")
        print("💡 Make sure you have the frontend files in the correct location")
    
    print("🌐 Starting Flask server on http://0.0.0.0:5000 ...")
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)