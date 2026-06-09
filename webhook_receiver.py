from flask import Flask, request, jsonify
import hmac
import hashlib
import json

app = Flask(__name__)

WEBHOOK_SECRET = "super_secret_webhook_key"

@app.route('/webhook', methods=['POST'])
def handle_webhook():
    """Receives webhook payloads and verifies HMAC-SHA256 signature."""
    signature_header = request.headers.get('X-Webhook-Signature')
    if not signature_header or not signature_header.startswith('sha256='):
        print("[AUTH ERROR] Webhook rejected: Missing or malformed X-Webhook-Signature header.")
        return jsonify({"status": "error", "message": "Missing or invalid signature header"}), 401

    received_signature = signature_header.split('sha256=')[1]
    
    payload = request.get_data()
    
    expected_signature = hmac.new(
        WEBHOOK_SECRET.encode('utf-8'),
        payload,
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(received_signature, expected_signature):
        print("[AUTH ERROR] Webhook rejected: Signature mismatch.")
        return jsonify({"status": "error", "message": "Signature verification failed"}), 403

    try:
        data = json.loads(payload.decode('utf-8'))
        print("\n" + "="*40)
        print(f"SECURE WEBHOOK RECEIVED: {data.get('event')}")
        print("="*40)
        print(json.dumps(data, indent=2))
        print("="*40 + "\n")
    except json.JSONDecodeError:
        print("[WARN] Webhook signature was valid, but payload is not valid JSON.")
        return jsonify({"status": "error", "message": "Invalid JSON"}), 400

    return jsonify({"status": "success", "message": "Webhook received"}), 200

if __name__ == '__main__':
    print(f"Listening for authenticated webhooks on port 5001...")
    print(f"Expecting Signature Secret: '{WEBHOOK_SECRET}'")
    app.run(host='0.0.0.0', port=5001)
