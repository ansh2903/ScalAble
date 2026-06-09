from __future__ import annotations

import secrets
import time

import docker
from docker.errors import DockerException, NotFound
from jupyter_client.blocking import BlockingKernelClient

from spore._config.settings import settings
from spore._exception import CustomException
from spore._logger import logging
from spore._utils import kernel_runtime, security_runtime

# Fixed in-container ZMQ ports; published to the DinD host for client access.
_KERNEL_PORTS = {
    "shell": 50000,
    "iopub": 50001,
    "stdin": 50002,
    "control": 50003,
    "hb": 50004,
}


def get_docker_client():
    host = settings.DOCKER_HOST
    if host:
        return docker.DockerClient(base_url=host)
    return docker.from_env()


def _docker_client():
    return get_docker_client()


def _new_connection_key() -> str:
    return secrets.token_hex(16)


def _port_bindings() -> dict[str, tuple[int, int] | None]:
  """Map container ports to auto-assigned host ports inside DinD."""
  return {f"{port}/tcp": None for port in _KERNEL_PORTS.values()}


def _inspect_host_ports(container) -> dict[str, int]:
    ports = container.attrs.get("NetworkSettings", {}).get("Ports") or {}
    mapping: dict[str, int] = {}
    for name, internal in _KERNEL_PORTS.items():
        key = f"{internal}/tcp"
        bindings = ports.get(key)
        if not bindings:
            raise CustomException(f"Kernel port {key} is not published")
        mapping[name] = int(bindings[0]["HostPort"])
    return mapping


