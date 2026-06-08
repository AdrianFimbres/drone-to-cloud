import sqlite3
import json
import re
from datetime import datetime, timezone
from flask import Flask, request, jsonify

DB_NAME = 'telemetry.db'

def get_db_connection():
    """Helper to get a DB connection with Foreign Keys enabled."""
    conn = sqlite3.connect(DB_NAME)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    """Initializes the database and creates the relational tables if they don't exist."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS vehicles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vehicle_serial TEXT NOT NULL UNIQUE,
                name TEXT,
                created_at TEXT NOT NULL
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS flights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                flight_id TEXT NOT NULL UNIQUE,
                vehicle_serial TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                state TEXT NOT NULL DEFAULT 'FLYING',
                FOREIGN KEY (vehicle_serial) REFERENCES vehicles(vehicle_serial)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS telemetry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                flight_id TEXT NOT NULL,
                vehicle_serial TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                altitude_agl REAL NOT NULL,
                speed REAL NOT NULL,
                heading REAL,
                battery_level INTEGER NOT NULL,
                state TEXT NOT NULL DEFAULT 'FLYING',
                FOREIGN KEY (flight_id) REFERENCES flights(flight_id),
                FOREIGN KEY (vehicle_serial) REFERENCES vehicles(vehicle_serial)
            )
        ''')
        conn.commit()
    print(f"Database '{DB_NAME}' initialized.")

app = Flask(__name__)

def is_valid_iso8601_z(timestamp_str):
    """Strictly checks if a string is a valid ISO 8601 UTC timestamp ending in Z."""
    pattern = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$'
    return re.match(pattern, timestamp_str) is not None

@app.route('/api/telemetry', methods=['POST'])
def receive_telemetry():
    """API endpoint to receive and store drone telemetry data."""
    if not request.is_json:
        return jsonify({"status": "error", "message": "Invalid format: JSON required"}), 400
    
    data = request.get_json()
    
    required_fields = ['flight_id', 'vehicle_serial', 'timestamp', 'latitude', 'longitude', 'altitude_agl', 'speed', 'battery_level']
    missing_fields = [field for field in required_fields if data.get(field) is None]
    
    if missing_fields:
        return jsonify({"status": "error", "message": f"Missing required fields: {', '.join(missing_fields)}"}), 400
        
    if not is_valid_iso8601_z(data.get('timestamp')):
        return jsonify({"status": "error", "message": "Timestamp must be ISO 8601 UTC ending with 'Z'"}), 400

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR IGNORE INTO vehicles (vehicle_serial, created_at)
                VALUES (?, ?)
            ''', (data['vehicle_serial'], datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')))
            
            cursor.execute('''
                INSERT OR IGNORE INTO flights (flight_id, vehicle_serial, started_at, state)
                VALUES (?, ?, ?, ?)
            ''', (data['flight_id'], data['vehicle_serial'], data['timestamp'], data.get('state', 'FLYING')))
            
            cursor.execute('''
                INSERT INTO telemetry (
                    flight_id, vehicle_serial, timestamp, latitude, longitude, 
                    altitude_agl, speed, heading, battery_level, state
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                data['flight_id'], data['vehicle_serial'], data['timestamp'], 
                data['latitude'], data['longitude'], data['altitude_agl'], 
                data['speed'], data.get('heading'), data['battery_level'], data.get('state', 'FLYING')
            ))
            
            conn.commit()
            
        return jsonify({"status": "success", "message": "Telemetry processed"}), 201

    except Exception as e:
        print(f"[ERROR] Database insertion failed: {str(e)}") 
        return jsonify({"status": "error", "message": "Internal server error while saving telemetry."}), 500

@app.route('/', methods=['GET'])
def view_logs():
    """Displays all telemetry logs in a professional dark-mode HTML table."""
    try:
        with get_db_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT t.id, t.vehicle_serial, t.flight_id, t.timestamp, 
                       t.altitude_agl, t.speed, t.battery_level, t.state 
                FROM telemetry t
                JOIN flights f ON t.flight_id = f.flight_id
                ORDER BY t.id DESC LIMIT 50
            ''')
            rows = cursor.fetchall()

        html = """
        <html><head><style>
            body { 
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
                background-color: #121212; 
                color: #E0E0E0; 
                padding: 20px; 
            }
            h2 { color: #FFFFFF; font-weight: 300; }
            table { border-collapse: collapse; width: 100%; border: 1px solid #333; }
            th, td { padding: 12px 15px; text-align: left; border-bottom: 1px solid #333; }
            th { 
                background-color: #1F1F1F; 
                color: #FFFFFF; 
                font-weight: 600; 
                text-transform: uppercase; 
                letter-spacing: 0.5px; 
                font-size: 0.85rem;
            }
            tr:nth-child(even) { background-color: #1A1A1A; }
            tr:hover { background-color: #252525; }
        </style></head><body>
        <h2>Telemetry Dashboard</h2>
        <table><tr><th>ID</th><th>Vehicle</th><th>Flight ID</th><th>Time</th><th>Alt (AGL)</th><th>Speed</th><th>Bat %</th><th>State</th></tr>
        """
        for row in rows:
            html += f"<tr><td>{row['id']}</td><td>{row['vehicle_serial']}</td><td>{row['flight_id']}</td><td>{row['timestamp']}</td><td>{row['altitude_agl']}</td><td>{row['speed']}</td><td>{row['battery_level']}</td><td>{row['state']}</td></tr>"
        html += "</table></body></html>"
        return html
    except Exception as e:
        print(f"[ERROR] Failed to load dashboard: {str(e)}")
        return "<h2>Error loading dashboard</h2><p>Internal server error. Please check server logs.</p>", 500

if __name__ == '__main__':
    init_db()
    # NOTE: Debug mode is enabled to catch request handling errors
    app.run(host='0.0.0.0', debug=True, port=5000)
