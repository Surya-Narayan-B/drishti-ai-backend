# --- Main Imports ---
import webbrowser
import cv2
import mediapipe as mp
import numpy as np
import time
from collections import deque, defaultdict
import json
import os
import sqlite3
from datetime import datetime, timedelta
import threading
from dotenv import load_dotenv
load_dotenv() # This line loads the .env file

# --- Local Module Imports ---
import wellness_assistant

# --- Flask Imports for Web Server ---
from flask import Flask, jsonify, render_template, request

# --- Google Gemini AI Imports ---
import google.generativeai as genai

# --- Dependency Checks ---
try:
    from plyer import notification
    PLYER_AVAILABLE = True
except ImportError:
    print("[WARNING] 'plyer' not found. Desktop notifications will be disabled.")
    PLYER_AVAILABLE = False
try:
    import pyttsx3
    PYTTSX_AVAILABLE = True
    engine = pyttsx3.init()
    engine.setProperty('rate', 150)
    engine.setProperty('volume', 0.9)
except Exception as e:
    print(f"[WARNING] pyttsx3 initialization failed: {e}. Voice alerts will be disabled.")
    PYTTSX_AVAILABLE = False

# --- Gemini AI Configuration ---
# IMPORTANT: Replace with your actual API key
YOUR_API_KEY = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=YOUR_API_KEY)
model = genai.GenerativeModel('gemini-2.0-flash')

# --- MediaPipe and Calculation Functions ---
mp_face_mesh = mp.solutions.face_mesh
face_mesh = mp_face_mesh.FaceMesh(static_image_mode=False, max_num_faces=1, refine_landmarks=True, min_detection_confidence=0.5, min_tracking_confidence=0.5)
RIGHT_EYE_INDICES = [33, 160, 158, 133, 153, 144]
LEFT_EYE_INDICES = [362, 385, 387, 263, 373, 380]
LEFT_EYE_CORNER = 130
RIGHT_EYE_CORNER = 359
drowsiness_score = 0
NOSE_TIP_LANDMARK = 1
TOP_LIP_LANDMARK = 13
BOTTOM_LIP_LANDMARK = 14
MOUTH_LEFT_CORNER = 61
MOUTH_RIGHT_CORNER = 291
FOREHEAD_LANDMARK = 10
CHIN_LANDMARK = 152
def calculate_ear(landmarks, eye_indices):
    p1=np.array([landmarks[eye_indices[0]].x, landmarks[eye_indices[0]].y]);p2=np.array([landmarks[eye_indices[1]].x, landmarks[eye_indices[1]].y]);p3=np.array([landmarks[eye_indices[2]].x, landmarks[eye_indices[2]].y]);p4=np.array([landmarks[eye_indices[3]].x, landmarks[eye_indices[3]].y]);p5=np.array([landmarks[eye_indices[4]].x, landmarks[eye_indices[4]].y]);p6=np.array([landmarks[eye_indices[5]].x, landmarks[eye_indices[5]].y]);v1=np.linalg.norm(p2-p6);v2=np.linalg.norm(p3-p5);h=np.linalg.norm(p1-p4);return(v1+v2)/(2.0*h+1e-6)
def calculate_mar(landmarks):
    t=np.array([landmarks[TOP_LIP_LANDMARK].x, landmarks[TOP_LIP_LANDMARK].y]);b=np.array([landmarks[BOTTOM_LIP_LANDMARK].x, landmarks[BOTTOM_LIP_LANDMARK].y]);l=np.array([landmarks[MOUTH_LEFT_CORNER].x, landmarks[MOUTH_LEFT_CORNER].y]);r=np.array([landmarks[MOUTH_RIGHT_CORNER].x, landmarks[MOUTH_RIGHT_CORNER].y]);vd=np.linalg.norm(t-b);hd=np.linalg.norm(l-r);return vd/(hd+1e-6)

# --- Tunable Parameters & File Paths ---
# Drowsiness Score Parameters
DROWSINESS_SCORE_THRESHOLD = 9
SCORE_INCREMENT_LONG_BLINK = 5
SCORE_INCREMENT_YAWN = 3
SCORE_DECAY_RATE = 1
SCORE_DECAY_INTERVAL_SEC = 10
GAZE_STABILITY_THRESHOLD_FRAMES = 5
# Other Parameters
IDLE_TIME_THRESHOLD_SEC = 45; YAWN_MAR_THRESHOLD = 0.6; YAWN_DURATION_SEC = 1.5; MICRO_SLEEP_THRESHOLD_MS = 700; DROWSINESS_ALERT_DEBOUNCE_SEC = 10; EAR_VELOCITY_THRESHOLD = -0.008; NO_BLINK_THRESHOLD_SEC = 10; LOW_BLINK_RATE_THRESHOLD = 10; BLINK_RATE_WINDOW_SEC = 60; BREAK_DURATION_SEC = 20; NOTIFICATION_DEBOUNCE_SEC = 30; SUMMARY_LOG_INTERVAL_SEC = 15;HEAD_TILT_DOWN_THRESHOLD_PERCENT = 0.22;HEAD_TILT_UP_THRESHOLD_PERCENT = 0.19
CALIBRATION_FRAMES_OPEN = 150; CALIBRATION_FRAMES_BLINK = 150
# --- ADD THIS HELPER FUNCTION AND NEW PATH DEFINITIONS ---
import sys # Make sure you have this import at the top of your file

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)


