from spore._kernel.manager import DockerKernel
from spore._utils import kernel_runtime
from spore._logger import logging
import threading

_kernels = {}
_lock = threading.Lock()
_generation = 0
_socketio = None


def register_socketio(socketio):
    global _socketio
    _socketio = socketio


def kernel_generation() -> int:
    return _generation


def bump_kernel_generation() -> int:
    global _generation
    with _lock:
        _generation += 1
        return _generation


def destroy_all_kernels():
    with _lock:
        for kernel in _kernels.values():
            try:
                kernel.shutdown()
            except Exception:
                pass
        _kernels.clear()


def invalidate_kernels(reason: str = "config_changed") -> int:
    """Bump generation, tear down all kernels, and notify connected clients."""
    from spore._kernel.execution_queue import clear_all_queues
    from spore._kernel.image_build import stop_all_kernel_containers
    from spore._kernel.manager import get_docker_client

    gen = bump_kernel_generation()
    destroy_all_kernels()
    try:
        stop_all_kernel_containers(get_docker_client())
    except Exception as exc:
        logging.warning("Orphan kernel container cleanup failed: %s", exc)
    if _socketio is not None:
        clear_all_queues(socketio=_socketio, reason=reason)
        _socketio.emit(
            "kernel_status",
            {"status": "invalidated", "kernel_generation": gen, "content": reason},
        )
    else:
        clear_all_queues(reason=reason)
    return gen


def get_kernel(session_id, kernel_name=None):
    with _lock:
        if session_id not in _kernels:
            runtime = kernel_runtime()
            _kernels[session_id] = DockerKernel(
                kernel_name=kernel_name or runtime["kernel_spec_name"],
                startup_code=runtime["startup_code"],
                packages=runtime["packages"],
            )
        return _kernels[session_id]
    
def destroy_kernel(session_id):
    with _lock:
        if session_id in _kernels:
            _kernels[session_id].shutdown()
            del _kernels[session_id]
