"""Unit tests for connector base layer, registry, and SourceConnector dispatch."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from spore._connectors import SourceConnector
from spore._connectors.base import (
    BaseSource,
    SecurityConfig,
    SourceCapabilities,
    SourceKind,
    TransportConfig,
)
from spore._connectors.db.postgresql import PostgreSQLSource, _qi, _qs
from spore._connectors.registry import REGISTRY


# ── SecurityConfig ────────────────────────────────────────────────────────────


def test_security_config_off():
    cfg = SecurityConfig.from_dict({}, use_ssl=False)
    assert cfg.ssl_mode == "disable"


def test_security_config_on_defaults_verify_full():
    cfg = SecurityConfig.from_dict({}, use_ssl=True)
    assert cfg.ssl_mode == "verify-full"


def test_security_config_paths_passthrough():
    cfg = SecurityConfig.from_dict(
        {
            "sslmode": "require",
            "sslrootcert": "/tmp/ca.pem",
            "sslcert": "/tmp/client.crt",
            "sslkey": "/tmp/client.key",
        },
        use_ssl=True,
    )
    assert cfg.ssl_mode == "require"
    assert cfg.ca_cert_path == "/tmp/ca.pem"
    assert cfg.client_cert_path == "/tmp/client.crt"
    assert cfg.client_key_path == "/tmp/client.key"


# ── TransportConfig ───────────────────────────────────────────────────────────


def test_transport_config_off():
    cfg = TransportConfig.from_dict({}, use_ssh=False)
    assert cfg.use_ssh_tunnel is False


def test_transport_config_on():
    cfg = TransportConfig.from_dict(
        {
            "ssh_host": "bastion.example.com",
            "ssh_port": "2222",
            "ssh_user": "ubuntu",
            "ssh_private_key": "/tmp/id_rsa",
            "host": "db.internal",
            "port": "5432",
        },
        use_ssh=True,
    )
    assert cfg.use_ssh_tunnel is True
    assert cfg.ssh_host == "bastion.example.com"
    assert cfg.ssh_port == 2222
    assert cfg.ssh_user == "ubuntu"
    assert cfg.ssh_private_key == "/tmp/id_rsa"
    assert cfg.remote_host == "db.internal"
    assert cfg.remote_port == 5432


# ── SQL identifier / literal escaping ───────────────────────────────────────


def test_qi_escapes_double_quotes():
    assert _qi('weird"name') == '"weird""name"'


def test_qs_escapes_single_quotes():
    assert _qs("O'Brien") == "'O''Brien'"


# ── Registry ────────────────────────────────────────────────────────────────


def test_registry_keys():
    assert set(REGISTRY.keys()) == {
        "postgresql",
        "mysql",
        "mssql",
        "sqlite",
        "mongodb",
        "bigquery",
        "snowflake",
        "redshift",
        "clickhouse",
        "databricks",
        "rest_api",
        "graphql_api",
        "csv_file",
        "excel_file",
        "json_file",
        "parquet_file",
    }


# ── SourceConnector dispatch ─────────────────────────────────────────────────


def test_source_connector_unknown_type_raises_valueerror():
    with pytest.raises(ValueError, match="No source handler registered"):
        SourceConnector(
            kind="database",
            source_type="nonexistent",
            creds={},
            use_ssh=False,
            use_ssl=False,
        )


def test_source_connector_capability_routing():
    class NoIngestSource(BaseSource):
        kind = SourceKind.DATABASE
        capabilities = SourceCapabilities(
            can_preview=False,
            can_ingest=False,
            can_stream=False,
            needs_ssh=False,
            needs_credentials=False,
        )

        def _create_connection(self, host, port):
            return MagicMock()

        def test_connection(self):
            return True, "ok"

        def fetch_metadata(self):
            return True, {}

    with patch.dict(REGISTRY, {"stub": NoIngestSource}, clear=False):
        connector = SourceConnector(
            kind="database",
            source_type="stub",
            creds={},
            use_ssh=False,
            use_ssl=False,
        )
        chunks = list(connector.ingest("stream", "SELECT 1"))
        assert len(chunks) == 1
        assert chunks[0]["type"] == "error"
        assert "does not support ingestion" in chunks[0]["content"]


def test_source_connector_preview_yields_error_when_unsupported():
    class NoPreviewSource(BaseSource):
        kind = SourceKind.DATABASE
        capabilities = SourceCapabilities(
            can_preview=False,
            can_ingest=False,
            can_stream=False,
            needs_ssh=False,
            needs_credentials=False,
        )

        def _create_connection(self, host, port):
            return MagicMock()

        def test_connection(self):
            return True, "ok"

        def fetch_metadata(self):
            return True, {}

    with patch.dict(REGISTRY, {"nopreview": NoPreviewSource}, clear=False):
        connector = SourceConnector(
            kind="database",
            source_type="nopreview",
            creds={},
            use_ssh=False,
            use_ssl=False,
        )
        chunks = list(connector.preview("SELECT 1"))
        assert len(chunks) == 1
        assert chunks[0]["type"] == "error"
        assert "doesn't support live preview" in chunks[0]["content"]


# ── PostgreSQL URI assembly ───────────────────────────────────────────────────


def test_postgres_uri_assembly():
    src = PostgreSQLSource(
        {
            "user": "user@name",
            "password": "p@ss",
            "database": "mydb",
            "port": "5432",
        },
        use_ssh=False,
        use_ssl=True,
    )
    uri = src._postgres_uri("db.example.com", 5432)
    assert "user%40name" in uri
    assert "p%40ss" in uri
    assert "mydb" in uri
    assert "sslmode=verify-full" in uri


# ── Docker localhost remap ────────────────────────────────────────────────────


def test_connection_context_docker_remap():
    captured: dict = {}

    class CaptureSource(PostgreSQLSource):
        def _create_connection(self, host, port):
            captured["host"] = host
            captured["port"] = port
            return MagicMock()

    src = CaptureSource(
        {"host": "localhost", "port": "5432", "user": "u", "password": "p", "database": "d"},
        use_ssh=False,
        use_ssl=False,
    )

    with patch("spore._utils.is_running_in_docker", return_value=True):
        with src.connection_context():
            pass

    assert captured["host"] == "host.docker.internal"
