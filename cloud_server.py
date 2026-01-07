import sqlite3
import json
from datetime import datetime
from flask import Flask, request, jsonify

# --- Creates the database ---
DB_NAME = 'telemetry.db'

def init_db():
    """Initializes the database and creates the 'logs' table if it doesn't exist."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                drone_id TEXT NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                battery_level INTEGER NOT NULL
            )
        ''')
        conn.commit()
        print(f"Database '{DB_NAME}' initialized.")

# --- Initializing Flask ---
app = Flask(__name__)

@app.route('/api/telemetry', methods=['POST'])
def receive_telemetry():
    """API endpoint to receive and store drone telemetry data."""
    if not request.is_json:
        return jsonify({"status": "error", "message": "Invalid format: JSON required"}), 400

    data = request.get_json()

    # Basic validation
    required_fields = ['drone_id', 'latitude', 'longitude', 'battery_level']
    if not all(field in data for field in required_fields):
        missing = [f for f in required_fields if f not in data]
        print(f"[{datetime.utcnow().isoformat()}] [ERROR] Invalid Payload. Missing fields: {missing}")
        return jsonify({"status": "error", "message": "Missing required fields"}), 400
    
    try:
        # Use context manager to ensure the database connection closes cleanly on errors
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()

            # If the drone sent a timestamp, use it. Otherwise, use server time.
            log_timestamp = data.get('timestamp', datetime.utcnow().isoformat())
            
            cursor.execute('''
                INSERT INTO logs (timestamp, drone_id, latitude, longitude, battery_level)
                VALUES (?, ?, ?, ?, ?)
            ''', (log_timestamp, data['drone_id'], data['latitude'], data['longitude'], data['battery_level']))
            
            new_log_id = cursor.lastrowid
            # Note: The context manager automatically commits on success, 
            # but explicit commit here is fine too.
            conn.commit()
            
        print(f"[{datetime.utcnow().isoformat()}] Received data from {data['drone_id']}")
        return jsonify({"status": "success", "id": new_log_id}), 201

    except Exception as e:
        print(f"[{datetime.utcnow().isoformat()}] Error processing request: {e}")
        return jsonify({"status": "error", "message": "Internal server error"}), 500

@app.route('/', methods=['GET'])
def view_logs():
    """Displays all telemetry logs in a simple HTML table."""
    try:
        with sqlite3.connect(DB_NAME) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM logs ORDER BY id DESC")
            rows = cursor.fetchall()

        # HTML section to show database in browser
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Drone Telemetry Logs</title>
            <style>
                body { font-family: sans-serif; margin: 2em; background: #f4f4f4; }
                table { border-collapse: collapse; width: 100%; }
                th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
                th { background-color: #007BFF; color: white; }
                tr:nth-child(even) { background-color: #f2f2f2; }
            </style>
        </head>
        <body>
            <h1>Drone Telemetry Logs</h1>
            <table>
                <tr>
                    <th>ID</th><th>Timestamp (UTC)</th><th>Drone ID</th>
                    <th>Latitude</th><th>Longitude</th><th>Battery (%)</th>
                </tr>
        """
        for row in rows:
            html += f"""
                <tr>
                    <td>{row['id']}</td><td>{row['timestamp']}</td><td>{row['drone_id']}</td>
                    <td>{row['latitude']}</td><td>{row['longitude']}</td><td>{row['battery_level']}</td>
                </tr>
            """
        html += "</table></body></html>"
        return html

    except Exception as e:
        return f"<h1>Error retrieving logs: {e}</h1>", 500

if __name__ == '__main__':
    init_db()
    # MODIFIED: Host set to 0.0.0.0 to allow external connections
    # NOTE: Debug mode is intentionally enabled to surface request handling errors
    # during diagnostics and failure reproduction.
    app.run(host='0.0.0.0', debug=True, port=5000)
