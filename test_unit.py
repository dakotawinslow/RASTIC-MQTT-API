"""
Structural / unit tests for mqtt_api.py
Run from the project root:  pytest test_unit.py
"""

import json
from configparser import ConfigParser
from datetime import datetime
from unittest.mock import MagicMock

import pytest

import mqtt_api


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_msg(topic: str, payload: bytes) -> MagicMock:
    msg = MagicMock()
    msg.topic = topic
    msg.payload = payload
    return msg


def clear_topics():
    with mqtt_api.topics_lock:
        mqtt_api.topics.clear()


def set_topics(data: dict):
    with mqtt_api.topics_lock:
        mqtt_api.topics.clear()
        mqtt_api.topics.update(data)


SAMPLE_TOPICS = {
    "sensors/temperature/room1": {
        "name": "sensors/temperature/room1",
        "last_message": "22.5",
        "timestamp": "2026-01-01T00:00:00+00:00",
    },
    "sensors/temperature/room2": {
        "name": "sensors/temperature/room2",
        "last_message": "21.0",
        "timestamp": "2026-01-01T00:00:00+00:00",
    },
    "sensors/humidity": {
        "name": "sensors/humidity",
        "last_message": "55",
        "timestamp": "2026-01-01T00:00:00+00:00",
    },
    "actuators/pump": {
        "name": "actuators/pump",
        "last_message": "off",
        "timestamp": "2026-01-01T00:00:00+00:00",
    },
}


# ── load_config ───────────────────────────────────────────────────────────────

class TestLoadConfig:
    def test_returns_configparser(self, tmp_path):
        f = tmp_path / "config.txt"
        f.write_text("[mqtt]\n")
        result = mqtt_api.load_config(str(f))
        assert isinstance(result, ConfigParser)

    def test_file_values_override_defaults(self, tmp_path):
        f = tmp_path / "config.txt"
        f.write_text("[mqtt]\nhost = mybroker\nport = 8883\n")
        config = mqtt_api.load_config(str(f))
        assert config["mqtt"]["host"] == "mybroker"
        assert config["mqtt"]["port"] == "8883"

    def test_defaults_filled_when_keys_absent(self, tmp_path):
        f = tmp_path / "config.txt"
        f.write_text("[mqtt]\n")
        config = mqtt_api.load_config(str(f))
        assert config["mqtt"]["host"] == "localhost"
        assert config["mqtt"]["port"] == "1883"
        assert config["mqtt"]["keepalive"] == "60"
        assert config["api"]["port"] == "443"

    def test_missing_file_raises_system_exit(self, tmp_path):
        with pytest.raises(SystemExit):
            mqtt_api.load_config(str(tmp_path / "does_not_exist.txt"))


# ── on_message ────────────────────────────────────────────────────────────────

class TestOnMessage:
    def setup_method(self):
        clear_topics()

    def test_stores_entry_with_correct_fields(self):
        mqtt_api.on_message(None, None, make_msg("sensors/temp", b"22.5"))
        entry = mqtt_api.topics["sensors/temp"]
        assert entry["name"] == "sensors/temp"
        assert entry["last_message"] == "22.5"
        assert "timestamp" in entry

    def test_timestamp_is_valid_iso8601(self):
        mqtt_api.on_message(None, None, make_msg("test/ts", b"x"))
        ts = mqtt_api.topics["test/ts"]["timestamp"]
        datetime.fromisoformat(ts)  # raises if invalid

    def test_binary_payload_falls_back_to_hex(self):
        raw = bytes([0xFF, 0xFE, 0x00, 0xAB])
        mqtt_api.on_message(None, None, make_msg("test/bin", raw))
        assert mqtt_api.topics["test/bin"]["last_message"] == raw.hex()

    def test_overwrites_previous_entry_for_same_topic(self):
        mqtt_api.on_message(None, None, make_msg("sensors/temp", b"20.0"))
        mqtt_api.on_message(None, None, make_msg("sensors/temp", b"25.0"))
        assert mqtt_api.topics["sensors/temp"]["last_message"] == "25.0"
        assert len(mqtt_api.topics) == 1

    def test_multiple_topics_stored_independently(self):
        mqtt_api.on_message(None, None, make_msg("a/b", b"1"))
        mqtt_api.on_message(None, None, make_msg("a/c", b"2"))
        assert len(mqtt_api.topics) == 2
        assert mqtt_api.topics["a/b"]["last_message"] == "1"
        assert mqtt_api.topics["a/c"]["last_message"] == "2"


# ── on_connect ────────────────────────────────────────────────────────────────

