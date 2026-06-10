# Drone-to-Cloud telemetry & diagnostics testbed

A sandbox for reproducing and diagnosing drone-to-cloud failure scenarios: service crashes, firewall blocking, invalid payloads, packet loss, and network latency. Covers the network, application, and data layers.

## Architecture
* **Client (`drone_client.py`):** Simulates a drone by replaying historical flight logs (`flight_log.csv`) or generating live telemetry in real-time. It handles network timeouts, generates a unique session ID (`flight_id`) at startup, and enforces strict UTC timestamp formatting for all outbound HTTP POST requests.
* **Server (`cloud_server.py`):** A Flask-based REST API. It validates incoming JSON telemetry against required fields and strict timestamp formats, then stores data in a structured, relational SQLite database.
* **ETL Pipeline (`etl_pipeline.py`):** Simulates batch processing of legacy flight data. Reads messy CSV exports, standardizes timestamps, strips unknown columns, and validates data types and ranges before pushing clean records to the cloud server.
* **Dashboard:** A web interface that queries the relational database to provide a real-time view of flight status and telemetry.
* **Webhook Receiver (`webhook_receiver.py`):** A mock webhook receiver running on port 5001. It listens for outbound POST requests from the cloud server and verifies the payload signature using HMAC-SHA256.

## Data structure
* **vehicles:** Hardware inventory, indexed by serial number.
* **flights:** Individual flight sessions, linked to a vehicle.
* **telemetry:** Raw flight data, linked to both the vehicle and the flight session.
```
vehicles (1) → flights (many) → telemetry (many)
```

## Tech stack
* **Language:** Python 3.x
* **Framework:** Flask (Web API)
* **Database:** SQLite (Relational Logging)
* **Networking:** HTTP/REST (Requests library), TCP/IP troubleshooting
* **Data Format:** JSON & CSV (Simulating Flight Log Replay)

## Authentication
All endpoints except the root dashboard require Bearer token authentication. The dashboard (GET /) is intentionally left open for local debugging.

**Sandbox tokens:**
* `token-rw-001`: read/write access (standard operational token).
* `token-ro-002`: read-only access (triggers a 403 Forbidden on any POST request).

To test authentication:
* **Test 401 (Unknown Identity):** Change `AUTH_TOKEN` to `"bad-token"`. Client logs `[AUTH ERROR] Unauthorized`.
* **Test 403 (Insufficient Permissions):** Change `AUTH_TOKEN` to `"token-ro-002"`. Client logs `[AUTH ERROR] Forbidden`.
* In both cases the server and network are healthy; the database receives no new rows.

## Rate Limiting
`POST /api/telemetry` is rate limited to 10 requests per 10 seconds per IP.

To test rate limiting:
* In `drone_client.py`, set `MIN_LATENCY` to `0.1`, `MAX_LATENCY` to `0.2`, and comment out `time.sleep(5)` in `run_live_simulation()`.
* Run the client in `LIVE` mode. The client will log `[RATE LIMITED] Server throttled request. Retry after 10s.` and back off automatically.

## API Endpoints
All endpoints except the root dashboard require `Authorization: Bearer <token>`.

* **`POST /api/telemetry`**: Receives and stores a telemetry record. **Rate limited to 10 requests per 10 seconds per IP.**
* **`GET /api/flights`**: Returns all flights with session metadata and telemetry row counts.
* **`GET /api/flight/<flight_id>/telemetry`**: Returns all telemetry records for a specific flight. Returns `404` if the flight does not exist.

**Example response (`GET /api/flights`):**
```json
{
  "flights": [
    {
      "flight_id": "flt_manual_test_001",
      "vehicle_serial": "v-SIM-001",
      "started_at": "2026-01-06T10:00:00Z",
      "ended_at": null,
      "state": "FLYING",
      "telemetry_count": 12
    }
  ]
}
```

## Webhooks & Event Triggers
The cloud server evaluates telemetry in real-time and dispatches outbound webhooks to a configured URL (`http://127.0.0.1:5001/webhook`) when specific thresholds are met.

**Trigger Rules:**
1. **Low Battery (`vehicle.battery.critical`):** Fires once when a vehicle's battery drops below 20%.
2. **State Change (`vehicle.state.changed`):** Fires when a vehicle transitions into `LANDING` or `DOCKED` states.
3. **Stale Connection (`vehicle.telemetry.stale`):** A background daemon fires this if no telemetry is received from an active flight for > 30 seconds.

