# RASTIC MQTT API

Subscribes to all topics on an MQTT broker and exposes the live topic state as a RESTful HTTPS API.

## Features

- Connects to any MQTT broker and subscribes to all topics (`#`)
- Maintains the latest message and timestamp for every topic seen
- Serves a JSON snapshot over HTTPS at `/mqtt`
- Filter results by topic prefix with `?topic=`
- Auto-generates a self-signed TLS certificate if none is provided

## Requirements

- Python 3.12+
- [UV](https://docs.astral.sh/uv/) for dependency management

## Installation

```bash
git clone https://github.com/dakotawinslow/RASTIC-MQTT-API.git
cd RASTIC-MQTT-API
uv sync
```

## Configuration

Edit `config.txt` before running:

```ini
[mqtt]
host = localhost        # Broker hostname or IP
port = 1883            # 1883 for plain, 8883 for TLS
username =             # Leave blank for anonymous access
password =
use_tls = false        # Set true for TLS/SSL broker connections
ca_cert =              # CA cert path for broker TLS verification
keepalive = 60

[api]
host = 0.0.0.0         # 0.0.0.0 = all interfaces, 127.0.0.1 = localhost only
port = 443             # Use 8443 to avoid needing elevated privileges
ssl_cert = cert.pem    # Auto-generated if files don't exist
ssl_key  = key.pem
```

> **Note on port 443:** Binding to ports below 1024 requires elevated privileges on Linux/macOS (`sudo`). Use port `8443` to run without `sudo`.

## Running

```bash
uv run python mqtt_api.py
```

On first run, if `cert.pem` and `key.pem` don't exist, a self-signed certificate valid for 10 years is generated automatically. Your browser will show a security warning for self-signed certs — this is expected.

## API

### `GET /mqtt`

Returns all tracked topics as a JSON object.

```jsonc
{
  "sensors/temperature/room1": {
    "name": "sensors/temperature/room1",
    "last_message": "22.5",
    "timestamp": "2026-02-26T14:30:00.123456+00:00"
  },
  "actuators/pump": {
    "name": "actuators/pump",
    "last_message": "off",
    "timestamp": "2026-02-26T14:29:55.000000+00:00"
  }
}
```

### `GET /mqtt?topic=<prefix>`

Returns only the specified topic and all child topics.

```
GET /mqtt?topic=sensors/temperature
```

```jsonc
{
  "sensors/temperature/room1": { ... },
  "sensors/temperature/room2": { ... }
}
```

Returns an empty object `{}` if no topics match the prefix.

## Testing

```bash
# Structural unit tests (no broker required)
uv run pytest test_unit.py -v

# Config validation + live broker connectivity
uv run pytest test_config.py -v

# Everything
uv run pytest -v
```

## License

This project is released into the public domain under the [Unlicense](LICENSE).
