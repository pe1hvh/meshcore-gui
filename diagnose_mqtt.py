#!/usr/bin/env python3
"""
MeshCore Observer — MQTT Connection Diagnostic

Tests every step of the authentication process individually
so you can see exactly where it fails.

Usage:
    cd ~/meshcore-gui
    source venv/bin/activate
    python diagnose_mqtt.py
"""

import json
import os
import sys
import time
import base64

# ── Step 0: Check dependencies ──────────────────────────────────────

print()
print("=" * 60)
print("  MeshCore Observer — MQTT Connection Diagnostic")
print("=" * 60)

errors = []
try:
    from nacl.signing import SigningKey, VerifyKey
    print("\n  [OK] PyNaCl installed")
except ImportError:
    print("\n  [FAIL] PyNaCl not installed — run: pip install PyNaCl")
    sys.exit(1)

try:
    import paho.mqtt.client as paho_mqtt
    try:
        import paho.mqtt as _paho_base
        _paho_ver = getattr(_paho_base, "__version__", "unknown")
    except Exception:
        _paho_ver = "unknown"
    print(f"  [OK] paho-mqtt installed (version: {_paho_ver})")
except ImportError:
    print("  [FAIL] paho-mqtt not installed — run: pip install paho-mqtt")
    sys.exit(1)

try:
    import yaml
    print("  [OK] pyyaml installed")
except ImportError:
    print("  [FAIL] pyyaml not installed — run: pip install pyyaml")
    sys.exit(1)


# ── Step 1: Load config ─────────────────────────────────────────────

print("\n" + "-" * 60)
print("  Step 1: Loading configuration")
print("-" * 60)

config_path = "observer_config.yaml"
if not os.path.exists(config_path):
    print(f"\n  [FAIL] {config_path} not found")
    sys.exit(1)

with open(config_path) as f:
    config = yaml.safe_load(f) or {}

mqtt = config.get("mqtt", {})
if not mqtt:
    print("\n  [FAIL] No 'mqtt:' section in config")
    sys.exit(1)

public_key = mqtt.get("public_key", "").strip()
iata = mqtt.get("iata", "").strip()
device_name = mqtt.get("device_name", "MeshCore Observer")

# Load private key (same priority as observer: env > file > inline)
private_key = ""
env_key = os.environ.get("MESHCORE_PRIVATE_KEY", "").strip()
if env_key:
    private_key = env_key
    print(f"\n  Private key source: environment variable")
elif mqtt.get("private_key_file"):
    key_path = os.path.expanduser(mqtt["private_key_file"])
    if os.path.exists(key_path):
        with open(key_path) as f:
            private_key = f.read().strip()
        print(f"\n  Private key source: {key_path}")
    else:
        print(f"\n  [FAIL] Key file not found: {key_path}")
        sys.exit(1)
elif mqtt.get("private_key"):
    private_key = mqtt["private_key"].strip()
    print(f"\n  Private key source: inline config")

if not private_key:
    print("\n  [FAIL] No private key found")
    sys.exit(1)

print(f"  IATA:        {iata}")
print(f"  Public key:  {public_key[:16]}...{public_key[-8:]}")
print(f"  Private key: {private_key[:16]}...{private_key[-8:]}")
print(f"  Device name: {device_name}")
print(f"  Key lengths: public={len(public_key)}, private={len(private_key)}")


# ── Step 2: Validate key pair ────────────────────────────────────────

print("\n" + "-" * 60)
print("  Step 2: Validating key pair")
print("-" * 60)

try:
    signing_key = SigningKey(bytes.fromhex(private_key))
    derived_public = signing_key.verify_key.encode().hex()
    print(f"\n  Derived public key from private: {derived_public[:16]}...{derived_public[-8:]}")

    if derived_public.lower() == public_key.lower():
        print("  [OK] Public key in config matches derived public key")
    else:
        print("  [FAIL] PUBLIC KEY MISMATCH!")
        print(f"    Config has:  {public_key}")
        print(f"    Should be:   {derived_public}")
        print("\n  Fixing this would likely solve the auth problem.")
        print(f"  Update public_key in {config_path} to: {derived_public}")
        sys.exit(1)
