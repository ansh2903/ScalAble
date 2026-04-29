from spore._kernel.manager import SessionKernel
import threading

_kernels = {}
_lock = threading.Lock()

def get_kernel(session_id, kernel_name = 'python3'):
    with _lock:
        if session_id not in _kernels:
            _kernels[session_id] = SessionKernel(kernel_name)
        return _kernels[session_id]
    
def destroy_kernel(session_id):
    with _lock:
        if session_id in _kernels:
            _kernels[session_id].shutdown()
            del _kernels[session_id]
