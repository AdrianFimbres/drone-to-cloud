import sqlite3
import requests
import time
import os
from datetime import datetime, timezone

DB_NAME = 'telemetry.db'

SF_CLIENT_ID = os.getenv("SF_CLIENT_ID", "your_consumer_key_here")
SF_CLIENT_SECRET = os.getenv("SF_CLIENT_SECRET", "your_consumer_secret_here")
SF_USERNAME = os.getenv("SF_USERNAME", "your_salesforce_username_here")
SF_PASSWORD = os.getenv("SF_PASSWORD", "your_password_plus_security_token_here")

SF_LOGIN_URL = "https://login.salesforce.com/services/oauth2/token"
API_VERSION = "v57.0"

def get_db_connection():
    """Returns a SQLite connection with rows accessible by column name."""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def migrate_db():
    """Ensures the synced_at column exists in the flights table."""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("PRAGMA table_info(flights);")
        columns = [row['name'] for row in cursor.fetchall()]

        if 'synced_at' not in columns:
            print("[DB MIGRATION] Adding 'synced_at' column to 'flights' table...")
            cursor.execute("ALTER TABLE flights ADD COLUMN synced_at TEXT DEFAULT NULL;")
            conn.commit()
            print("[DB MIGRATION] Complete.")

def get_sf_token():
    """Authenticates with Salesforce and returns (access_token, instance_url)."""
    payload = {
        'grant_type': 'password',
        'client_id': SF_CLIENT_ID,
        'client_secret': SF_CLIENT_SECRET,
        'username': SF_USERNAME,
        'password': SF_PASSWORD
    }
    response = None
    try:
        response = requests.post(SF_LOGIN_URL, data=payload, timeout=10)
        response.raise_for_status()
        auth_data = response.json()
        print("[AUTH] Successfully authenticated with Salesforce.")
        return auth_data['access_token'], auth_data['instance_url']
    except requests.exceptions.RequestException as e:
        print(f"[AUTH ERROR] Failed to authenticate with Salesforce: {e}")
        if response is not None:
            print(f"Details: {response.text}")
        return None, None

def fetch_unsynced_flights():
    """Queries SQLite for flights that have not been pushed to Salesforce."""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        query = '''
            SELECT 
                f.flight_id, 
                f.vehicle_serial, 
                f.started_at, 
                f.ended_at, 
                (SELECT state FROM telemetry 
                 WHERE flight_id = f.flight_id 
                 ORDER BY timestamp DESC LIMIT 1) as final_state,
                COUNT(t.id) as telemetry_count,
                (SELECT battery_level FROM telemetry 
                 WHERE flight_id = f.flight_id 
                 ORDER BY timestamp DESC LIMIT 1) as battery_at_landing
            FROM flights f
            LEFT JOIN telemetry t ON f.flight_id = t.flight_id
            WHERE f.synced_at IS NULL
            GROUP BY f.flight_id
        '''
        cursor.execute(query)
        return [dict(row) for row in cursor.fetchall()]

def push_flight_to_salesforce(token, instance_url, flight):
    """Upserts a single flight record into the DroneFlightLog__c object."""
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    
    endpoint = f"{instance_url}/services/data/{API_VERSION}/sobjects/DroneFlightLog__c/Flight_ID__c/{flight['flight_id']}"
    
    payload = {
        "Vehicle_Serial__c": flight['vehicle_serial'],
        "Started_At__c": flight['started_at'],
        "Ended_At__c": flight['ended_at'],
        "Final_State__c": flight['final_state'],
        "Telemetry_Count__c": flight['telemetry_count'] or 0,
        "Battery_At_Landing__c": flight['battery_at_landing']
    }
    
    payload = {k: v for k, v in payload.items() if v is not None}

    for attempt in range(2):
        try:
            response = requests.patch(endpoint, json=payload, headers=headers, timeout=10)
            
            if response.status_code in [201, 204]:
                action = "Created" if response.status_code == 201 else "Updated"
                print(f"[SFDC] {action} {flight['flight_id']}")
                return True
                
            elif response.status_code in [429, 503]:
                if attempt == 0:
                    print(f"[WARN] Rate limited ({response.status_code}). Retrying after 60s...")
                    time.sleep(60)
                    continue
                else:
                    print(f"[ERROR] Retry failed for {flight['flight_id']}. Skipping.")
                    return False
                    
            else:
                print(f"[ERROR] Failed to upsert {flight['flight_id']}: {response.status_code} - {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            print(f"[NETWORK ERROR] Failed to reach Salesforce during upsert: {e}")
            return False

    return False

def mark_flight_synced(flight_id):
    """Updates the synced_at timestamp in SQLite after a successful push."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        now_utc = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        cursor.execute(
            "UPDATE flights SET synced_at = ? WHERE flight_id = ?",
            (now_utc, flight_id)
        )
        conn.commit()

def run_sync():
    print("--- STARTING SALESFORCE SYNC ---")

    migrate_db()

    flights_to_sync = fetch_unsynced_flights()
    if not flights_to_sync:
        print("[INFO] No unsynced flights found. Exiting.")
        return

    print(f"[INFO] Found {len(flights_to_sync)} flights pending sync.")

    token, instance_url = get_sf_token()
    if not token:
        return

    stats = {"success": 0, "failed": 0}

    for flight in flights_to_sync:
        success = push_flight_to_salesforce(token, instance_url, flight)

        if success:
            mark_flight_synced(flight['flight_id'])
            stats["success"] += 1
        else:
            stats["failed"] += 1

        time.sleep(0.5)

    print("-" * 40)
    print(f"[SUMMARY] Success: {stats['success']} | Failed: {stats['failed']}")
    print("--- SALESFORCE SYNC COMPLETE ---")

if __name__ == "__main__":
    run_sync()