class DockerKernel:
    """Per-session Jupyter kernel running in an isolated Docker container."""

    def __init__(
        self,
        kernel_name: str | None = None,
        startup_code: str = "",
        packages: list | None = None,
    ):
        runtime = kernel_runtime()
        self.kernel_name = kernel_name or runtime["kernel_spec_name"]
        self.user_startup_code = startup_code if startup_code else runtime["startup_code"]
        self.packages = packages if packages is not None else runtime["packages"]
        self._security = security_runtime()
        self._key = _new_connection_key()
        self._container = None
        self.kc = BlockingKernelClient()
        self._start_container()
        self._connect_client()
        self._wait_for_ready()
        self._inject_startup_config()
        logging.info("Docker kernel started: %s (%s)", self.kernel_name, self._container.short_id)

    def _start_container(self) -> None:
        client = _docker_client()
        name = f"spore-kernel-{secrets.token_hex(6)}"
        env = {
            "KERNEL_SHELL_PORT": str(_KERNEL_PORTS["shell"]),
            "KERNEL_IOPUB_PORT": str(_KERNEL_PORTS["iopub"]),
            "KERNEL_STDIN_PORT": str(_KERNEL_PORTS["stdin"]),
            "KERNEL_CONTROL_PORT": str(_KERNEL_PORTS["control"]),
            "KERNEL_HB_PORT": str(_KERNEL_PORTS["hb"]),
            "KERNEL_KEY": self._key,
        }
        volumes = {
            settings.KERNEL_VOLUME_BIND: {
                "bind": settings.KERNEL_DATA_MOUNT,
                "mode": "rw",
            }
        }
        runtime = kernel_runtime()
        sec = security_runtime()
        try:
            self._container = client.containers.run(
                runtime["image"],
                name=name,
                detach=True,
                environment=env,
                ports=_port_bindings(),
                volumes=volumes,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges"],
                mem_limit=sec["mem_limit"],
                pids_limit=sec["pids_limit"],
                remove=False,
            )
        except DockerException as exc:
            raise CustomException(f"Failed to start kernel container: {exc}") from exc

        # Wait briefly for port bindings to appear.
        for _ in range(30):
            self._container.reload()
            try:
                _inspect_host_ports(self._container)
                return
            except CustomException:
                time.sleep(0.2)
        raise CustomException("Kernel container started but ports were not published")

    def _connect_client(self) -> None:
        host_ports = _inspect_host_ports(self._container)
        conn_info = {
            "ip": settings.KERNEL_HOST,
            "shell_port": host_ports["shell"],
            "iopub_port": host_ports["iopub"],
            "stdin_port": host_ports["stdin"],
            "control_port": host_ports["control"],
            "hb_port": host_ports["hb"],
            "key": self._key,
            "transport": "tcp",
            "signature_scheme": "hmac-sha256",
            "kernel_name": "python3",
        }
        self.kc.load_connection_info(conn_info)
        self.kc.start_channels()

    def _inject_startup_config(self):
        pip_lines = []
        for pkg in self.packages or []:
            name = (pkg.get("name") or "").strip()
            if not name:
                continue
            version = (pkg.get("version") or "").strip()
            spec = f"{name}=={version}" if version else name
            pip_lines.append(f"subprocess.run(['pip', 'install', {spec!r}], check=False)")
        full_code = ""
        if pip_lines:
            full_code += "import subprocess\ntry:\n" + "\n".join(f"    {line}" for line in pip_lines) + "\nexcept Exception:\n    pass\n"
        if self.user_startup_code:
            full_code += "\n" + self.user_startup_code
        for _ in self.execute(full_code, enforce_timeout=False):
            pass

    def _wait_for_ready(self):
        self.kc.kernel_info()
        try:
            self.kc.get_shell_msg(timeout=15)
            logging.info("Kernel handshake complete.")
        except Exception:
            logging.warning("Kernel info request timed out, checking IOPub fallback...")
            self._iopub_poll_fallback()

    def _iopub_poll_fallback(self):
        start_time = time.time()
        while time.time() - start_time < 20:
            try:
                msg = self.kc.get_iopub_msg(timeout=0.2)
                if (
                    msg["header"]["msg_type"] == "status"
                    and msg["content"]["execution_state"] == "idle"
                ):
                    break
            except Exception:
                continue

    def execute(self, code, enforce_timeout: bool = True):
        """Yield structured output chunks as the kernel produces them."""
        msg_id = self.kc.execute(code)
        exec_timeout = self._security.get("exec_timeout", 30)
        started = time.time()
        poll_timeout = 30

        while True:
            try:
                if enforce_timeout and exec_timeout > 0:
                    elapsed = time.time() - started
                    if elapsed >= exec_timeout:
                        self.interrupt()
                        yield {
                            "type": "error",
                            "ename": "KernelTimeout",
                            "evalue": f"Execution exceeded {exec_timeout}s limit",
                        }
                        yield {"type": "done"}
                        break
                    poll_timeout = min(30, max(0.5, exec_timeout - elapsed))

                msg = self.kc.get_iopub_msg(timeout=poll_timeout)
                msg_type = msg["header"]["msg_type"]
                content = msg["content"]

                if msg["parent_header"].get("msg_id") != msg_id:
                    continue

                if msg_type == "stream":
                    yield {
                        "type": "stream",
                        "stream": content["name"],
                        "content": content["text"],
                    }

                elif msg_type == "display_data":
                    yield {
                        "type": "display",
                        "data": content["data"],
                    }

                elif msg_type == "execute_result":
                    yield {
                        "type": "result",
                        "data": content["data"],
                        "execution_count": content["execution_count"],
                    }

                elif msg_type == "error":
                    yield {
                        "type": "error",
                        "ename": content["ename"],
                        "evalue": content["evalue"],
                        "traceback": content["traceback"],
                    }

                elif msg_type == "status":
                    if content["execution_state"] == "idle":
                        yield {"type": "done"}
                        break

            except Exception as e:
                yield {
                    "type": "error",
                    "ename": "KernelTimeout",
                    "evalue": str(e),
                }
                break

    def interrupt(self):
        try:
            self.kc.interrupt()
        except Exception as exc:
            logging.warning("Kernel interrupt via control channel failed: %s", exc)
            if self._container:
                self._container.kill(signal="SIGINT")
        logging.info("Kernel interrupted")

    def restart(self):
        self.shutdown()
        self._security = security_runtime()
        runtime = kernel_runtime()
        self.packages = runtime["packages"]
        self.user_startup_code = runtime["startup_code"]
        self._key = _new_connection_key()
        self.kc = BlockingKernelClient()
        self._start_container()
        self._connect_client()
        self._wait_for_ready()
        self._inject_startup_config()
        logging.info("Kernel restarted")

    def shutdown(self):
        try:
            self.kc.stop_channels()
        except Exception:
            pass
        if self._container is not None:
            try:
                self._container.stop(timeout=5)
            except Exception:
                pass
            try:
                self._container.remove(force=True)
            except NotFound:
                pass
            except DockerException as exc:
                logging.warning("Failed to remove kernel container: %s", exc)
            self._container = None
        logging.info("Kernel shutdown")

    @staticmethod
    def available_kernels() -> list[str]:
        return [kernel_runtime()["kernel_spec_name"]]


# Backwards-compatible alias used by store/socket events.
SessionKernel = DockerKernel
