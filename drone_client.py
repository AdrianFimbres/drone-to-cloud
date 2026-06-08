import requests
import json
import time
import csv
import uuid
import random
from datetime import datetime, timezone

# NOTE: This client intentionally avoids retries to preserve raw network behavior for diagnostics.

SERVER_URL = "http://127.0.0.1:5000/api/telemetry"
VEHICLE_SERIAL = "v-SIM-001" 
FLIGHT_ID = f"flt_{uuid.uuid4()}" 
CSV_FILENAME = "flight_log.csv"
SIMULATION_MODE = "CSV" 
PACKET_DROP_RATE = 0.2
MIN_LATENCY = 0.5
MAX_LATENCY = 2.0
AUTH_TOKEN = "token-rw-001"

def format_iso8601_z(raw_timestamp_str):
    """Converts the timestamp to strict UTC Z format. Warns if malformed."""
    try:
        dt = datetime.fromisoformat(raw_timestamp_str)
        return dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    except Exception as e:
        fallback = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        print(f"[WARN] Malformed timestamp '{raw_timestamp_str}'. Substituting server time: {fallback}")
        return fallback

def send_data_to_server(data):
    """Sends a telemetry payload to the cloud server."""
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {AUTH_TOKEN}'
    }
    try:
        response = requests.post(SERVER_URL, data=json.dumps(data), headers=headers, timeout=5)

        if response.status_code == 401:
            print(f"[AUTH ERROR] Unauthorized: Missing or invalid token for frame {data.get('timestamp')}.")
            return
        elif response.status_code == 403:
            print(f"[AUTH ERROR] Forbidden: Token lacks required scope for frame {data.get('timestamp')}.")
            return
        
        response.raise_for_status() 
        print(f"Sent frame {data.get('timestamp', 'N/A')}. Server: {response.json()}")

    except requests.exceptions.Timeout:
        print(f"[High Latency] Request timed out for frame {data.get('timestamp')}. Possible network congestion.")
    except requests.exceptions.ConnectionError as e:
        print(f"[Network Failure] Could not reach server. Diagnostics: {e}")
    except requests.exceptions.HTTPError as err:
        print(f"[Server Error] 4xx/5xx response: {err}. Check payload format or server logs.")
    except requests.exceptions.RequestException as e:
        print(f"ERROR: Connection failed. Details: {e}")

def run_csv_replay():
    print(f"Starting Flight Replay for '{VEHICLE_SERIAL}'. Reading from {CSV_FILENAME}...")
    try:
        with open(CSV_FILENAME, mode='r') as csv_file:
            csv_reader = csv.DictReader(csv_file)
            for row in csv_reader:
                
                if random.random() < PACKET_DROP_RATE:
                    print(f"[WARN] Simulated packet loss for frame {row['timestamp']}...")
                    continue
                
                heading_raw = row.get('heading')
                heading_val = float(heading_raw) if heading_raw else None

                payload = {
                    "flight_id": FLIGHT_ID,
                    "vehicle_serial": VEHICLE_SERIAL,
                    "timestamp": format_iso8601_z(row['timestamp']),
                    "latitude": float(row['latitude']),
                    "longitude": float(row['longitude']),
                    "altitude_agl": float(row.get('altitude_agl', 0.0)), 
                    "speed": float(row.get('speed', 0.0)),
                    "heading": heading_val,          
                    "battery_level": int(row['battery_level']),
                    "state": row.get('state', "FLYING")
                }
                
                latency = random.uniform(MIN_LATENCY, MAX_LATENCY)
                time.sleep(latency)
                
                send_data_to_server(payload)
                
    except FileNotFoundError:
        print(f"ERROR: {CSV_FILENAME} not found.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

def run_live_simulation():
    print(f"Starting LIVE Telemetry Generation for '{VEHICLE_SERIAL}'...")
    battery = 100
    altitude = 0.0
    heading = 0.0
    
    while battery > 0:
        if random.random() < PACKET_DROP_RATE:
            print("[WARN] Simulated packet loss...")
            time.sleep(2) 
            battery -= 1  
            continue
            
        altitude = min(120.0, altitude + random.uniform(0.5, 5.0))
        heading = (heading + random.uniform(-5, 5)) % 360
            
        payload = {
            "flight_id": FLIGHT_ID,
            "vehicle_serial": VEHICLE_SERIAL,
            "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            "latitude": 34.118400 + random.uniform(-0.0001, 0.0001),
            "longitude": -118.300400 + random.uniform(-0.0001, 0.0001),
            "altitude_agl": round(altitude, 2),
            "speed": round(random.uniform(10.0, 15.0), 2),
            "heading": round(heading, 2),
            "battery_level": battery,
            "state": "FLYING"
        }
        
        latency = random.uniform(MIN_LATENCY, MAX_LATENCY)
        time.sleep(latency)
        
        send_data_to_server(payload)
        
        battery -= 1
        time.sleep(5)

def main(): 
    if SIMULATION_MODE == "CSV":
        run_csv_replay()
    elif SIMULATION_MODE == "LIVE":
        run_live_simulation()
    else:
        print("ERROR: Invalid SIMULATION_MODE selected. Choose 'CSV' or 'LIVE'.")

if __name__ == "__main__":
    main()