class TestOnConnect:
    def test_subscribes_to_wildcard_on_success(self):
        client = MagicMock()
        mqtt_api.on_connect(client, None, None, 0)
        client.subscribe.assert_called_once_with("#")

    @pytest.mark.parametrize("rc", [1, 2, 3, 4, 5])
    def test_does_not_subscribe_on_failure(self, rc):
        client = MagicMock()
        mqtt_api.on_connect(client, None, None, rc)
        client.subscribe.assert_not_called()


# ── GET /mqtt ─────────────────────────────────────────────────────────────────

class TestGetTopicsEndpoint:
    def setup_method(self):
        set_topics(SAMPLE_TOPICS)
        self.client = mqtt_api.app.test_client()

    def test_returns_all_topics_without_filter(self):
        resp = self.client.get("/mqtt")
        data = json.loads(resp.data)
        assert set(data.keys()) == set(SAMPLE_TOPICS.keys())

    def test_response_is_json(self):
        resp = self.client.get("/mqtt")
        assert resp.status_code == 200
        assert "application/json" in resp.content_type

    def test_filter_returns_children_of_prefix(self):
        resp = self.client.get("/mqtt?topic=sensors/temperature")
        data = json.loads(resp.data)
        assert "sensors/temperature/room1" in data
        assert "sensors/temperature/room2" in data
        assert "sensors/humidity" not in data
        assert "actuators/pump" not in data

    def test_filter_returns_exact_match(self):
        resp = self.client.get("/mqtt?topic=sensors/humidity")
        data = json.loads(resp.data)
        assert list(data.keys()) == ["sensors/humidity"]

    def test_filter_returns_both_exact_and_children(self):
        # Add an exact-match entry alongside its children
        set_topics({
            **SAMPLE_TOPICS,
            "sensors/temperature": {
                "name": "sensors/temperature",
                "last_message": "agg",
                "timestamp": "2026-01-01T00:00:00+00:00",
            },
        })
        resp = self.client.get("/mqtt?topic=sensors/temperature")
        data = json.loads(resp.data)
        assert "sensors/temperature" in data
        assert "sensors/temperature/room1" in data
        assert "sensors/temperature/room2" in data

    def test_filter_no_match_returns_empty_object(self):
        resp = self.client.get("/mqtt?topic=nonexistent/topic")
        data = json.loads(resp.data)
        assert data == {}

    def test_filter_does_not_match_on_partial_word(self):
        # "sensors/temperature" must NOT match "sensors/temperaturexyz"
        set_topics({
            **SAMPLE_TOPICS,
            "sensors/temperaturexyz": {
                "name": "sensors/temperaturexyz",
                "last_message": "x",
                "timestamp": "2026-01-01T00:00:00+00:00",
            },
        })
        resp = self.client.get("/mqtt?topic=sensors/temperature")
        data = json.loads(resp.data)
        assert "sensors/temperaturexyz" not in data

    def test_empty_store_returns_empty_object(self):
        clear_topics()
        resp = self.client.get("/mqtt")
        assert json.loads(resp.data) == {}

    def test_entry_structure_has_required_fields(self):
        resp = self.client.get("/mqtt")
        data = json.loads(resp.data)
        for entry in data.values():
            assert "name" in entry
            assert "last_message" in entry
            assert "timestamp" in entry


# ── generate_self_signed_cert ─────────────────────────────────────────────────

class TestGenerateSelfSignedCert:
    def test_creates_cert_and_key_files(self, tmp_path):
        cert = str(tmp_path / "cert.pem")
        key = str(tmp_path / "key.pem")
        mqtt_api.generate_self_signed_cert(cert, key)
        assert (tmp_path / "cert.pem").exists()
        assert (tmp_path / "key.pem").exists()

    def test_cert_is_pem_encoded(self, tmp_path):
        cert = str(tmp_path / "cert.pem")
        key = str(tmp_path / "key.pem")
        mqtt_api.generate_self_signed_cert(cert, key)
        content = (tmp_path / "cert.pem").read_text()
        assert "-----BEGIN CERTIFICATE-----" in content
        assert "-----END CERTIFICATE-----" in content

    def test_key_is_pem_encoded(self, tmp_path):
        cert = str(tmp_path / "cert.pem")
        key = str(tmp_path / "key.pem")
        mqtt_api.generate_self_signed_cert(cert, key)
        content = (tmp_path / "key.pem").read_text()
        assert "-----BEGIN" in content
        assert "PRIVATE KEY-----" in content

    def test_cert_is_valid_x509(self, tmp_path):
        from cryptography import x509
        cert_path = str(tmp_path / "cert.pem")
        key_path = str(tmp_path / "key.pem")
        mqtt_api.generate_self_signed_cert(cert_path, key_path)
        raw = (tmp_path / "cert.pem").read_bytes()
        cert = x509.load_pem_x509_certificate(raw)
        assert cert.subject == cert.issuer  # self-signed