**Security & Signature Validation:**
All outbound webhooks include an `X-Webhook-Signature` header. The payload is signed using HMAC-SHA256 with a shared secret configured in `WEBHOOK_SECRET` in both `cloud_server.py` and `webhook_receiver.py`. The receiver must compute the hash of the raw request bytes and securely compare it to the provided signature to prevent spoofing.

**Example Webhook Payload:**
```json
{
  "event": "vehicle.battery.critical",
  "flight_id": "flt_aca1866c-01d7-4a12-b34c-f54479a097cc",
  "vehicle_serial": "v-SIM-001",
  "timestamp": "2026-06-09T22:41:45Z",
  "data": {
    "battery_level": 19,
    "latitude": 34.1183,
    "longitude": -118.3004
  }
}
```

## Project structure
```
drone-to-cloud/
├── cloud_server.py          # Flask backend & SQLite database logic
├── webhook_receiver.py      # Mock webhook receiver with HMAC-SHA256 validation
├── drone_client.py          # Client simulation (CSV replay & live gen)
├── etl_pipeline.py          # Standalone ETL script for legacy data migration
├── flight_log.csv           # Sample flight path
├── legacy_flight_export.csv # Intentionally messy test data for ETL
├── telemetry_api.json       # Postman collection for manual testing
├── requirements.txt         # Python dependencies
└── README.md                # Documentation
```

## Troubleshooting scenarios

### Scenario 1: The service crash
* Simulation: While the client is running, manually terminate the Flask server process (Ctrl+C in terminal).

* Symptom: Client logs a **Connection refused** error with an OS-specific errno code (`61` on macOS, `111` on Linux, `10061` on Windows).

* Diagnosis: Ping works but the application port is closed.

### Scenario 2: The firewall block
* Simulation: Configure your OS Firewall to "Block incoming connections" for Python.

* Symptom: Client logs `timeout` after `5s` hang.

* Diagnosis: The firewall is blocking the connection before it reaches the application.

### Scenario 3: Integration failure (bad data)
* Simulation: Modify `drone_client.py` to comment out the `latitude` field in the payload.

* Symptom: Server responds with `HTTP 400 Bad Request` and lists the missing required fields.

* Diagnosis: Connection is good but the payload fails server-side validation.

### Scenario 4: Network degradation (weak signal)
* Simulation: Set `PACKET_DROP_RATE` to 0.0 and `MIN_LATENCY`/`MAX_LATENCY` to 0 to isolate other scenarios. Default values (0.2 drop rate, 0.5s–2s latency) keep this scenario always active.

* Symptom: Dashboard updates become choppy; logs show intermittent gaps but no hard errors.

* Diagnosis: Ping works and the server stays reachable. Sporadic 200 OK responses in the logs point to the application being healthy; the issue is network instability, not a crash.

## Future additions
UDP-based video streaming simulation to explore how the same network conditions affect video and telemetry differently, and how to distinguish a degraded video link from a true network failure in the field.

## How to run it

### 1. Setup
Clone the repository and install dependencies:
```bash
pip3 install -r requirements.txt
```

### 2. Start the ground station (the server)
Open a terminal and run:
```bash
python3 cloud_server.py
```

**Network**: Listens on `0.0.0.0:5000` (Accepts external connections).

**Local Dashboard**: Access via `http://127.0.0.1:5000` in your browser.

**Note**: The `telemetry.db` file is created automatically at runtime (it is not included in the repo).

### 3. Start the webhook receiver
Open a new terminal tab and run:
```bash
python3 webhook_receiver.py
```
**Network**: Listens on `0.0.0.0:5001`.

### 4. Launch the flight simulation (the drone)
Open a new terminal tab and run:
```bash
python3 drone_client.py
```
This script has two modes controlled by the `SIMULATION_MODE` variable in `drone_client.py`:

* `CSV` (default): Simulates a post-flight sync from a disconnected field operation using `flight_log.csv`.
* `LIVE`: Generates continuous telemetry in real time until the simulated battery depletes.

### 5. Run the legacy data migration (ETL pipeline)
Open a new terminal and run:
```bash
python3 etl_pipeline.py
```
**Note**: In this test dataset, all rows use the legacy timestamp format, so the `[WARN]` tag appears on every row. In a real migration, warnings would be sparse and indicate specific rows requiring manual review.

### 6. Monitor operations
**Real-time**: Check the terminal for HTTP status codes.

**Dashboard**: Navigate to `http://127.0.0.1:5000` to monitor incoming telemetry.