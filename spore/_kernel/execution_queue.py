"""Per-session FIFO queue for kernel_execute requests."""

from collections import deque
import threading

from spore._kernel.manager import format_kernel_error
from spore._logger import logging

_queues: dict[str, "_SessionQueue"] = {}
_registry_lock = threading.Lock()


class _SessionQueue:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self._pending: deque[tuple[str | None, str]] = deque()
        self._lock = threading.Lock()
        self._draining = False
        self._current_cell_id: str | None = None

    def submit(self, socketio, cell_id, code, run_fn):
        start_worker = False
        with self._lock:
            for i, (queued_id, _) in enumerate(self._pending):
                if queued_id == cell_id:
                    self._pending[i] = (cell_id, code)
                    return
            self._pending.append((cell_id, code))
            if not self._draining:
                self._draining = True
                start_worker = True

        if start_worker:
            socketio.start_background_task(self._drain, socketio, run_fn)

    def _drain(self, socketio, run_fn):
        while True:
            with self._lock:
                if not self._pending:
                    self._draining = False
                    self._current_cell_id = None
                    socketio.emit("kernel_status", {"status": "idle"}, to=self.session_id)
                    return
                cell_id, code = self._pending.popleft()
                self._current_cell_id = cell_id

            socketio.emit("kernel_status", {"status": "busy"}, to=self.session_id)
            try:
                run_fn(socketio, self.session_id, cell_id, code)
            except Exception as exc:
                logging.error(
                    "Kernel execution failed for session %s cell %s: %s",
                    self.session_id,
                    cell_id,
                    exc,
                    exc_info=True,
                )
                socketio.emit(
                    "kernel_output",
                    {**format_kernel_error("ExecutionError", str(exc)), "cell_id": cell_id},
                    to=self.session_id,
                )
                socketio.emit(
                    "kernel_output",
                    {"type": "done", "cell_id": cell_id},
                    to=self.session_id,
                )

    def clear(self):
        with self._lock:
            self._pending.clear()
            self._current_cell_id = None


def _get_queue(session_id: str) -> _SessionQueue:
    with _registry_lock:
        if session_id not in _queues:
            _queues[session_id] = _SessionQueue(session_id)
        return _queues[session_id]


def submit_execution(socketio, session_id, cell_id, code, run_fn):
    """Enqueue a kernel_execute request for sequential processing."""
    _get_queue(session_id).submit(socketio, cell_id, code, run_fn)


def clear_queue(session_id: str):
    """Drop pending executions for a session (disconnect/restart)."""
    with _registry_lock:
        queue = _queues.pop(session_id, None)
    if queue:
        queue.clear()
