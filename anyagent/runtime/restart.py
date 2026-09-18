"""Coordinate a graceful server stop before the entrypoint replaces its process."""

from collections.abc import Callable
from uuid import uuid4

from anyagent.configs import load_cmd_config


class RestartController:
    def __init__(
        self, stop_server: Callable[[], None], *, port_override: int | None = None
    ):
        self.stop_server = stop_server
        self.port_override = port_override
        self.requested = False
        self.instance_id = uuid4().hex

    def request(self) -> int:
        """Reserve one restart and return the effective replacement server port."""
        if self.requested:
            raise RuntimeError("Restart already requested")
        port = self.port_override or load_cmd_config().server.port
        self.requested = True
        return port