def get_user_data_path(file_name):
    """
    Get absolute path to a file in the user's data directory.
    USE THIS FOR USER-GENERATED DATA (e.g., database, settings, logs).
    """
    # Use os.path.expanduser('~') to find the user's home directory
    app_data_dir = os.path.join(os.path.expanduser('~'), '.DrishtiAI')
    
    # Create the directory if it doesn't exist
    os.makedirs(app_data_dir, exist_ok=True)
        
    return os.path.join(app_data_dir, file_name)

CONFIG_FILE = get_user_data_path("calibration_profile.json")
DB_FILE = get_user_data_path("monitoring_data.db")
# --- END OF REPLACEMENT ---

# --- Global State Variables ---
conversation_history = []
monitoring_active = False
monitoring_thread = None
yawn_count = 0; blink_count = 0; active_time_sec = 0; idle_time_sec = 0
blink_rate_bpm = 0; is_gaze_centered = False; user_status = "Idle"
last_status_change_time = time.time()
current_session_id = None; session_start_time_iso = None

# --- Profile and Database Functions ---
def save_calibration_profile(ear_threshold, avg_open_ear, avg_face_height, avg_gaze_ratio, avg_nose_y):
    profile_data = {"ear_threshold": ear_threshold, "avg_open_ear": avg_open_ear, "avg_face_height": avg_face_height, "avg_center_gaze": avg_gaze_ratio, "avg_nose_y": avg_nose_y}
    with open(CONFIG_FILE, 'w') as f: json.dump(profile_data, f, indent=4)
    print(f"[INFO] Calibration profile saved to {CONFIG_FILE}")
def load_calibration_profile():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f: profile_data = json.load(f)
            print(f"[INFO] Calibration profile loaded from {CONFIG_FILE}")
            ear_threshold = profile_data["ear_threshold"]; avg_open_ear = profile_data["avg_open_ear"]; avg_face_height = profile_data.get("avg_face_height", 0.0); avg_center_gaze = profile_data.get("avg_center_gaze", 0.0);avg_nose_y = profile_data.get("avg_nose_y", 0.0)
            if avg_face_height == 0.0 or avg_center_gaze == 0.0: print("[WARNING] Old profile detected. Face/Gaze data will be recalibrated.")
            return ear_threshold, avg_open_ear, avg_face_height, avg_center_gaze,avg_nose_y
        except (json.JSONDecodeError, KeyError):
            print(f"[WARNING] Could not read {CONFIG_FILE}. Starting new calibration.")
    return None, None, None, None,None
