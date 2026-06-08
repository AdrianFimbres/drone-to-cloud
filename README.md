# Drone-to-Cloud telemetry & diagnostics testbed

A sandbox for reproducing and diagnosing drone-to-cloud failure scenarios: service crashes, firewall blocking, invalid payloads, packet loss, and network latency. Covers the network, application, and data layers.

## Architecture
* **Client (`drone_client.py`):** Simulates a drone by replaying historical flight logs (`flight_log.csv`) or generating live telemetry in real-time. It handles network timeouts, generates a unique session ID (`flight_id`) at startup, and enforces strict UTC timestamp formatting for all outbound HTTP POST requests.
* **Server (`cloud_server.py`):** A Flask-based REST API. It validates incoming JSON telemetry against required fields and strict timestamp formats, then stores data in a structured, relational SQLite database.
* **Dashboard:** A web interface that queries the relational database to provide a real-time view of flight status and telemetry. 

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

## Project structure

```
drone-to-cloud/
├── cloud_server.py       # Flask backend & SQLite database logic
├── drone_client.py       # Client simulation (CSV replay & live gen)
├── flight_log.csv        # Sample flight path
├── telemetry_api.json    # Postman collection for manual testing
├── requirements.txt      # Python dependencies
└── README.md             # Documentation
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

### 3. Launch the flight simulation (the drone)
Open a new terminal tab and run:
```bash
python3 drone_client.py
```
This script has two modes controlled by the `SIMULATION_MODE` variable in `drone_client.py`:

* `CSV` (default): Replays a historical flight from `flight_log.csv`.
* `LIVE`: Generates continuous telemetry in real time until the simulated battery depletes.

### 4. Monitor operations
**Real-time**: Check the terminal for HTTP status codes.

**Dashboard**: Navigate to `http://127.0.0.1:5000` to monitor incoming telemetry.