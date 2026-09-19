"""Build startup diagnostics and verify the configured listener."""

import socket

import psutil

from anyagent import __version__

ANYAGENT_BANNER = r"""
     ___      .__   __. ____    ____  ___       _______  _______ .__   __. .___________.
    /   \     |  \ |  | \   \  /   / /   \     /  _____||   ____||  \ |  | |           |
   /  ^  \    |   \|  |  \   \/   / /  ^  \   |  |  __  |  |__   |   \|  | `---|  |----`
  /  /_\  \   |  . `  |   \_    _/ /  /_\  \  |  | |_ | |   __|  |  . `  |     |  |
 /  _____  \  |  |\   |     |  |  /  _____  \ |  |__| | |  |____ |  |\   |     |  |
/__/     \__\ |__| \__|     |__| /__/     \__\ \______| |_______||__| \__|     |__|
""".strip("\n")


def check_listener_available(host: str, port: int) -> None:
    """Verify that every address resolved for the listener can be bound."""
    for family, kind, protocol, _, address in socket.getaddrinfo(
        host, port, type=socket.SOCK_STREAM
    ):
        with socket.socket(family, kind, protocol) as listener:
            if family == socket.AF_INET6:
                listener.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            listener.bind(address)


def get_network_ipv4_addresses() -> list[str]:
    """Return unique non-loopback IPv4 addresses in display order."""
    addresses = {
        address.address
        for interface in psutil.net_if_addrs().values()
        for address in interface
        if address.family == socket.AF_INET
        and address.address != "0.0.0.0"
        and not address.address.startswith("127.")
    }
    return sorted(addresses)


def build_startup_display(host: str, port: int, *, frontend_ready: bool) -> str:
    """Build the multiline startup banner and user-facing access URLs."""
    display_host = "127.0.0.1" if host == "0.0.0.0" else host
    if ":" in display_host and not display_host.startswith("["):
        display_host = f"[{display_host}]"
    base_url = f"http://{display_host}:{port}"
    frontend_status = "ready" if frontend_ready else "unavailable"
    lines = [
        "",
        ANYAGENT_BANNER,
        "",
        f"  AnyAgent v{__version__}  Frontend: {frontend_status}",
        "",
        f"   ->  Chat:     {base_url}/",
        f"   ->  Settings: {base_url}/settings",
        f"   ->  API Docs: {base_url}/docs",
    ]
    if host == "0.0.0.0":
        lines.extend(
            f"   ->  Network:  http://{address}:{port}/"
            for address in get_network_ipv4_addresses()
        )
    return "\n".join(lines)
