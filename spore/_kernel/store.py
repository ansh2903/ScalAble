from spore._kernel.manager import DockerKernel
from spore._utils import kernel_runtime
import threading

_kernels = {}
_lock = threading.Lock()


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
