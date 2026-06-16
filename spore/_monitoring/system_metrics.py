"""Collect CPU/RAM metrics with explicit scope when host access is unavailable."""

from __future__ import annotations

import platform
import time
from pathlib import Path
from typing import Any

import psutil
import requests

from spore._config.settings import settings
from spore._logger import logging

# Cached host-bridge availability: None = unknown, True/False = last probe result.
_host_bridge_available: bool | None = None
_host_bridge_checked_at: float = 0.0
_HOST_BRIDGE_RECHECK_SECONDS = 30.0


def _is_containerized() -> bool:
    if Path("/.dockerenv").exists():
        return True
    try:
        cgroup = Path("/proc/1/cgroup").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    markers = ("docker", "containerd", "kubepods", "lxc")
    return any(marker in cgroup for marker in markers)


def _psutil_scope() -> str:
    """Return the scope label for metrics read directly from psutil."""
    if not _is_containerized():
        return "host"
    return "docker"


def _format_ram(used_bytes: float, total_bytes: float | None = None) -> str:
    used_gb = used_bytes / (1024**3)
    if total_bytes is not None and total_bytes > 0:
        total_gb = total_bytes / (1024**3)
        return f"{used_gb:.2f} / {total_gb:.2f} GB"
    return f"{used_gb:.2f} GB"


def _normalize_bridge_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Validate and normalize a host-bridge JSON response."""
    try:
        cpu_val = float(payload.get("cpu_percent", payload.get("cpu", 0)))
        mem = payload.get("memory") or {}
        if isinstance(mem, dict) and mem:
            used = float(mem.get("used", mem.get("used_bytes", 0)))
            total = float(mem.get("total", mem.get("total_bytes", 0)))
        else:
            used = float(payload.get("ram_used_bytes", payload.get("ram_used", 0)))
            total = float(payload.get("ram_total_bytes", payload.get("ram_total", 0)))
    except (TypeError, ValueError):
        return None

    if total <= 0:
        return None

    return {
        "cpu": f"{cpu_val:.1f}%",
        "ram": _format_ram(used, total),
        "cpu_percent": cpu_val,
        "ram_used_gb": round(used / (1024**3), 2),
        "ram_total_gb": round(total / (1024**3), 2),
        "scope": "host",
        "source": "bridge",
        "available": True,
        "platform": payload.get("platform") or platform.system(),
    }


def _fetch_host_bridge() -> dict[str, Any] | None:
    """Query the optional host metrics HTTP endpoint."""
    global _host_bridge_available, _host_bridge_checked_at

    url = (settings.SPORE_HOST_METRICS_URL or "").strip()
    if not url:
        return None

    now = time.monotonic()
    if (
        _host_bridge_available is False
        and (now - _host_bridge_checked_at) < _HOST_BRIDGE_RECHECK_SECONDS
    ):
        return None

    headers: dict[str, str] = {}
    token = (settings.SPORE_HOST_METRICS_TOKEN or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=settings.SPORE_METRICS_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("host bridge response must be a JSON object")
        normalized = _normalize_bridge_payload(payload)
        if normalized is None:
            raise ValueError("host bridge response missing required fields")
        _host_bridge_available = True
        _host_bridge_checked_at = now
        return normalized
    except Exception as exc:
        logging.debug("Host metrics bridge unavailable: %s", exc)
        _host_bridge_available = False
        _host_bridge_checked_at = now
        return None


def _psutil_metrics(cpu_interval: float = 0.0) -> dict[str, Any]:
    """Read metrics from the current runtime namespace (/proc inside container or host)."""
    cpu_percent = psutil.cpu_percent(interval=cpu_interval)
    mem = psutil.virtual_memory()
    scope = _psutil_scope()
    source = "psutil"
    return {
        "cpu": f"{cpu_percent:.1f}%",
        "ram": _format_ram(mem.used, mem.total),
        "cpu_percent": cpu_percent,
        "ram_used_gb": round(mem.used / (1024**3), 2),
        "ram_total_gb": round(mem.total / (1024**3), 2),
        "scope": scope,
        "source": source,
        "available": True,
        "platform": platform.system(),
    }


def get_system_metrics(cpu_interval: float = 1.0) -> dict[str, Any]:
    """
    Return structured CPU/RAM metrics for the workspace monitor.

    Priority:
    1. Optional host metrics bridge (SPORE_HOST_METRICS_URL)
    2. psutil in the current runtime (host on native Linux, docker/container otherwise)
    """
    bridge = _fetch_host_bridge()
    if bridge is not None:
        return bridge
    return _psutil_metrics(cpu_interval=cpu_interval)


def reset_host_bridge_cache() -> None:
    """Reset cached host-bridge probe state (for tests)."""
    global _host_bridge_available, _host_bridge_checked_at
    _host_bridge_available = None
    _host_bridge_checked_at = 0.0
