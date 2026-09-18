"""Coordinate a graceful server stop before the entrypoint replaces its process."""

import socket
from collections.abc import Callable
from uuid import uuid4

from anyagent.configs import load_cmd_config


class RestartController:
    def __init__(
        self,
        stop_server: Callable[[], None],
        *,
        port_override: int | None = None,
        host_override: str | None = None,
        current_host: str | None = None,
        current_port: int | None = None,
    ):
        self.stop_server = stop_server
        self.port_override = port_override
        self.host_override = host_override
        self.current_host = current_host
        self.current_port = current_port
        self.requested = False
        self.instance_id = uuid4().hex

    def _check_listener(self, host: str, port: int) -> None:
        if self.current_port is None or (
            host == self.current_host and port == self.current_port
        ):
            return
        # The current process owns its existing port; probe a changed host on port 0.
        probe_port = 0 if port == self.current_port else port
        for family, kind, protocol, _, address in socket.getaddrinfo(
            host, probe_port, type=socket.SOCK_STREAM
        ):
            with socket.socket(family, kind, protocol) as listener:
                if family == socket.AF_INET6:
                    listener.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
                listener.bind(address)

    def request(self) -> int:
        """Reserve one restart and return the effective replacement server port."""
        if self.requested:
            raise RuntimeError("Restart already requested")
        configured = load_cmd_config().server
        port = self.port_override or configured.port
        host = self.host_override or configured.host
        self._check_listener(host, port)
        self.requested = True
        return port
