"""Pending client-tool requests for agent loop (Socket.IO handshake)."""

from __future__ import annotations

import threading
from typing import Any

_lock = threading.Lock()
_events: dict[str, threading.Event] = {}
_results: dict[str, dict[str, Any]] = {}
_interrupts: dict[str, threading.Event] = {}


def _key(session_id: str, request_id: str) -> str:
    return f"{session_id}:{request_id}"


def register_wait(session_id: str, request_id: str) -> threading.Event:
    key = _key(session_id, request_id)
    ev = threading.Event()
    with _lock:
        _events[key] = ev
    return ev


def deliver_result(session_id: str, request_id: str, result: dict[str, Any]) -> None:
    key = _key(session_id, request_id)
    with _lock:
        _results[key] = result
        ev = _events.get(key)
    if ev:
        ev.set()


def wait_result(session_id: str, request_id: str, timeout: float = 120.0) -> dict[str, Any]:
    key = _key(session_id, request_id)
    with _lock:
        ev = _events.get(key)
    if not ev:
        return {"ok": False, "error": "No pending request"}
    ev.wait(timeout)
    with _lock:
        result = _results.pop(key, {"ok": False, "error": "Timeout"})
        _events.pop(key, None)
    return result


def register_interrupt(session_id: str) -> threading.Event:
    ev = threading.Event()
    with _lock:
        _interrupts[session_id] = ev
    return ev


def clear_interrupt(session_id: str) -> None:
    with _lock:
        _interrupts.pop(session_id, None)


def trigger_interrupt(session_id: str) -> None:
    with _lock:
        ev = _interrupts.get(session_id)
    if ev:
        ev.set()


def is_interrupted(session_id: str) -> bool:
    with _lock:
        ev = _interrupts.get(session_id)
    return bool(ev and ev.is_set())
