from spore._kernel.manager import DockerKernel
import threading

_kernels = {}
_lock = threading.Lock()


def get_kernel(session_id, kernel_name=None):
    with _lock:
        if session_id not in _kernels:
            _kernels[session_id] = DockerKernel(kernel_name=kernel_name)
        return _kernels[session_id]
    
def destroy_kernel(session_id):
    with _lock:
        if session_id in _kernels:
            _kernels[session_id].shutdown()
            del _kernels[session_id]