except Exception as e:
    print(f"\n  [FAIL] Invalid private key: {e}")
    sys.exit(1)

# Test sign + verify
test_msg = b"diagnostic_test"
try:
    signed = signing_key.sign(test_msg)
    verify_key = VerifyKey(bytes.fromhex(public_key))
    verify_key.verify(signed.message, signed.signature)
    print("  [OK] Sign + verify roundtrip successful")
except Exception as e:
    print(f"  [FAIL] Sign/verify failed: {e}")
    sys.exit(1)


# ── Step 3: Generate JWT token ───────────────────────────────────────

print("\n" + "-" * 60)
print("  Step 3: Generating JWT token")
print("-" * 60)

def base64url_encode(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

def base64url_decode(s):
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)

# Find first enabled broker
brokers = mqtt.get("brokers", [])
enabled = [b for b in brokers if b.get("enabled", True)]
if not enabled:
    print("\n  [FAIL] No enabled brokers")
    sys.exit(1)

broker = enabled[0]
broker_server = broker["server"]
broker_port = broker.get("port", 443)
broker_transport = broker.get("transport", "websockets")
broker_tls = broker.get("tls", True)

print(f"\n  Broker: {broker.get('name', 'unknown')} ({broker_server}:{broker_port})")

# Build JWT exactly as auth_token.py does
header = {"alg": "EdDSA", "typ": "JWT"}
now = int(time.time())
payload = {
    "publicKey": public_key.upper(),
    "aud": broker_server,
    "iat": now,
    "exp": now + 3600,
}

header_b64 = base64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
payload_b64 = base64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))

message = f"{header_b64}.{payload_b64}".encode("utf-8")
signed = signing_key.sign(message)
signature_b64 = base64url_encode(signed.signature)
token = f"{header_b64}.{payload_b64}.{signature_b64}"

username = f"v1_{public_key.upper()}"

print(f"\n  JWT header:  {json.dumps(header)}")
print(f"  JWT payload: {json.dumps(payload, indent=2)}")
print(f"  JWT token:   {token[:40]}...{token[-20:]}")
print(f"  Token length: {len(token)}")
print(f"  MQTT username: {username[:30]}...")
print(f"  MQTT password: (JWT token above)")

# Verify our own token
try:
    parts = token.split(".")
    verify_msg = f"{parts[0]}.{parts[1]}".encode("utf-8")
    sig_bytes = base64url_decode(parts[2])
    verify_key = VerifyKey(bytes.fromhex(public_key))
    verify_key.verify(verify_msg, sig_bytes)
    print("  [OK] JWT self-verification passed")
except Exception as e:
    print(f"  [FAIL] JWT self-verification failed: {e}")
    sys.exit(1)


# ── Step 4: Test MQTT connection ─────────────────────────────────────

print("\n" + "-" * 60)
print("  Step 4: Testing MQTT connection")
print("-" * 60)

import ssl
import threading

result_event = threading.Event()
connect_result = {"rc": None, "error": ""}

def on_connect(client, userdata, flags, rc, *args):
    if rc == 0 or (hasattr(rc, 'value') and rc.value == 0):
        connect_result["rc"] = 0
        print(f"\n  [OK] CONNECTED SUCCESSFULLY!")
    else:
        connect_result["rc"] = rc
        # Decode common MQTT return codes
        rc_val = rc.value if hasattr(rc, 'value') else rc
        rc_messages = {
            1: "Incorrect protocol version",
            2: "Invalid client identifier",
            3: "Server unavailable",
            4: "Bad username or password",
            5: "Not authorized",
        }
        msg = rc_messages.get(rc_val, f"Unknown error (rc={rc})")
        connect_result["error"] = msg
        print(f"\n  [FAIL] Connection refused: {msg}")

        if rc_val in (4, 5):
            print("\n  This means the broker rejected our credentials.")
            print("  Possible causes:")
            print("  - JWT format doesn't match what the broker expects")
            print("  - Public key format issue (upper/lower case)")
            print("  - Broker requires a specific MQTT version or WebSocket path")
    result_event.set()

def on_disconnect(client, userdata, *args):
    if not result_event.is_set():
        connect_result["error"] = "Disconnected before CONNACK"
        result_event.set()

