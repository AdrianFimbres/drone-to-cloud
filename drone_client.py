import requests
import json
import time
import csv
import random

# NOTE: This client intentionally avoids retries to preserve raw network behavior for diagnostics.

# --- CONFIGURATION ---
SERVER_URL = "http://127.0.0.1:5000/api/telemetry"
DRONE_ID = "drone_id_123"
CSV_FILENAME = "flight_log.csv"

# SCENARIO 4: Network Degradation
PACKET_DROP_RATE = 0.2  # 20% chance to lose data
MIN_LATENCY = 0.5       # Seconds
MAX_LATENCY = 2.0       # Seconds

def send_data_to_server(data):
    """Sends telemetry data to the server via POST request."""
    headers = {'Content-Type': 'application/json'}
    try:
        response = requests.post(SERVER_URL, data=json.dumps(data), headers=headers, timeout=5)
        response.raise_for_status() 
        print(f"Sent frame {data.get('timestamp', 'N/A')}. Server: {response.json()}")

    except requests.exceptions.Timeout:
        print(f"[High Latency] Request timed out for frame {data.get('timestamp')}. Possible network congestion.")
    except requests.exceptions.ConnectionError:
        print(f"[Connection Refused] Could not reach server. Is the Firewall blocking port 5000? Is the server down?")
    except requests.exceptions.HTTPError as err:
        print(f"[Server Error] 4xx/5xx response: {err}. Check payload format or server logs.")
    except requests.exceptions.RequestException as e:
        # Catch-all for any other unexpected network errors
        print(f"ERROR: Connection failed. Details: {e}")

def main():
    print(f"Starting Flight Replay for '{DRONE_ID}'. Reading from {CSV_FILENAME}...")
    
    try:
        with open(CSV_FILENAME, mode='r') as csv_file:
            csv_reader = csv.DictReader(csv_file)
            
            for row in csv_reader:
                # 1. Parse Data
                telemetry_data = {
                    "drone_id": DRONE_ID,
                    "latitude": float(row['latitude']),
                    "longitude": float(row['longitude']),
                    "battery_level": int(row['battery_percent']),
                    "timestamp": row['timestamp']
                }
                
                # --- SCENARIO 4: NETWORK DEGRADATION SIMULATION ---
                # Randomly drop telemetry packets to simulate weak signal
                if random.random() < PACKET_DROP_RATE:
                    print(f"[WARN] Simulated packet loss — telemetry dropped at {row['timestamp']}")
                    continue  # Skip send, simulating lost transmission

                # Inject variable network latency (jitter)
                latency = random.uniform(MIN_LATENCY, MAX_LATENCY)
                time.sleep(latency)
                # --------------------------------------------------
                
                # 2. Send Data
                send_data_to_server(telemetry_data)
                
                # 3. Base Flight Interval (Wait 2 seconds between points)
                time.sleep(2)
                
        print("Flight log replay complete. Landing drone.")

    except FileNotFoundError:
        print(f"ERROR: Could not find file '{CSV_FILENAME}'.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

if __name__ == "__main__":
    main()