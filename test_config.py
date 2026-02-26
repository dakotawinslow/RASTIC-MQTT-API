"""
Config validation tests for config.txt
Tests that the file is well-formed AND that the broker credentials actually work.
Run from the project root:  pytest test_config.py
"""

import socket
import threading

import pytest
import paho.mqtt.client as mqtt

import mqtt_api

CONFIG_PATH = "config.txt"


@pytest.fixture(scope="module")
def config():
    return mqtt_api.load_config(CONFIG_PATH)


# ── Structure & format ────────────────────────────────────────────────────────

class TestConfigStructure:
    def test_mqtt_section_present(self, config):
        assert "mqtt" in config, "config.txt is missing the [mqtt] section"

    def test_api_section_present(self, config):
        assert "api" in config, "config.txt is missing the [api] section"

    def test_mqtt_host_is_not_empty(self, config):
        host = config["mqtt"].get("host", "").strip()
        assert host, "mqtt.host must not be empty"

    def test_mqtt_port_is_an_integer(self, config):
        try:
            config.getint("mqtt", "port")
        except ValueError:
            pytest.fail("mqtt.port must be an integer")

    def test_mqtt_port_in_valid_range(self, config):
        port = config.getint("mqtt", "port")
        assert 1 <= port <= 65535, f"mqtt.port ({port}) is outside the valid range 1–65535"

    def test_mqtt_keepalive_is_a_positive_integer(self, config):
        try:
            keepalive = config.getint("mqtt", "keepalive")
        except ValueError:
            pytest.fail("mqtt.keepalive must be an integer")
        assert keepalive > 0, f"mqtt.keepalive ({keepalive}) must be greater than 0"

    def test_mqtt_use_tls_is_a_boolean(self, config):
        try:
            config.getboolean("mqtt", "use_tls")
        except ValueError:
            pytest.fail("mqtt.use_tls must be a boolean (true/false/yes/no/1/0)")

    def test_mqtt_password_set_when_username_is_set(self, config):
        username = config["mqtt"].get("username", "").strip()
        password = config["mqtt"].get("password", "").strip()
        if username:
            assert password, (
                "mqtt.password must be set when mqtt.username is provided"
            )

    def test_api_host_is_not_empty(self, config):
        host = config["api"].get("host", "").strip()
        assert host, "api.host must not be empty"

    def test_api_port_is_an_integer(self, config):
        try:
            config.getint("api", "port")
        except ValueError:
            pytest.fail("api.port must be an integer")

    def test_api_port_in_valid_range(self, config):
        port = config.getint("api", "port")
        assert 1 <= port <= 65535, f"api.port ({port}) is outside the valid range 1–65535"

    def test_api_ssl_cert_key_are_not_empty(self, config):
        cert = config["api"].get("ssl_cert", "").strip()
        key = config["api"].get("ssl_key", "").strip()
        assert cert, "api.ssl_cert must not be empty"
        assert key, "api.ssl_key must not be empty"


# ── Live connectivity ─────────────────────────────────────────────────────────

class TestMQTTConnectivity:
    def test_broker_host_is_reachable(self, config):
        """TCP-level check: the broker host:port must accept a socket connection."""
        host = config["mqtt"]["host"]
        port = config.getint("mqtt", "port")
        try:
            sock = socket.create_connection((host, port), timeout=5)
            sock.close()
        except (socket.timeout, ConnectionRefusedError, OSError) as exc:
            pytest.fail(
                f"Cannot reach MQTT broker at {host}:{port} — {exc}\n"
                "Check that the broker is running and that host/port in config.txt are correct."
            )

    def test_broker_accepts_credentials(self, config):
        """
        Full MQTT handshake: connect with the credentials from config.txt and
        verify the broker responds with rc=0 (accepted).
        """
        cfg = config["mqtt"]
        host = cfg["host"]
        port = cfg.getint("port")

        result = {"rc": None}
        connected = threading.Event()

        def on_connect(client, userdata, flags, rc):
            result["rc"] = rc
            connected.set()

        client = mqtt.Client()

        username = cfg.get("username", "").strip()
        password = cfg.get("password", "").strip()
        if username:
            client.username_pw_set(username, password or None)

        if cfg.getboolean("use_tls", False):
            ca_cert = cfg.get("ca_cert", "").strip() or None
            client.tls_set(ca_certs=ca_cert)

        client.on_connect = on_connect

        try:
            client.connect(host, port, keepalive=10)
        except Exception as exc:
            pytest.fail(
                f"mqtt.Client.connect() raised an exception: {exc}\n"
                "Check that the broker is reachable and TLS settings are correct."
            )

        client.loop_start()
        timed_out = not connected.wait(timeout=10)
        client.loop_stop()
        client.disconnect()

        if timed_out:
            pytest.fail(
                f"No response from MQTT broker at {host}:{port} within 10 seconds."
            )

        code_desc = mqtt_api._CONNECT_CODES.get(result["rc"], f"rc={result['rc']}")
        assert result["rc"] == 0, (
            f"Broker rejected the connection: {code_desc}\n"
            "Check mqtt.username and mqtt.password in config.txt."
        )
