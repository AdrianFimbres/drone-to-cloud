import requests
import json
import time
import csv
import random
from datetime import datetime, timezone

# NOTE: This client intentionally avoids retries to preserve raw network behavior for diagnostics.

# --- CONFIGURATION ---
SERVER_URL = "http://127.0.0.1:5000/api/telemetry"
DRONE_ID = "drone_id_123"
CSV_FILENAME = "flight_log.csv"
SIMULATION_MODE = "CSV"

PACKET_DROP_RATE = 0.2 
MIN_LATENCY = 0.5 
MAX_LATENCY = 2.0 

def send_data_to_server(data):
    """Sends telemetry data to the server via POST request."""
    headers = {'Content-Type': 'application/json'}
    try:
        response = requests.post(SERVER_URL, data=json.dumps(data), headers=headers, timeout=5)
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
    print(f"Starting Flight Replay for '{DRONE_ID}'. Reading from {CSV_FILENAME}...")
    try:
        with open(CSV_FILENAME, mode='r') as csv_file:
            csv_reader = csv.DictReader(csv_file)
            
            for row in csv_reader:
                telemetry_data = {
                    "drone_id": DRONE_ID,
                    "latitude": float(row['latitude']),
                    "longitude": float(row['longitude']),
                    "battery_level": int(row['battery_percent']),
                    "timestamp": row['timestamp']
                }
                
                if random.random() < PACKET_DROP_RATE:
                    print(f"[WARN] Simulated packet loss — telemetry dropped at {row['timestamp']}")
                    continue 

                latency = random.uniform(MIN_LATENCY, MAX_LATENCY)
                time.sleep(latency)
                
                send_data_to_server(telemetry_data)
                time.sleep(2)
                
        print("Flight log replay complete. Landing drone.")

    except FileNotFoundError:
        print(f"ERROR: Could not find file '{CSV_FILENAME}'.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")


def run_live_simulation(): 
    print(f"Starting LIVE Telemetry Generation for '{DRONE_ID}'...")
    
    current_lat = 34.118400
    current_lon = -118.300400
    battery = 100
    
    while True:
        latency = random.uniform(MIN_LATENCY, MAX_LATENCY)
        time.sleep(latency)
        
        if random.random() < PACKET_DROP_RATE:
            drop_time = datetime.now(timezone.utc).isoformat()
            print(f"[WARN] Simulated packet loss — telemetry dropped at {drop_time}")
            time.sleep(5) 
            continue

        live_payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "drone_id": DRONE_ID,
            "latitude": current_lat,
            "longitude": current_lon,
            "battery_level": battery
        }
        
        send_data_to_server(live_payload)
        
        current_lat += 0.000050
        battery = max(0, battery - 1)
        
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