def setup_database():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False); cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS sessions (session_id INTEGER PRIMARY KEY AUTOINCREMENT, start_time TEXT NOT NULL, end_time TEXT, total_active_time_sec INTEGER DEFAULT 0, total_idle_time_sec INTEGER DEFAULT 0)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS events (event_id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER NOT NULL, timestamp TEXT NOT NULL, event_type TEXT NOT NULL, value_numeric REAL, value_text TEXT, FOREIGN KEY (session_id) REFERENCES sessions (session_id))''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY,
            user_name TEXT DEFAULT 'User',
            goal_blink_rate INTEGER, goal_breaks INTEGER, enable_weekly_goals BOOLEAN,
            enable_daily_streak BOOLEAN, master_notifications BOOLEAN, notify_blink BOOLEAN,
            notify_break BOOLEAN, notify_frequency INTEGER, active_start_time TEXT, active_end_time TEXT
        )
    ''')
    cursor.execute("INSERT OR IGNORE INTO settings (id) VALUES (1)")
    conn.commit(); conn.close(); print(f"[INFO] Database '{DB_FILE}' is ready.")
def start_new_session():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False); cursor = conn.cursor()
    start_time_iso = datetime.now().isoformat(); cursor.execute("INSERT INTO sessions (start_time) VALUES (?)", (start_time_iso,)); session_id = cursor.lastrowid; conn.commit(); conn.close(); print(f"[INFO] Started new session with ID: {session_id}")
    return session_id, start_time_iso
def log_event(session_id, event_type, value_numeric=None, value_text=None):
    conn = sqlite3.connect(DB_FILE, check_same_thread=False); cursor = conn.cursor()
    timestamp_iso = datetime.now().isoformat(); cursor.execute("INSERT INTO events (session_id, timestamp, event_type, value_numeric, value_text) VALUES (?, ?, ?, ?, ?)", (session_id, timestamp_iso, event_type, value_numeric, value_text)); conn.commit(); conn.close()
def end_session(session_id, active_time, idle_time, end_time_iso):
    conn = sqlite3.connect(DB_FILE, check_same_thread=False); cursor = conn.cursor()
    cursor.execute("UPDATE sessions SET end_time = ?, total_active_time_sec = ?, total_idle_time_sec = ? WHERE session_id = ?", (end_time_iso, int(active_time), int(idle_time), session_id)); conn.commit(); conn.close(); print(f"[INFO] Session {session_id} ended. Active: {int(active_time)}s, Idle: {int(idle_time)}s")
def calculate_current_streak(conn):
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT date(start_time) FROM sessions ORDER BY date(start_time) DESC")
        session_days_str = [row[0] for row in cursor.fetchall()]
        if not session_days_str: return 0
        session_dates = [datetime.strptime(day_str, '%Y-%m-%d').date() for day_str in session_days_str]
        today = datetime.now().date(); yesterday = today - timedelta(days=1); streak = 0
        if session_dates[0] == today or session_dates[0] == yesterday:
            streak = 1
            for i in range(len(session_dates) - 1):
                if (session_dates[i] - session_dates[i+1]).days == 1: streak += 1
                else: break
        return streak
    except Exception as e:
        print(f"[ERROR] Could not calculate streak: {e}")
        return 0

# --- Alert Functions ---
def should_send_notification(notification_type):
    try:
        conn = sqlite3.connect(DB_FILE, check_same_thread=False); conn.row_factory = sqlite3.Row; cursor = conn.cursor()
        cursor.execute("SELECT * FROM settings WHERE id = 1"); settings = cursor.fetchone(); conn.close()
        if not settings or not settings['master_notifications']: return False
        if notification_type == 'drowsiness' and not settings['notify_blink']: return False
        if notification_type in ['stare', 'low_bpm'] and not settings['notify_blink']: return False
        if notification_type == 'break' and not settings['notify_break']: return False
        now = datetime.now().time()
        start_time = datetime.strptime(settings['active_start_time'], '%H:%M').time()
        end_time = datetime.strptime(settings['active_end_time'], '%H:%M').time()
        if not (start_time <= now <= end_time): return False
        return True
    except Exception as e:
        print(f"[ERROR] Could not check notification settings: {e}")
        return True
def send_notification_threaded(title, message):
    if PLYER_AVAILABLE: threading.Thread(target=notification.notify, kwargs={'title':title,'message':message,'app_name':'Eye Monitor','timeout':10}, daemon=True).start()
def speak_threaded(text):
    if PYTTSX_AVAILABLE and not engine.isBusy(): threading.Thread(target=lambda:(engine.say(text), engine.runAndWait()), daemon=True).start()

# --- Calibration Process Function ---
def run_calibration_process(user_name=None):
    print("[INFO] Starting calibration process...")
    if user_name:
        print(f"[INFO] Calibrating for user: {user_name}")
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("UPDATE settings SET user_name = ? WHERE id = 1", (user_name,))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[ERROR] Could not save user name during calibration: {e}")

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("[ERROR] Cannot open camera for calibration.")
        return

    open_ears, closed_ears, face_heights, gaze_ratios ,nose_y_coords= [], [], [], [],[]
    frame_count = 0
    calibration_stage = "OPEN_EYES"

    while cap.isOpened() and calibration_stage != "DONE":
        ret, frame = cap.read()
        if not ret: break
        
        frame = cv2.flip(frame, 1)
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = face_mesh.process(rgb_frame)

        if results.multi_face_landmarks:
            for face_landmarks in results.multi_face_landmarks:
                landmarks = face_landmarks.landmark
                avg_ear = (calculate_ear(landmarks, LEFT_EYE_INDICES) + calculate_ear(landmarks, RIGHT_EYE_INDICES)) / 2.0
                
                if calibration_stage == "OPEN_EYES":
                    if frame_count < CALIBRATION_FRAMES_OPEN:
                        open_ears.append(avg_ear)
                        face_heights.append(abs(landmarks[CHIN_LANDMARK].y - landmarks[FOREHEAD_LANDMARK].y))
                        total_eye_dist = landmarks[RIGHT_EYE_CORNER].x - landmarks[LEFT_EYE_CORNER].x
                        nose_y_coords.append(landmarks[NOSE_TIP_LANDMARK].y)
                        gaze_ratios.append((landmarks[NOSE_TIP_LANDMARK].x - landmarks[LEFT_EYE_CORNER].x) / (total_eye_dist + 1e-6))
                        frame_count += 1
                        cv2.putText(frame, f"Keep eyes open: {frame_count}/{CALIBRATION_FRAMES_OPEN}", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                    else:
                        calibration_stage = "BLINK"; frame_count = 0
                
                elif calibration_stage == "BLINK":
                    if frame_count < CALIBRATION_FRAMES_BLINK:
                        closed_ears.append(avg_ear)
                        frame_count += 1
                        cv2.putText(frame, f"Now blink normally: {frame_count}/{CALIBRATION_FRAMES_BLINK}", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)
                    else:
                        calibration_stage = "DONE"

        cv2.imshow('Calibration', frame)
        if cv2.waitKey(1) & 0xFF == ord('q'): break

    cap.release()
    cv2.destroyAllWindows()

    if open_ears and closed_ears:
        avg_open_ear = np.mean(open_ears)
        avg_closed_ear = np.mean(closed_ears)
        ear_threshold = (avg_open_ear + avg_closed_ear) / 2.0
        avg_face_height = np.mean(face_heights)
        avg_gaze_ratio = np.mean(gaze_ratios)
        avg_nose_y = np.mean(nose_y_coords)
        
        save_calibration_profile(ear_threshold, avg_open_ear, avg_face_height, avg_gaze_ratio,avg_nose_y)
        print("[INFO] Calibration successful.")
    else:
        print("[ERROR] Calibration failed. Not enough data collected.")

# --- Main Monitoring Loop ---
# --- Main Monitoring Loop ---
def run_monitoring_loop():
    global monitoring_active, yawn_count, blink_count, active_time_sec, idle_time_sec, blink_rate_bpm, is_gaze_centered, user_status, last_status_change_time, current_session_id, session_start_time_iso,drowsiness_score
    
    yawn_count = 0; blink_count = 0; active_time_sec = 0; idle_time_sec = 0
    blink_rate_bpm = 0; is_gaze_centered = False; user_status = "Active"
    last_status_change_time = time.time()
    
    current_session_id, session_start_time_iso = start_new_session()
    log_event(current_session_id, "SESSION_START")

    cap = cv2.VideoCapture(0)
    
    EAR_THRESHOLD, avg_open_ear, avg_face_height, avg_center_gaze,avg_nose_y = load_calibration_profile()
    if not (EAR_THRESHOLD and avg_open_ear and avg_face_height > 0 and avg_center_gaze > 0 and avg_nose_y > 0):
        print("[WARNING] Calibration profile not found or incomplete. Using default values.")
        EAR_THRESHOLD = 0.20
    
    user_settings = wellness_assistant.get_user_settings(DB_FILE)
    work_duration_min = 20 # Default value
    if user_settings:
        freq = user_settings.get('notify_frequency')
        if freq is not None:
            work_duration_min = int(freq)
    print(f"[INFO] Break reminder frequency set to {work_duration_min} minutes.")

    last_blink_time = time.time(); on_break = False; last_break_time = time.time()
    eye_state = "OPEN"; time_eye_closed_start = 0; last_drowsiness_alert_time = 0; yawn_start_time = 0
    blink_timestamps = deque(maxlen=int(BLINK_RATE_WINDOW_SEC*1.5))
    last_no_blink_alert_time = 0; last_low_blink_rate_alert_time = 0
    ear_history = deque(maxlen=5)
    time_no_face_start = 0; last_summary_log_time = 0
    gaze_centered_frame_counter = 0 
    last_score_decay_time = time.time()
    y_delta = 0 # Initialize y_delta
    
    try:
        while cap.isOpened() and monitoring_active:
            ret, frame = cap.read()
            if not ret: break
            frame = cv2.flip(frame, 1); h, w, _ = frame.shape; rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB); results = face_mesh.process(rgb_frame); current_time = time.time()
            avg_ear = 0.0
            is_head_tilted_vertically = False # Reset on each frame
            
            if on_break:
                time_left = BREAK_DURATION_SEC - (current_time - break_start_time)
                if time_left > 0:
                    cv2.putText(frame, "BREAK TIME!", (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 255, 255), 3); cv2.putText(frame, f"Resuming in: {int(time_left)}s", (50, 150), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2); cv2.imshow('Eye Monitoring', frame)
                    if cv2.waitKey(1) & 0xFF == ord('q'): monitoring_active = False
                    continue
                else: on_break = False; last_break_time = current_time

            if results.multi_face_landmarks:
                if user_status == "Idle":
                    idle_duration = current_time - last_status_change_time; idle_time_sec += idle_duration; log_event(current_session_id, "USER_ACTIVE_RESUME", value_numeric=idle_duration); print(f"[INFO] User returned after {int(idle_duration)}s. Resuming monitoring."); speak_threaded("Welcome back.")
                    last_blink_time = current_time; last_break_time = current_time; last_status_change_time = current_time
                user_status = "Active"; time_no_face_start = 0
                
                for face_landmarks in results.multi_face_landmarks:
                    landmarks = face_landmarks.landmark
                    avg_ear = (calculate_ear(landmarks, LEFT_EYE_INDICES) + calculate_ear(landmarks, RIGHT_EYE_INDICES)) / 2.0; ear_history.append(avg_ear)
                    left_eye_x = landmarks[LEFT_EYE_CORNER].x; right_eye_x = landmarks[RIGHT_EYE_CORNER].x; nose_x = landmarks[NOSE_TIP_LANDMARK].x; total_eye_dist = right_eye_x - left_eye_x; gaze_ratio = (nose_x - left_eye_x) / (total_eye_dist + 1e-6)
                    is_looking_away_horizontally = True
                    if avg_center_gaze > 0:
                        GAZE_CALIBRATED_TOLERANCE = 0.26; gaze_min_threshold = avg_center_gaze - GAZE_CALIBRATED_TOLERANCE; gaze_max_threshold = avg_center_gaze + GAZE_CALIBRATED_TOLERANCE
                        is_looking_away_horizontally = not (gaze_min_threshold < gaze_ratio < gaze_max_threshold)
                    
                    current_nose_y = landmarks[NOSE_TIP_LANDMARK].y
                    y_delta = current_nose_y - avg_nose_y

                    is_head_tilted_down = y_delta > (avg_face_height * HEAD_TILT_DOWN_THRESHOLD_PERCENT)
                    is_head_tilted_up = y_delta < -(avg_face_height * HEAD_TILT_UP_THRESHOLD_PERCENT)

                    is_head_tilted_vertically = is_head_tilted_down
                    is_gaze_centered = not (is_looking_away_horizontally or is_head_tilted_down or is_head_tilted_up)
                    
                    if (current_time - last_break_time) > (work_duration_min * 60):
                        if should_send_notification('break'):
                            alert_msg = f"Time for a {BREAK_DURATION_SEC}-second break!"; send_notification_threaded("Take a Break!", alert_msg); speak_threaded("It's time for a short eye break.")
                        on_break = True; break_start_time = current_time; log_event(current_session_id, "20_20_20_BREAK_TAKEN"); continue
                    
                    mar = calculate_mar(landmarks)
                    if mar > YAWN_MAR_THRESHOLD:
                        if yawn_start_time == 0:
                            yawn_start_time = current_time
                        elif yawn_start_time > 0 and (current_time - yawn_start_time) > YAWN_DURATION_SEC:
                            yawn_count += 1
                            drowsiness_score += SCORE_INCREMENT_YAWN
                            log_event(current_session_id, "YAWN_DETECTED")
                            print(f"[SCORE] Yawn! Score is now: {drowsiness_score}")
                            yawn_start_time = -1
                    else:
                        yawn_start_time = 0

                    if is_gaze_centered:
                        gaze_centered_frame_counter += 1
                    else:
                        gaze_centered_frame_counter = 0
                        eye_state = "OPEN"
                        time_eye_closed_start = 0
                        last_blink_time = current_time

                    if gaze_centered_frame_counter > GAZE_STABILITY_THRESHOLD_FRAMES:
                        ear_velocity = ear_history[-1] - ear_history[-2]
                        if eye_state == "OPEN" and ear_velocity < EAR_VELOCITY_THRESHOLD: eye_state = "CLOSING"
                        elif eye_state == "CLOSING" and avg_ear < EAR_THRESHOLD: blink_count += 1; last_blink_time = current_time; blink_timestamps.append(current_time); log_event(current_session_id, "BLINK"); eye_state = "CLOSED"; time_eye_closed_start = current_time
                        elif eye_state == "CLOSED" and avg_ear > (EAR_THRESHOLD * 1.1):
                            eye_state = "OPEN"
                            blink_duration_ms = (current_time - time_eye_closed_start) * 1000
                            if blink_duration_ms > MICRO_SLEEP_THRESHOLD_MS:
                                if is_head_tilted_vertically:
                                    drowsiness_score += SCORE_INCREMENT_LONG_BLINK
                                    log_event(current_session_id, "MICRO_SLEEP_DETECTED", value_numeric=blink_duration_ms)
                                    print(f"[SCORE] Head Nod + Long Blink! Score is now: {drowsiness_score}")
                                else:
                                    print(f"[INFO] Long blink ignored (no head nod). Duration: {int(blink_duration_ms)}ms")
                            time_eye_closed_start = 0
                        
                        time_since_last_blink = current_time - last_blink_time
                        if time_since_last_blink > NO_BLINK_THRESHOLD_SEC and (current_time - last_no_blink_alert_time) > NOTIFICATION_DEBOUNCE_SEC:
                            log_event(current_session_id, "STARE_ALERT_TRIGGERED", value_numeric=time_since_last_blink)
                            if should_send_notification('stare'):
                                send_notification_threaded("Eye Strain Warning!", f"No blink for {int(time_since_last_blink)}+ seconds!"); speak_threaded("Please blink your eyes.")
                            last_no_blink_alert_time = current_time
                        
                        while blink_timestamps and blink_timestamps[0] < current_time - BLINK_RATE_WINDOW_SEC: blink_timestamps.popleft()
                        blink_rate_bpm = (len(blink_timestamps) / BLINK_RATE_WINDOW_SEC) * 60 if BLINK_RATE_WINDOW_SEC > 0 else 0
                        
                        if (current_time - last_break_time) > BLINK_RATE_WINDOW_SEC and blink_rate_bpm < LOW_BLINK_RATE_THRESHOLD and len(blink_timestamps) > 1 and (current_time - last_low_blink_rate_alert_time) > NOTIFICATION_DEBOUNCE_SEC:
                            log_event(current_session_id, "LOW_BPM_ALERT_TRIGGERED", value_numeric=blink_rate_bpm)
                            if should_send_notification('low_bpm'):
                                send_notification_threaded("Low Blink Rate", f"Low blink rate ({int(blink_rate_bpm)} BPM)."); speak_threaded("Your blink rate is low.")
                            last_low_blink_rate_alert_time = current_time

                    # SCORE DECAY & MASTER ALERT (applies regardless of gaze stability)
                    if (current_time - last_score_decay_time) > SCORE_DECAY_INTERVAL_SEC:
                        if drowsiness_score > 0:
                            drowsiness_score = max(0, drowsiness_score - SCORE_DECAY_RATE)
                        last_score_decay_time = current_time

                    if drowsiness_score >= DROWSINESS_SCORE_THRESHOLD:
                        if (current_time - last_drowsiness_alert_time) > DROWSINESS_ALERT_DEBOUNCE_SEC:
                            alert_msg = f"High fatigue score: {drowsiness_score}. Consider taking a break."
                            if should_send_notification('drowsiness'):
                                send_notification_threaded("Fatigue Alert!", alert_msg)
                                speak_threaded("High level of fatigue detected. Please consider taking a break.")
                            log_event(current_session_id, "FATIGUE_SCORE_ALERT", value_numeric=drowsiness_score)
                            last_drowsiness_alert_time = current_time

                    if (current_time - last_summary_log_time) > SUMMARY_LOG_INTERVAL_SEC: 
                        log_event(current_session_id, "SUMMARY_EAR", value_numeric=avg_ear)
                        log_event(current_session_id, "SUMMARY_BPM", value_numeric=blink_rate_bpm)
                        last_summary_log_time = current_time
            else: 
                if time_no_face_start == 0: time_no_face_start = current_time
                elif (current_time - time_no_face_start) > IDLE_TIME_THRESHOLD_SEC:
                    if user_status == "Active":
                        active_duration = current_time - last_status_change_time; active_time_sec += active_duration; log_event(current_session_id, "USER_IDLE_START", value_numeric=active_duration); print("[INFO] User is idle. Pausing monitoring."); speak_threaded("Monitoring paused."); user_status = "Idle"; last_status_change_time = current_time
            
            instruction_text = "Monitoring Active (Press 'q' in this window to stop)"
            cv2.putText(frame, instruction_text, (30, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
            gaze_text = "Gaze: Centered" if is_gaze_centered else "Gaze: Away"; gaze_color = (0, 255, 0) if is_gaze_centered else (0, 0, 255)
            cv2.putText(frame, gaze_text, (w - 200, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, gaze_color, 2)
            cv2.putText(frame, f"Blinks: {blink_count}", (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
            cv2.putText(frame, f"EAR: {avg_ear:.2f}", (30, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            cv2.putText(frame, f"BPM: {int(blink_rate_bpm)}", (30, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
            cv2.putText(frame, f"Yawns: {yawn_count}", (w - 200, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (128, 0, 128), 2)
            cv2.putText(frame, f"Fatigue Score: {drowsiness_score}", (w - 250, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)
            
            tilt_text = "Head Tilted: YES" if is_head_tilted_vertically else "Head Tilted: NO"
            tilt_color = (0, 0, 255) if is_head_tilted_vertically else (0, 255, 0)
            cv2.putText(frame, tilt_text, (w - 250, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.7, tilt_color, 2)
            
            up_threshold = -(avg_face_height * HEAD_TILT_UP_THRESHOLD_PERCENT)
            debug_text = f"Y Delta: {y_delta:.3f} / Up Threshold: {up_threshold:.3f}"
            cv2.putText(frame, debug_text, (30, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)

            cv2.imshow('Eye Monitoring', frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                monitoring_active = False

    finally:
        print("\n[INFO] Monitoring loop stopped. Finalizing session data.")
        if user_status == "Active":
            active_time_sec += time.time() - last_status_change_time
        else:
            idle_time_sec += time.time() - last_status_change_time
        
        end_time_iso = datetime.now().isoformat()
        log_event(current_session_id, "SESSION_END")
        end_session(current_session_id, active_time_sec, idle_time_sec, end_time_iso)
        
        summary_report = wellness_assistant.generate_session_summary(
            session_id=current_session_id,
            start_time_str=session_start_time_iso,
            end_time_str=end_time_iso,
            db_path=DB_FILE
        )
        print(json.dumps(summary_report, indent=4))

        cap.release()
        cv2.destroyAllWindows()
        if PYTTSX_AVAILABLE:
            engine.stop()
# --- Flask Web Server ---
app = Flask(__name__, template_folder='templates', static_folder='static')

@app.route('/')
def dashboard():
    return render_template('dashboard.html')

@app.route('/api/check_calibration', methods=['GET'])
def check_calibration():
    is_calibrated = os.path.exists(CONFIG_FILE)
    return jsonify({'is_calibrated': is_calibrated})

@app.route('/api/start_calibration', methods=['POST'])
def start_calibration():
    data = request.get_json()
    user_name = data.get('user_name') if data else None
    calibration_thread = threading.Thread(target=run_calibration_process, args=(user_name,), daemon=True)
    calibration_thread.start()
    calibration_thread.join() # This line waits for the calibration to finish
    if os.path.exists(CONFIG_FILE):
        return jsonify({'status': 'complete', 'message': 'Calibration successful.'})
    else:
        return jsonify({'status': 'failed', 'message': 'Calibration failed to save profile.'}), 500

@app.route('/api/start_monitoring', methods=['POST'])
def start_monitoring():
    global monitoring_active, monitoring_thread
    if not monitoring_active:
        monitoring_active = True
        monitoring_thread = threading.Thread(target=run_monitoring_loop, daemon=True)
        monitoring_thread.start()
        print("[INFO] Monitoring session started via API.")
        return jsonify({'status': 'Monitoring started'})
    return jsonify({'status': 'Monitoring is already active'})

@app.route('/api/stop_monitoring', methods=['POST'])
def stop_monitoring():
    global monitoring_active, current_session_id, monitoring_thread
    if monitoring_active:
        ended_session_id = current_session_id
        monitoring_active = False
        
        if monitoring_thread is not None:
            monitoring_thread.join()

        print("[INFO] Monitoring session stopped and data finalized via API.")
        return jsonify({'status': 'Monitoring stopped', 'session_id': ended_session_id})
    return jsonify({'status': 'No active monitoring session'})

@app.route('/api/stats')
def get_stats():
    live_data = {
        'blinks': blink_count, 
        'active_time': int(active_time_sec + (time.time() - last_status_change_time if user_status == "Active" else 0)),
        'bpm': int(blink_rate_bpm),
        'yawns': yawn_count,
        'gaze_status': "Centered" if is_gaze_centered else "Away",
        'fatigue_score': drowsiness_score
    }
    return jsonify(live_data)

@app.route('/api/summary_stats')
def get_summary_stats():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("SELECT value_numeric FROM events WHERE event_type = 'SUMMARY_BPM' AND value_numeric > 0")
    bpm_records = cursor.fetchall()
    avg_bpm = np.mean([r[0] for r in bpm_records]) if bpm_records else 15
    health_score = min(100, int((avg_bpm / 20.0) * 100))
    cursor.execute("SELECT strftime('%H', timestamp) as hour FROM events WHERE event_type IN ('YAWN_DETECTED', 'MICRO_SLEEP_DETECTED', 'FATIGUE_SCORE_ALERT')")
    fatigue_hours = [int(r[0]) for r in cursor.fetchall()]
    fatigue_hotspots = defaultdict(int)
    for hour in fatigue_hours: fatigue_hotspots[hour] += 1
    cursor.execute("SELECT strftime('%H', timestamp) as hour FROM events WHERE event_type = 'SUMMARY_EAR'")
    activity_hours = [int(r[0]) for r in cursor.fetchall()]
    activity_clock = defaultdict(int)
    for hour in activity_hours: activity_clock[hour] += 1
    current_streak = calculate_current_streak(conn)
    conn.close()
    return jsonify({
        'health_score': health_score, 
        'avg_blink_rate': int(avg_bpm), 
        'fatigue_hotspots': dict(fatigue_hotspots), 
        'activity_clock': dict(activity_clock),
        'current_streak': current_streak
    })

@app.route('/api/weekly_report')
def get_weekly_report():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    cursor = conn.cursor()
    one_week_ago = (datetime.now() - timedelta(days=7)).isoformat()
    cursor.execute("SELECT strftime('%Y-%m-%d', start_time) as day, SUM(total_active_time_sec) FROM sessions WHERE start_time >= ? GROUP BY day", (one_week_ago,))
    daily_activity = cursor.fetchall()
    conn.close()
    report_data = {'labels': [datetime.strptime(day, '%Y-%m-%d').strftime('%a') for day, sec in daily_activity], 'data': [round(sec / 3600, 1) if sec else 0 for day, sec in daily_activity]}
    return jsonify(report_data)

@app.route('/api/session_report/<int:session_id>')
def get_session_report(session_id):
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT start_time, end_time FROM sessions WHERE session_id = ?", (session_id,))
        session_times = cursor.fetchone()
        conn.close()

        if not session_times:
            return jsonify({"error": "Session not found"}), 404
        
        start_time, end_time = session_times
        
        report = wellness_assistant.generate_session_summary(
            session_id=session_id,
            start_time_str=start_time,
            end_time_str=end_time,
            db_path=DB_FILE
        )
        return jsonify(report)
    except Exception as e:
        print(f"[ERROR] Could not generate session report for ID {session_id}: {e}")
        return jsonify({"error": "Failed to generate report"}), 500

@app.route('/api/get_settings', methods=['GET'])
def get_settings():
    try:
        conn = sqlite3.connect(DB_FILE); conn.row_factory = sqlite3.Row; cursor = conn.cursor()
        cursor.execute("SELECT * FROM settings WHERE id = 1"); settings_row = cursor.fetchone(); conn.close()
        if settings_row: return jsonify(dict(settings_row))
        else: return jsonify({"goal_blink_rate": 20, "goal_breaks": 5, "enable_weekly_goals": True, "enable_daily_streak": False, "master_notifications": True, "notify_blink": True, "notify_break": True, "notify_frequency": 30, "active_start_time": "09:00", "active_end_time": "17:00"})
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/api/save_settings', methods=['POST'])
def save_settings():
    try:
        new_settings = request.get_json(); conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO settings (
                id, user_name, goal_blink_rate, goal_breaks, 
                enable_weekly_goals, enable_daily_streak, master_notifications, 
                notify_blink, notify_break, notify_frequency, 
                active_start_time, active_end_time
            ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            new_settings.get('userName'), new_settings.get('goalBlinkRate'),
            new_settings.get('goalBreaks'), new_settings.get('enableWeeklyGoals'), 
            new_settings.get('enableDailyStreak'), new_settings.get('masterNotifications'), 
            new_settings.get('notifyBlink'), new_settings.get('notifyBreak'), 
            new_settings.get('notifyFrequency'), new_settings.get('activeStartTime'), 
            new_settings.get('activeEndTime')
        ))
        conn.commit(); conn.close()
        return jsonify({"status": "success", "message": "Settings saved."}), 200
    except Exception as e: return jsonify({"error": str(e)}), 500
@app.route('/api/chat', methods=['POST'])
def chat_with_gemini():
    global conversation_history # Access the global list
    try:
        user_message = request.json['message']
        
        # Add the user's message to the history
        conversation_history.append(f"User: {user_message}")

        # Limit history to the last 10 messages to keep the prompt size reasonable
        if len(conversation_history) > 20:
            conversation_history = conversation_history[-20:]
            
        # Format the history for the prompt
        history_for_prompt = "\n".join(conversation_history)

        # --- Your existing code to get user data ---
        conn = sqlite3.connect(DB_FILE, check_same_thread=False); cursor = conn.cursor()
        cursor.execute("SELECT user_name FROM settings WHERE id = 1")
        user_name_result = cursor.fetchone()
        user_name = user_name_result[0] if user_name_result and user_name_result[0] else "friend"
        cursor.execute("SELECT value_numeric FROM events WHERE event_type = 'SUMMARY_BPM' AND value_numeric > 0")
        bpm_records = cursor.fetchall()
        avg_bpm = np.mean([r[0] for r in bpm_records]) if bpm_records else 15
        health_score = min(100, int((avg_bpm / 20.0) * 100))
        cursor.execute("SELECT strftime('%H', timestamp) as hour, COUNT(*) as count FROM events WHERE event_type IN ('YAWN_DETECTED', 'MICRO_SLEEP_DETECTED', 'FATIGUE_SCORE_ALERT') GROUP BY hour ORDER BY count DESC LIMIT 1")
        hotspot_result = cursor.fetchone()
        fatigue_hotspot_hour = f"{hotspot_result[0]}:00" if hotspot_result else "Not enough data"
        conn.close()
        user_stats = { "avg_bpm": int(avg_bpm), "health_score": health_score, "fatigue_hotspot_hour": fatigue_hotspot_hour }
        
        # --- Updated prompt with conversation history ---
        prompt = f"""
        You are DrishtiAI, a gentle and supportive wellness companion. Your user's name is {user_name}.

        Core Identity:
        - You ARE DrishtiAI. Do not introduce yourself in every message. Assume the user knows who you are.
        - Your tone is always warm, empathetic, and kind, like a caring friend.
        - You are capable of answering general knowledge questions, but always try to gently guide the conversation back to wellness, well-being, or your core functionalities.

        This is the recent conversation history:
        {history_for_prompt}

        User's NEW Message: "{user_message}"

        Context Data (Only use if relevant to the conversation):
        - Average Blink Rate: {user_stats['avg_bpm']} BPM
        - Screen Health Score: {user_stats['health_score']}/100
        - Common Fatigue Time: {user_stats['fatigue_hotspot_hour']}

        Behavior Rules:
        - If the user sounds stressed or tired, respond with calming and reassuring words. Offer a simple breathing exercise.
        - If the user sounds happy, match their energy with light, encouraging, and slightly playful support.
        - If the user asks a factual question that is NOT directly related to wellness (e.g., "who is X?", "what is Y?"), answer it concisely and accurately. After answering, gently pivot back to their well-being or offer a wellness tip. For example: "X is [brief explanation]. Speaking of focus, how are your eyes feeling today, {user_name}?" or "Y is [brief explanation]. Remember to take short breaks for your eyes throughout the day!"
        - If the user's message is unclear, gibberish, or just a simple greeting, respond with a gentle check-in. Examples: "Hey {user_name}, how's your energy today?" or "Everything okay? I'm here to listen."
        - NEVER respond to unclear messages by re-introducing yourself.
        - Be concise. Keep your replies to 2-3 short sentences.
        - Avoid using the user's name({user_name}) repeatedly. Only use it at the start of a conversation or when absolutely necessary — such as in emotionally significant moments or when clearly addressing the user in a group or public setting. In normal back-and-forth replies, do not use the name at all. Overuse feels robotic and insincere.
        """
        
        response = model.generate_content(prompt)
        
        # Add the bot's response to the history, with error checking
        bot_reply = ""
        if response.parts:
            bot_reply = response.text
        else:
            bot_reply = "I'm sorry, I couldn't generate a response for that. It may have triggered my safety filters."
            print("[ERROR] Gemini response was blocked or empty.")

        conversation_history.append(f"AI: {bot_reply}")

        return jsonify({'reply': bot_reply})
        
    except Exception as e:
        print(f"[ERROR] Gemini API call failed: {e}")
        return jsonify({'reply': "Sorry, I'm having trouble connecting to the AI service right now. Please try again later."}), 500

def run_flask_app():
    # This line triggers the browser to open automatically
    webbrowser.open_new_tab('http://127.0.0.1:5000') 
    app.run(port=5000, debug=False, use_reloader=False)

# --- Main Execution Block ---
if __name__ == '__main__':
    if not os.path.exists(DB_FILE):
        print("[INFO] No database found. Creating a new one for this user.")
        setup_database()
    print("Application ready. Starting web server...")
    print("Open your browser to http://localhost:5000 to control the application.")
    run_flask_app()
    