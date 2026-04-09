from jupyter_client import KernelManager
from jupyter_client.kernelspec import KernelSpecManager

from src.core.logger import logging
from src.core.exception import CustomException

class SessionKernel:
    def __init__(self, kernel_name='python3'):
        self.km = KernelManager(kernel_name=kernel_name)
        self.km.start_kernel()
        self.kc = self.km.client()
        self.kc.start_channels()
        self.wait_for_ready()
        logging.info(f"Kernel started: {kernel_name}")
    
    def _wait_for_ready(self):
        while True:
            try:
                msg = self.kc.get_iopub_msg(timeout=10)
                if (msg['header']['msg_type'] == 'status' and msg['content']['execution_state'] == 'idle'):
                    break
            
            except Exception:
                logging.info('Kernel Timeout.')
                break

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
        logging('Kernel Restarted')

    def shutdown(self):
        self.kc.stop_channels()
        self.km.shutdown_kernel()
        logging.info('Kernel Shutdown')

    @staticmethod
    def available_kernels():
        return list(KernelSpecManager().get_all_specs().keys)