from jupyter_client import KernelManager
from jupyter_client.kernelspec import KernelSpecManager

from spore._logger import logging
from spore._exception import CustomException

class SessionKernel:
    def __init__(self, kernel_name='python3', startup_code=''):
        self.km = KernelManager(kernel_name=kernel_name)
        self.km.start_kernel()
        self.kc = self.km.client()
        self.kc.start_channels()
        self._wait_for_ready()
        self.user_startup_code = startup_code
        self._inject_startup_config()
        logging.info(f"Kernel started: {kernel_name}")

    def _inject_startup_config(self):
        BASE_STARTUP = """
    try:
        import plotly.io as pio
        # 'plotly_mimetype' is the cleanest way to just get the raw JSON bundle
        pio.renderers.default = "plotly_mimetype"
    except ImportError:
        pass
    try:
        pass
        # import matplotlib
        # matplotlib.use('Agg') 
    except ImportError:
        pass
    """
        full_code = BASE_STARTUP + '\n' + self.user_startup_code
        for _ in self.execute(full_code):
            pass

    
    def _wait_for_ready(self):
        # Proactive approach: Send a request and wait for the specific reply
        # This is much faster than polling the broadcast channel
        self.kc.kernel_info()
        try:
            # Wait for the kernel_info_reply on the SHELL channel
            # 5 seconds is usually plenty for a local kernel
            self.kc.get_shell_msg(timeout=5)
            logging.info("Kernel handshake complete.")
        except Exception:
            logging.warning("Kernel info request timed out, checking IOPub fallback...")
            # Fallback to your old method only if the shell is unresponsive
            self._iopub_poll_fallback()

    def _iopub_poll_fallback(self):
        import time
        start_time = time.time()
        while time.time() - start_time < 10: # Max 10 second total wait
            try:
                msg = self.kc.get_iopub_msg(timeout=0.2) # Small, snappy timeout
                if (msg['header']['msg_type'] == 'status' and 
                    msg['content']['execution_state'] == 'idle'):
                    break
            except Exception:
                continue

    def execute(self, code):
        """
        Generator - yields structured output chunks as the kernel produces them.
        Blocks until cell finished.
        """

        msg_id = self.kc.execute(code)

        while True:
            try:
                msg = self.kc.get_iopub_msg(timeout=30)
                msg_type = msg['header']['msg_type']
                content = msg['content']

                if msg['parent_header'].get('msg_id') != msg_id:
                    continue

                # Streaming is for things like loops, generators and iterators thats why.
                if msg_type == 'stream':
                    # stdout, stderr
                    yield {
                        "type": "stream",
                        "stream": content['name'],
                        "content": content['text']
                    }

                elif msg_type == 'display_data':
                    # plots like from matplotlib, seaborn etc.
                    yield {
                        "type": "display",
                        "data": content['data'] # dick of MIME types
                    }

                elif msg_type == 'execute_result':
                    # dont know what this one is
                    yield {
                        "type": "result",
                        "data": content['data'],
                        "execution_count": content['execution_count']
                    }

                elif msg_type == 'error':
                    # you blew it up
                    yield {
                        "type": "error",
                        "ename": content['ename'],
                        "evalue": content['evalue'],
                        "traceback": content['traceback']
                    }

                elif msg_type == 'status':
                    if content['execution_state'] == 'idle':
                        yield {
                            "type": "done"
                        }
                        break

            except Exception as e:
                yield {
                    "type": "error",
                    "ename": "KernelTimeout",
                    "evalue": str(e)
                }
                break
    
    def interrupt(self):
        self.km.interrupt_kernel()
        logging.info('Kernel Interrupted')

    def restart(self):
        self.km.restart_kernel()
        self._wait_for_ready()
        self._inject_startup_config()
        logging.info('Kernel Restarted')

    def shutdown(self):
        self.kc.stop_channels()
        self.km.shutdown_kernel()
        logging.info('Kernel Shutdown')

    @staticmethod
    def available_kernels():
        return list(KernelSpecManager().get_all_specs().keys())
