import sqlite3
from datetime import datetime
import numpy as np

def get_user_settings(db_path):
    """
    Fetches the user's saved settings from the database.

    Args:
        db_path (str): The path to the SQLite database file.

    Returns:
        dict: A dictionary containing the user's settings, or None if not found.
    """
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row # Allows accessing columns by name
        cursor = conn.cursor()
        
        # Fetch the single row of settings
        cursor.execute("SELECT * FROM settings WHERE id = 1")
        settings_row = cursor.fetchone()
        
        if settings_row:
            return dict(settings_row)
        return None
            
    except sqlite3.Error as e:
        # This can happen if the table doesn't exist yet
        print(f"[INFO] Could not fetch settings, table might not exist yet: {e}")
        return None
    finally:
        if conn:
            conn.close()


def get_historical_averages(db_path, current_session_id):
    """
    Calculates a more robust historical average for key wellness metrics by
    averaging the results of the most recent 20 past sessions.
    """
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT session_id, total_active_time_sec 
            FROM sessions 
            WHERE end_time IS NOT NULL AND session_id != ?
            ORDER BY start_time DESC 
            LIMIT 20
        """, (current_session_id,))
        
        past_sessions = cursor.fetchall()

        if not past_sessions:
            return None

        session_bpms = []
        session_stares = []
        session_fatigue_events = [] # New combined list

        for session_id, active_time_sec in past_sessions:
            if active_time_sec < 30:
                continue

            cursor.execute("SELECT event_type, COUNT(*) FROM events WHERE session_id = ? GROUP BY event_type", (session_id,))
            events = dict(cursor.fetchall())
            
            blinks = events.get('BLINK', 0)
            active_minutes = active_time_sec / 60.0
            bpm = blinks / active_minutes if active_minutes > 0 else 0
            session_bpms.append(bpm)
            
            session_stares.append(events.get('STARE_ALERT_TRIGGERED', 0))
            
            # Combine all fatigue events into one metric
            fatigue_count = events.get('MICRO_SLEEP_DETECTED', 0) + events.get('YAWN_DETECTED', 0) + events.get('FATIGUE_SCORE_ALERT', 0)
            session_fatigue_events.append(fatigue_count)

        if not session_bpms:
            return None

        historical_data = {
            "session_count": len(session_bpms),
            "avg_bpm": np.mean(session_bpms),
            "avg_stare_alerts": np.mean(session_stares),
            "avg_fatigue_events": np.mean(session_fatigue_events) # New combined average
        }
        
        return historical_data

    except sqlite3.Error as e:
        print(f"[ERROR] Database error in get_historical_averages: {e}")
        return None
    finally:
        if conn:
            conn.close()

def generate_session_summary(session_id, start_time_str, end_time_str, db_path="monitoring_data.db"):
    """
    Analyzes a session and returns a structured JSON report with insights
    and status indicators for frontend rendering.
    """
    report_data = {
        "session_id": session_id,
        "error": None,
        "goal_achievement": {},
        "performance": {}
    }
    conn = None

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # --- 1. Fetch Session Data ---
        cursor.execute("SELECT total_active_time_sec FROM sessions WHERE session_id = ?", (session_id,))
        result = cursor.fetchone()
        total_seconds = result[0] if result else 0
        
        if total_seconds < 30:
            report_data["error"] = "Session was too short to generate a meaningful wellness report."
            return report_data

        minutes, seconds = divmod(total_seconds, 60)
        report_data["active_time_str"] = f"{minutes} minutes, {seconds} seconds"
        active_minutes = total_seconds / 60.0
        
        cursor.execute("SELECT event_type, COUNT(*) FROM events WHERE session_id = ? GROUP BY event_type", (session_id,))
        current_events = dict(cursor.fetchall())
        
        current_blinks = current_events.get('BLINK', 0)
        current_bpm = (current_blinks / active_minutes) if active_minutes > 0 else 0
        current_stares = current_events.get('STARE_ALERT_TRIGGERED', 0)
        
        # New: Combine all fatigue events for the current session
        current_fatigue_events = current_events.get('MICRO_SLEEP_DETECTED', 0) + current_events.get('YAWN_DETECTED', 0) + current_events.get('FATIGUE_SCORE_ALERT', 0)

        # --- 2. Fetch User Settings & Check Goals ---
        user_settings = get_user_settings(db_path)
        if user_settings and user_settings['enable_weekly_goals']:
            goal_bpm = user_settings.get('goal_blink_rate')
            if goal_bpm is not None and goal_bpm > 0:
                if current_bpm >= goal_bpm:
                    report_data["goal_achievement"]["blink_rate"] = {
                        "status": "good",
                        "text": f"ACHIEVED! (Your avg of {current_bpm:.1f} BPM met the {goal_bpm} BPM target)"
                    }
                else:
                    report_data["goal_achievement"]["blink_rate"] = {
                        "status": "warning",
                        "text": f"In Progress. (Your avg was {current_bpm:.1f} BPM, goal is {goal_bpm} BPM)"
                    }
        
        # --- 3. Get Historical Averages & Generate Insights ---
        history = get_historical_averages(db_path, session_id)
        
        # Blink Rate
        bpm_data = {"session": f"{current_bpm:.1f} BPM", "historical": "N/A", "insight": "Complete more sessions for historical insights.", "status": "neutral"}
        if history:
            bpm_data["historical"] = f"{history['avg_bpm']:.1f} BPM"
            if current_bpm > history['avg_bpm'] * 1.15:
                bpm_data["insight"] = "Your blink rate was significantly higher than usual. Great job!"
                bpm_data["status"] = "good"
            elif current_bpm < history['avg_bpm'] * 0.85:
                bpm_data["insight"] = "Your blink rate was significantly lower than usual. Remember to blink more often."
                bpm_data["status"] = "warning"
        report_data["performance"]["blink_rate"] = bpm_data

        # NEW: Unified Fatigue Events
        fatigue_data = {"session": current_fatigue_events, "historical": "N/A", "insight": "", "status": "neutral"}
        if history:
            fatigue_data["historical"] = f"{history['avg_fatigue_events']:.1f}"
            if history['avg_fatigue_events'] > 0 and current_fatigue_events < history['avg_fatigue_events']:
                fatigue_data["insight"] = "You had fewer fatigue events than usual. Great job staying alert!"
                fatigue_data["status"] = "good"
            elif current_fatigue_events > history['avg_fatigue_events'] and current_fatigue_events > 1:
                fatigue_data["insight"] = "You had more fatigue events than usual. Consider taking more breaks."
                fatigue_data["status"] = "warning"
        report_data["performance"]["fatigue_events"] = fatigue_data

        # Stare Alerts
        stare_data = {"session": current_stares, "historical": "N/A", "insight": "", "status": "neutral"}
        if history:
            stare_data["historical"] = f"{history['avg_stare_alerts']:.1f}"
            if current_stares > history['avg_stare_alerts'] and current_stares > 1:
                stare_data["insight"] = "You had more moments of intense focus. Remember the 20-20-20 rule."
                stare_data["status"] = "warning"
        report_data["performance"]["stares"] = stare_data
        
        return report_data

    except sqlite3.Error as e:
        report_data["error"] = f"Database error: {e}"
        return report_data
    finally:
        if conn:
            conn.close()
