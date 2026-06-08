import csv
import json
import requests
from datetime import datetime, timezone

CSV_FILEPATH = "legacy_flight_export.csv"
API_URL = "http://127.0.0.1:5000/api/telemetry"
AUTH_TOKEN = "token-rw-001"

ALLOWED_SCHEMA = {
    'flight_id', 'vehicle_serial', 'timestamp', 'latitude', 
    'longitude', 'altitude_agl', 'speed', 'heading', 
    'battery_level', 'state'
}

REQUIRED_FIELDS = {
    'flight_id', 'vehicle_serial', 'timestamp', 'latitude', 
    'longitude', 'altitude_agl', 'speed', 'battery_level'
}

def extract(filepath):
    """Reads the dirty CSV and returns a raw list of dictionaries."""
    try:
        # utf-8-sig handles any hidden Byte Order Marks (BOM) common in legacy CSV exports
        with open(filepath, mode='r', encoding='utf-8-sig') as file:
            reader = csv.DictReader(file)
            return list(reader)
    except FileNotFoundError:
        print(f"[FATAL] Could not find {filepath}")
        return []

def transform(row_index, row):
    """Cleans data, strips unknown columns, and normalizes formats."""
    clean_row = {}
    stripped_keys = []

    for key, value in row.items():
        if key in ALLOWED_SCHEMA:
            clean_row[key] = value
        else:
            stripped_keys.append(key)
    
    if stripped_keys:
        print(f"[TRANSFORM] Row {row_index} | Stripped unknown vendor columns: {stripped_keys}")

    raw_ts = clean_row.get('timestamp', '')
    if raw_ts and '/' in raw_ts:  
        try:
            dt = datetime.strptime(raw_ts, "%Y/%m/%d %I:%M %p")
            dt_utc = dt.replace(tzinfo=timezone.utc)
            clean_row['timestamp'] = dt_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
            print(f"[WARN] Row {row_index} | Naive timestamp assumed UTC. Converted to ISO 8601.")
        except ValueError:
            pass 

    return clean_row

def validate(row_index, row, seen_records):
    """Validates field presence, types, ranges, and duplicates."""
    
    for field in REQUIRED_FIELDS:
        val = row.get(field)
        if val is None or str(val).strip() == "":
            return False, f"Missing or empty required field: '{field}'"

    # NOTE: This only catches duplicates within the current ETL run. 
    record_signature = f"{row['vehicle_serial']}_{row['timestamp']}"
    if record_signature in seen_records:
        return False, f"Duplicate telemetry record detected for {record_signature}"
    seen_records.add(record_signature)

    try:
        battery = int(row['battery_level'])
        if not (0 <= battery <= 100):
            return False, f"battery_level out of range ({battery})"
        row['battery_level'] = battery

        lat = float(row['latitude'])
        lon = float(row['longitude'])
        if not (-90.0 <= lat <= 90.0):
            return False, f"latitude out of range ({lat})"
        if not (-180.0 <= lon <= 180.0):
            return False, f"longitude out of range ({lon})"
        row['latitude'] = lat
        row['longitude'] = lon

        row['altitude_agl'] = float(row['altitude_agl'])
        row['speed'] = float(row['speed'])
        
        if 'heading' in row and row['heading']:
            row['heading'] = float(row['heading'])
            
    except ValueError as e:
        return False, f"Type conversion failed: {str(e)}"

    return True, "OK"

def load(row_index, clean_record):
    """Pushes the verified record to the cloud API."""
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {AUTH_TOKEN}'
    }
    try:
        response = requests.post(API_URL, data=json.dumps(clean_record), headers=headers, timeout=5)
        if response.status_code == 201:
            print(f"[PASS] Row {row_index} | Successfully loaded {clean_record['flight_id']}.")
            return True
        else:
            print(f"[REJECT] Row {row_index} | API Rejected Payload: {response.status_code} - {response.text}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Row {row_index} | Network failure during load: {e}")
        return False

def run_pipeline():
    print("--- STARTING LEGACY ETL MIGRATION ---")
    raw_data = extract(CSV_FILEPATH)
    if not raw_data:
        return

    stats = {"processed": 0, "passed": 0, "rejected": 0}
    seen_records = set()

    for idx, raw_row in enumerate(raw_data, start=1):
        stats["processed"] += 1
        
        cleaned_row = transform(idx, raw_row)
        
        is_valid, reason = validate(idx, cleaned_row, seen_records)
        
        if not is_valid:
            print(f"[REJECT] Row {idx} | Reason: {reason}")
            stats["rejected"] += 1
            continue
            
        success = load(idx, cleaned_row)
        if success:
            stats["passed"] += 1
        else:
            stats["rejected"] += 1

    print("-" * 40)
    print(f"[SUMMARY] Processed: {stats['processed']} | Passed: {stats['passed']} | Rejected: {stats['rejected']}")
    print("--- ETL MIGRATION COMPLETE ---")

if __name__ == "__main__":
    run_pipeline()