print(f"\n  Connecting to {broker_server}:{broker_port} ({broker_transport})...")

try:
    try:
        client = paho_mqtt.Client(
            callback_api_version=paho_mqtt.CallbackAPIVersion.VERSION2,
            client_id="diag_test",
            transport=broker_transport,
            protocol=paho_mqtt.MQTTv311,
        )
    except (TypeError, AttributeError):
        client = paho_mqtt.Client(
            client_id="diag_test",
            transport=broker_transport,
            protocol=paho_mqtt.MQTTv311,
        )

    client.username_pw_set(username, token)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect

    if broker_tls:
        client.tls_set(cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLS_CLIENT)

    client.connect(broker_server, broker_port)
    client.loop_start()

    # Wait for result (max 15 seconds)
    result_event.wait(timeout=15)

    if not result_event.is_set():
        print("\n  [FAIL] Connection timed out (15s)")

    client.loop_stop()
    client.disconnect()

except Exception as e:
    print(f"\n  [FAIL] Connection error: {e}")


# ── Step 5: Try alternative approaches if failed ─────────────────────

if connect_result["rc"] != 0:
    print("\n" + "-" * 60)
    print("  Step 5: Trying alternative configurations")
    print("-" * 60)

    # Try with lowercase public key
    print("\n  5a. Trying lowercase public key in username + JWT...")

    payload_lower = {
        "publicKey": public_key.lower(),
        "aud": broker_server,
        "iat": now,
        "exp": now + 3600,
    }
    payload_lower_b64 = base64url_encode(json.dumps(payload_lower, separators=(",", ":")).encode("utf-8"))
    message_lower = f"{header_b64}.{payload_lower_b64}".encode("utf-8")
    signed_lower = signing_key.sign(message_lower)
    sig_lower_b64 = base64url_encode(signed_lower.signature)
    token_lower = f"{header_b64}.{payload_lower_b64}.{sig_lower_b64}"
    username_lower = f"v1_{public_key.lower()}"

    result_event_lower = threading.Event()
    result_lower = {"rc": None}

    def on_connect_lower(client, userdata, flags, rc, *args):
        rc_val = rc.value if hasattr(rc, 'value') else rc
        result_lower["rc"] = rc_val
        if rc_val == 0:
            print("  [OK] LOWERCASE WORKS! Update your code to use lowercase keys.")
        else:
            print(f"  [FAIL] Lowercase also rejected (rc={rc})")
        result_event_lower.set()

    try:
        try:
            client2 = paho_mqtt.Client(
                callback_api_version=paho_mqtt.CallbackAPIVersion.VERSION2,
                client_id="diag_lower",
                transport=broker_transport,
                protocol=paho_mqtt.MQTTv311,
            )
        except (TypeError, AttributeError):
            client2 = paho_mqtt.Client(
                client_id="diag_lower",
                transport=broker_transport,
                protocol=paho_mqtt.MQTTv311,
            )

        client2.username_pw_set(username_lower, token_lower)
        client2.on_connect = on_connect_lower
        if broker_tls:
            client2.tls_set(cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLS_CLIENT)
        client2.connect(broker_server, broker_port)
        client2.loop_start()
        result_event_lower.wait(timeout=10)
        if not result_event_lower.is_set():
            print("  [FAIL] Timed out")
        client2.loop_stop()
        client2.disconnect()
    except Exception as e:
        print(f"  [FAIL] Error: {e}")

    # Try with 'sub' claim instead of 'publicKey'
    print("\n  5b. Trying 'sub' claim instead of 'publicKey' in JWT...")

    payload_sub = {
        "sub": public_key.upper(),
        "aud": broker_server,
        "iat": now,
        "exp": now + 3600,
    }
    payload_sub_b64 = base64url_encode(json.dumps(payload_sub, separators=(",", ":")).encode("utf-8"))
    message_sub = f"{header_b64}.{payload_sub_b64}".encode("utf-8")
    signed_sub = signing_key.sign(message_sub)
    sig_sub_b64 = base64url_encode(signed_sub.signature)
    token_sub = f"{header_b64}.{payload_sub_b64}.{sig_sub_b64}"

    result_event_sub = threading.Event()
    result_sub = {"rc": None}

    def on_connect_sub(client, userdata, flags, rc, *args):
        rc_val = rc.value if hasattr(rc, 'value') else rc
        result_sub["rc"] = rc_val
        if rc_val == 0:
            print("  [OK] 'sub' CLAIM WORKS! Update auth_token.py to use 'sub' instead of 'publicKey'.")
        else:
            print(f"  [FAIL] 'sub' claim also rejected (rc={rc})")
        result_event_sub.set()

    try:
        try:
            client3 = paho_mqtt.Client(
                callback_api_version=paho_mqtt.CallbackAPIVersion.VERSION2,
                client_id="diag_sub",
                transport=broker_transport,
                protocol=paho_mqtt.MQTTv311,
            )
        except (TypeError, AttributeError):
            client3 = paho_mqtt.Client(
                client_id="diag_sub",
                transport=broker_transport,
                protocol=paho_mqtt.MQTTv311,
            )

        client3.username_pw_set(username, token_sub)
        client3.on_connect = on_connect_sub
        if broker_tls:
            client3.tls_set(cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLS_CLIENT)
        client3.connect(broker_server, broker_port)
        client3.loop_start()
        result_event_sub.wait(timeout=10)
        if not result_event_sub.is_set():
            print("  [FAIL] Timed out")
        client3.loop_stop()
        client3.disconnect()
    except Exception as e:
        print(f"  [FAIL] Error: {e}")

    # Try MQTTv5
    print("\n  5c. Trying MQTTv5 protocol...")

    result_event_v5 = threading.Event()
    result_v5 = {"rc": None}

    def on_connect_v5(client, userdata, flags, rc, *args):
        rc_val = rc.value if hasattr(rc, 'value') else rc
        result_v5["rc"] = rc_val
        if rc_val == 0:
            print("  [OK] MQTTv5 WORKS! Update mqtt_uplink.py to use MQTTv5.")
        else:
            print(f"  [FAIL] MQTTv5 also rejected (rc={rc})")
        result_event_v5.set()

    try:
        try:
            client4 = paho_mqtt.Client(
                callback_api_version=paho_mqtt.CallbackAPIVersion.VERSION2,
                client_id="diag_v5",
                transport=broker_transport,
                protocol=paho_mqtt.MQTTv5,
            )
        except (TypeError, AttributeError):
            client4 = paho_mqtt.Client(
                client_id="diag_v5",
                transport=broker_transport,
                protocol=paho_mqtt.MQTTv5,
            )

        client4.username_pw_set(username, token)
        client4.on_connect = on_connect_v5
        if broker_tls:
            client4.tls_set(cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLS_CLIENT)
        client4.connect(broker_server, broker_port)
        client4.loop_start()
        result_event_v5.wait(timeout=10)
        if not result_event_v5.is_set():
            print("  [FAIL] Timed out")
        client4.loop_stop()
        client4.disconnect()
    except Exception as e:
        print(f"  [FAIL] Error: {e}")


# ── Summary ──────────────────────────────────────────────────────────

print("\n" + "=" * 60)
print("  Summary")
print("=" * 60)

if connect_result["rc"] == 0:
    print("\n  Connection SUCCESSFUL with default settings.")
    print("  Your observer_config.yaml and keys are correct.")
    print("  Run: python meshcore_observer.py")
else:
    any_worked = False
    if result_lower.get("rc") == 0:
        print("\n  FIX: Use lowercase hex for public key")
        any_worked = True
    if result_sub.get("rc") == 0:
        print("\n  FIX: Use 'sub' instead of 'publicKey' in JWT payload")
        any_worked = True
    if result_v5.get("rc") == 0:
        print("\n  FIX: Use MQTTv5 instead of MQTTv311")
        any_worked = True

    if not any_worked:
        print("\n  All attempts failed. Next steps:")
        print("  1. Ask on the LetsMesh forum: https://forum.letsmesh.net")
        print("     Share this diagnostic output (it contains no secrets)")
        print("  2. Compare with a working meshcoretomqtt setup")
        print("     if you have access to one")
        print(f"  3. Your JWT payload for reference:")
        print(f"     {json.dumps(payload, indent=2)}")

print()
