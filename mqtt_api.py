#!/usr/bin/env python3
"""
RASTIC MQTT API
Bridges MQTT topics to a RESTful HTTPS API.
"""

import os
import sys
import threading
from configparser import ConfigParser
from datetime import datetime, timedelta, timezone

import paho.mqtt.client as mqtt
from flask import Flask, jsonify, render_template_string, request

# ── Global state ─────────────────────────────────────────────────────────────

topics: dict = {}
topics_lock = threading.Lock()
widget_topics: list = []

app = Flask(__name__)


# ── Config ────────────────────────────────────────────────────────────────────

DEFAULTS = {
    "mqtt": {
        "host": "localhost",
        "port": "1883",
        "username": "",
        "password": "",
        "use_tls": "false",
        "ca_cert": "",
        "keepalive": "60",
    },
    "api": {
        "host": "0.0.0.0",
        "port": "443",
        "use_ssl": "true",
        "ssl_cert": "cert.pem",
        "ssl_key": "key.pem",
    },
    "widget": {
        "topics": "",
    },
}


def load_config(path: str = "config.txt") -> ConfigParser:
    config = ConfigParser()
    config.read_dict(DEFAULTS)
    if not config.read(path):
        print(f"Error: config file '{path}' not found.", file=sys.stderr)
        sys.exit(1)
    return config


# ── TLS cert generation ───────────────────────────────────────────────────────

def generate_self_signed_cert(cert_path: str, key_path: str) -> None:
    """Auto-generate a self-signed certificate for localhost."""
    try:
        import ipaddress

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError:
        print(
            "Error: 'cryptography' package is required to auto-generate TLS certs.\n"
            "Install it with:  pip install cryptography\n"
            f"Or provide existing cert/key at: {cert_path}, {key_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Generating self-signed certificate -> {cert_path}, {key_path}")

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(timezone.utc)

    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
            ]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )

    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    with open(key_path, "wb") as f:
        f.write(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            )
        )


# ── MQTT ──────────────────────────────────────────────────────────────────────

_CONNECT_CODES = {
    0: "Connected successfully",
    1: "Refused – incorrect protocol version",
    2: "Refused – invalid client identifier",
    3: "Refused – server unavailable",
    4: "Refused – bad username or password",
    5: "Refused – not authorised",
}


def on_connect(client, userdata, flags, rc):
    print(f"MQTT: {_CONNECT_CODES.get(rc, f'Unknown result code {rc}')}")
    if rc == 0:
        client.subscribe("#")
        print("MQTT: Subscribed to all topics (#)")


def on_disconnect(client, userdata, rc):
    if rc != 0:
        print(f"MQTT: Unexpected disconnect (rc={rc}), reconnecting…")


