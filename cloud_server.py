import sqlite3
import json
import re
import threading
import time
import requests
import hmac
import hashlib
from datetime import datetime, timezone
from functools import wraps
from flask import Flask, request, jsonify

DB_NAME = 'telemetry.db'

VALID_TOKENS = {
    "token-rw-001": {"scope": "read_write"}, 
    "token-ro-002": {"scope": "read_only"}, 
}

WEBHOOK_URL = "http://127.0.0.1:5001/webhook"
WEBHOOK_SECRET = "super_secret_webhook_key"

# Format: flight_id -> {'last_state': str, 'last_seen': datetime, 
# 'battery_alerted': bool, 'stale_alerted': bool, 'vehicle_serial': str}
flight_states = {}

def send_webhook(event, flight_id, vehicle_serial, data):
    """Generates an HMAC-SHA256 signature and sends a webhook POST payload."""
    payload = {
        "event": event,
        "flight_id": flight_id,
        "vehicle_serial": vehicle_serial,
        "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "data": data
    }
    
    payload_bytes = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    
    signature = hmac.new(WEBHOOK_SECRET.encode('utf-8'), payload_bytes, hashlib.sha256).hexdigest()
    
    headers = {
        'Content-Type': 'application/json',
        'X-Webhook-Signature': f"sha256={signature}"
    }
    
    try:
        requests.post(WEBHOOK_URL, data=payload_bytes, headers=headers, timeout=3)
        print(f"[WEBHOOK] Dispatched '{event}' for {flight_id}")
    except requests.exceptions.RequestException as e:
        print(f"[WEBHOOK ERROR] Failed to deliver '{event}' to {WEBHOOK_URL}: {e}")

def stale_telemetry_monitor():
    """Background task to detect flight feeds that have gone dark (Rule 3)."""
    while True:
        now = datetime.now(timezone.utc)
        for flight_id, state_info in list(flight_states.items()):
            if not state_info.get('stale_alerted'):
                delta = (now - state_info['last_seen']).total_seconds()
                if delta > 30:
                    send_webhook(
                        event="vehicle.telemetry.stale",
                        flight_id=flight_id,
                        vehicle_serial=state_info['vehicle_serial'],
                        data={
                            "last_seen": state_info['last_seen'].strftime('%Y-%m-%dT%H:%M:%SZ'),
                            "seconds_since_last_telemetry": int(delta)
                        }
                    )
                    state_info['stale_alerted'] = True
        time.sleep(5)

def require_auth(f):
    """Checks Bearer token and scope before allowing access."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({"status": "error", "message": "Unauthorized"}), 401
            
        parts = auth_header.split(' ')
        if len(parts) != 2 or not parts[1]:
            return jsonify({"status": "error", "message": "Unauthorized"}), 401
            
        token = parts[1]
        
        if token not in VALID_TOKENS:
            return jsonify({"status": "error", "message": "Unauthorized"}), 401
            
        token_scope = VALID_TOKENS[token]["scope"]
        if request.method == 'POST' and token_scope == 'read_only':
            return jsonify({"status": "error", "message": "Forbidden: insufficient permissions"}), 403
            
        return f(*args, **kwargs)
    return decorated_function

def get_db_connection():
    """Helper to get a DB connection with Foreign Keys enabled."""
    conn = sqlite3.connect(DB_NAME)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    """Creates the database and schema if they don't exist."""
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
    """Validates ISO 8601 UTC timestamps."""
    pattern = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$'
    return re.match(pattern, timestamp_str) is not None

