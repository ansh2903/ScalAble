"""Tests for hybrid system metrics provider."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from spore._config.settings import settings
from spore._monitoring import system_metrics as sm


@pytest.fixture(autouse=True)
def reset_bridge_cache():
    sm.reset_host_bridge_cache()
    yield
    sm.reset_host_bridge_cache()


@pytest.fixture
def metrics_settings(monkeypatch):
    monkeypatch.setattr(settings, "SPORE_HOST_METRICS_URL", "")
    monkeypatch.setattr(settings, "SPORE_HOST_METRICS_TOKEN", "")
    monkeypatch.setattr(settings, "SPORE_METRICS_TIMEOUT", 2.0)


def test_psutil_metrics_native_host_scope(metrics_settings, monkeypatch):
    monkeypatch.setattr(sm, "_is_containerized", lambda: False)
    fake_mem = MagicMock(used=2 * 1024**3, total=16 * 1024**3)

    with patch.object(sm.psutil, "cpu_percent", return_value=42.5), patch.object(
        sm.psutil, "virtual_memory", return_value=fake_mem
    ):
        result = sm.get_system_metrics(cpu_interval=0)

    assert result["scope"] == "host"
    assert result["source"] == "psutil"
    assert result["cpu"] == "42.5%"
    assert result["ram"] == "2.00 / 16.00 GB"
    assert result["ram_used_gb"] == 2.0
    assert result["ram_total_gb"] == 16.0
    assert result["available"] is True


def test_psutil_metrics_docker_scope_when_containerized(metrics_settings, monkeypatch):
    monkeypatch.setattr(sm, "_is_containerized", lambda: True)
    fake_mem = MagicMock(used=1 * 1024**3, total=4 * 1024**3)

    with patch.object(sm.psutil, "cpu_percent", return_value=10.0), patch.object(
        sm.psutil, "virtual_memory", return_value=fake_mem
    ):
        result = sm.get_system_metrics(cpu_interval=0)

    assert result["scope"] == "docker"
    assert result["source"] == "psutil"
    assert result["cpu"] == "10.0%"
    assert result["ram"] == "1.00 / 4.00 GB"


def test_host_bridge_success(metrics_settings, monkeypatch):
    monkeypatch.setattr(
        settings,
        "SPORE_HOST_METRICS_URL",
        "http://host.docker.internal:8765/metrics",
    )
    monkeypatch.setattr(settings, "SPORE_HOST_METRICS_TOKEN", "secret")

    bridge_payload = {
        "cpu_percent": 55.2,
        "memory": {"used": 8 * 1024**3, "total": 32 * 1024**3},
        "platform": "Windows",
    }
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = bridge_payload

    with patch.object(sm.requests, "get", return_value=mock_response) as mock_get:
        result = sm.get_system_metrics(cpu_interval=0)

    assert result["scope"] == "host"
    assert result["source"] == "bridge"
    assert result["cpu"] == "55.2%"
    assert result["ram"] == "8.00 / 32.00 GB"
    assert result["platform"] == "Windows"
    mock_get.assert_called_once()
    headers = mock_get.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer secret"


def test_host_bridge_failure_falls_back_to_psutil(metrics_settings, monkeypatch):
    monkeypatch.setattr(
        settings,
        "SPORE_HOST_METRICS_URL",
        "http://host.docker.internal:8765/metrics",
    )
    monkeypatch.setattr(sm, "_is_containerized", lambda: True)
    fake_mem = MagicMock(used=512 * 1024**2, total=2 * 1024**3)

    with patch.object(sm.requests, "get", side_effect=ConnectionError("refused")), patch.object(
        sm.psutil, "cpu_percent", return_value=5.0
    ), patch.object(sm.psutil, "virtual_memory", return_value=fake_mem):
        result = sm.get_system_metrics(cpu_interval=0)

    assert result["scope"] == "docker"
    assert result["source"] == "psutil"


def test_normalize_bridge_payload_rejects_invalid():
    assert sm._normalize_bridge_payload({}) is None
    assert sm._normalize_bridge_payload({"cpu_percent": "bad"}) is None


def test_is_containerized_detects_dockerenv(tmp_path, monkeypatch):
    monkeypatch.setattr(sm.Path, "exists", lambda self: str(self) == "/.dockerenv")
    assert sm._is_containerized() is True


def test_format_ram_without_total():
    assert sm._format_ram(2 * 1024**3) == "2.00 GB"