def on_message(client, userdata, msg):
    try:
        payload = msg.payload.decode("utf-8")
    except UnicodeDecodeError:
        # Fall back to a hex representation for binary payloads
        payload = msg.payload.hex()

    entry = {
        "name": msg.topic,
        "last_message": payload,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    with topics_lock:
        topics[msg.topic] = entry


def start_mqtt(config: ConfigParser) -> None:
    cfg = config["mqtt"]
    client_id = cfg.get("client_id", "").strip() or None
    client = mqtt.Client(client_id=client_id)

    username = cfg.get("username", "").strip()
    password = cfg.get("password", "").strip()
    if username:
        client.username_pw_set(username, password or None)

    if cfg.getboolean("use_tls", False):
        ca_cert = cfg.get("ca_cert", "").strip() or None
        client.tls_set(ca_certs=ca_cert)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    host = cfg.get("host", "localhost")
    port = cfg.getint("port", 1883)
    keepalive = cfg.getint("keepalive", 60)

    print(f"MQTT: Connecting to {host}:{port}")
    client.connect(host, port, keepalive)
    client.loop_forever()


# ── Widget HTML template ──────────────────────────────────────────────────────

WIDGET_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MQTT Widget</title>
<style>
  body { font-family: sans-serif; margin: 0; padding: 12px; background: #f5f5f5; }
  table { width: 100%; border-collapse: collapse; background: #fff; border-radius: 6px;
          overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.15); }
  th { background: #333; color: #fff; text-align: left; padding: 8px 12px; font-size: .85rem; }
  td { padding: 8px 12px; border-bottom: 1px solid #eee; font-size: .9rem; vertical-align: top; }
  tr:last-child td { border-bottom: none; }
  .age { font-size: .8rem; }
  .age.warn  { color: #b45309; }
  .age.stale { color: #b91c1c; }
  .no-data   { color: #9ca3af; font-style: italic; }
</style>
</head>
<body>
<table>
  <thead><tr><th>Name</th><th>Topic</th><th>Last Message</th><th>Updated</th></tr></thead>
  <tbody id="tbody"></tbody>
</table>
<script>
const CONFIGURED = {{ topics | tojson }};
let store = {};

function fmtAge(isoTs) {
  const secs = Math.floor((Date.now() - new Date(isoTs)) / 1000);
  if (secs < 60)  return [secs + 's ago',  ''];
  if (secs < 300) return [Math.floor(secs / 60) + 'm ago', 'warn'];
  if (secs < 3600) return [Math.floor(secs / 60) + 'm ago', 'stale'];
  return [Math.floor(secs / 3600) + 'h ago', 'stale'];
}

function render() {
  const tbody = document.getElementById('tbody');
  tbody.innerHTML = CONFIGURED.map(t => {
    const entry = store[t.topic];
    if (!entry) {
      return `<tr><td>${t.name}</td><td>${t.topic}</td><td colspan="2" class="no-data">No data yet</td></tr>`;
    }
    const [age, cls] = fmtAge(entry.timestamp);
    return `<tr>
      <td>${t.name}</td>
      <td>${t.topic}</td>
      <td>${entry.last_message}</td>
      <td class="age ${cls}">${age}</td>
    </tr>`;
  }).join('');
}

function fetchData() {
  Promise.all(CONFIGURED.map(t =>
    fetch('/mqtt?topic=' + encodeURIComponent(t.topic))
      .then(r => r.json())
      .catch(() => ({}))
  )).then(results => {
    results.forEach(obj => Object.assign(store, obj));
    render();
  });
}

fetchData();
setInterval(render, 1000);
setInterval(fetchData, 5000);
</script>
</body>
</html>"""


# ── REST API ──────────────────────────────────────────────────────────────────

@app.route("/mqtt")
def get_topics():
    """
    Returns all tracked MQTT topics as a JSON object.

    Optional query parameter:
      ?topic=<topic>  – return only the specified topic and all child topics.

    Example:
      GET /mqtt
      GET /mqtt?topic=sensors/temperature
    """
    topic_filter = request.args.get("topic", "").strip()

    with topics_lock:
        snapshot = dict(topics)

    if not topic_filter:
        return jsonify(snapshot)

    # Include exact match and any child topics (prefix/...)
    filtered = {
        k: v
        for k, v in snapshot.items()
        if k == topic_filter or k.startswith(topic_filter + "/")
    }
    return jsonify(filtered)


@app.route("/widget")
def get_widget():
    return render_template_string(WIDGET_HTML, topics=widget_topics)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    global widget_topics
    config = load_config()

    widget_topics = []
    for item in config["widget"]["topics"].split(","):
        item = item.strip()
        if not item:
            continue
        if ":" in item:
            topic, name = item.split(":", 1)
            widget_topics.append({"topic": topic.strip(), "name": name.strip()})
        else:
            widget_topics.append({"topic": item, "name": item})

    mqtt_thread = threading.Thread(target=start_mqtt, args=(config,), daemon=True)
    mqtt_thread.start()

    api_cfg = config["api"]
    use_ssl = api_cfg.getboolean("use_ssl", True)
    host = api_cfg.get("host", "0.0.0.0").strip()
    port = api_cfg.getint("port", 443)

    if use_ssl:
        cert_path = api_cfg.get("ssl_cert", "cert.pem").strip()
        key_path = api_cfg.get("ssl_key", "key.pem").strip()
        if not (os.path.exists(cert_path) and os.path.exists(key_path)):
            generate_self_signed_cert(cert_path, key_path)
        ssl_context = (cert_path, key_path)
        scheme = "https"
    else:
        ssl_context = None
        scheme = "http"

    print(f"API:  Listening on {scheme}://localhost:{port}/mqtt")
    print(f"API:  Widget at {scheme}://localhost:{port}/widget")
    app.run(host=host, port=port, ssl_context=ssl_context)


if __name__ == "__main__":
    main()