@app.route('/api/telemetry', methods=['POST'])
@require_auth
def receive_telemetry():
    """Receives and stores incoming telemetry."""
    if not request.is_json:
        return jsonify({"status": "error", "message": "Invalid format: JSON required"}), 400
    
    data = request.get_json()
    
    required_fields = ['flight_id', 'vehicle_serial', 'timestamp', 'latitude', 'longitude', 'altitude_agl', 'speed', 'battery_level']
    missing_fields = [field for field in required_fields if data.get(field) is None]
    
    if missing_fields:
        return jsonify({"status": "error", "message": f"Missing required fields: {', '.join(missing_fields)}"}), 400
        
    if not is_valid_iso8601_z(data.get('timestamp')):
        return jsonify({"status": "error", "message": "Timestamp must be ISO 8601 UTC ending with 'Z'"}), 400
    
    flight_id = data['flight_id']
    vehicle_serial = data['vehicle_serial']
    current_state = data.get('state', 'FLYING')
    battery = data['battery_level']

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

        now = datetime.now(timezone.utc)
        
        if flight_id not in flight_states:
            flight_states[flight_id] = {
                'last_state': current_state,
                'last_seen': now,
                'battery_alerted': False,
                'stale_alerted': False,
                'vehicle_serial': vehicle_serial
            }
            
        state_info = flight_states[flight_id]
        prev_state = state_info['last_state']
        
        state_info['last_seen'] = now
        state_info['last_state'] = current_state
        if state_info['stale_alerted']:
            state_info['stale_alerted'] = False 

        def evaluate_rules():
            if battery < 20 and not state_info.get('battery_alerted'):
                send_webhook("vehicle.battery.critical", flight_id, vehicle_serial, {
                    "battery_level": battery,
                    "latitude": data['latitude'],
                    "longitude": data['longitude']
                })
                state_info['battery_alerted'] = True
            elif battery >= 20:
                state_info['battery_alerted'] = False 

            if prev_state != current_state and current_state in ['LANDING', 'DOCKED']:
                send_webhook("vehicle.state.changed", flight_id, vehicle_serial, {
                    "previous_state": prev_state,
                    "new_state": current_state
                })
                
        threading.Thread(target=evaluate_rules).start()
            
        return jsonify({"status": "success", "message": "Telemetry processed"}), 201

    except Exception as e:
        print(f"[ERROR] Database insertion failed: {str(e)}") 
        return jsonify({"status": "error", "message": "Internal server error while saving telemetry."}), 500
    
@app.route('/api/flights', methods=['GET'])
@require_auth
def get_flights():
    """Returns all flights and their total telemetry row counts."""
    try:
        with get_db_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT f.flight_id, f.vehicle_serial, f.started_at, f.ended_at, f.state,
                       COUNT(t.id) as telemetry_count
                FROM flights f
                LEFT JOIN telemetry t ON f.flight_id = t.flight_id
                GROUP BY f.flight_id
                ORDER BY f.started_at DESC
            ''')
            rows = cursor.fetchall()
            
            flights = [dict(row) for row in rows]
            return jsonify({"flights": flights}), 200
            
    except Exception as e:
        print(f"[ERROR] Failed to fetch flights: {str(e)}")
        return jsonify({"status": "error", "message": "Internal server error."}), 500
    
@app.route('/api/flight/<flight_id>/telemetry', methods=['GET'])
@require_auth
def get_flight_telemetry(flight_id):
    """Returns all telemetry for a given flight."""
    try:
        with get_db_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('SELECT flight_id FROM flights WHERE flight_id = ?', (flight_id,))
            if not cursor.fetchone():
                return jsonify({"status": "error", "message": "Flight not found"}), 404
                
            cursor.execute('''
                SELECT timestamp, latitude, longitude, altitude_agl, speed, 
                       heading, battery_level, state
                FROM telemetry
                WHERE flight_id = ?
                ORDER BY timestamp ASC
            ''', (flight_id,))
            rows = cursor.fetchall()
            
            telemetry = [dict(row) for row in rows]
            return jsonify({
                "flight_id": flight_id,
                "telemetry": telemetry
            }), 200
            
    except Exception as e:
        print(f"[ERROR] Failed to fetch telemetry for flight {flight_id}: {str(e)}")
        return jsonify({"status": "error", "message": "Internal server error."}), 500

@app.route('/', methods=['GET'])
# NOTE: Intentionally left unauthenticated for visual dashboard debugging
def view_logs():
    """Renders the last 50 telemetry records as an HTML dashboard."""
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
            .api-links {
                background-color: #1A1A1A;
                padding: 15px;
                border: 1px solid #333;
                border-radius: 4px;
                margin-bottom: 20px;
                font-size: 0.9rem;
            }
            .api-links a { color: #4CAF50; text-decoration: none; margin-right: 20px; font-weight: 600; }
            .api-links a:hover { text-decoration: underline; }
            .api-links code { background-color: #252525; padding: 2px 6px; border-radius: 3px; color: #FFA500; }
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

        <div class="api-links">
            <strong>REST Endpoints:</strong><br><br>
            <a href="/api/flights">GET /api/flights</a> 
            <span style="color: #AAA;">(Requires Bearer Auth)</span><br><br>
            <a href="#">GET /api/flight/<code>&lt;flight_id&gt;</code>/telemetry</a>
            <span style="color: #AAA;">(Requires Bearer Auth)</span>
        </div>

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

    monitor_thread = threading.Thread(target=stale_telemetry_monitor, daemon=True)
    monitor_thread.start()
    print("Background stale telemetry monitor started.")

    # NOTE: Debug mode is enabled to catch request handling errors
    app.run(host='0.0.0.0', debug=True, port=5000, use_reloader=False)
