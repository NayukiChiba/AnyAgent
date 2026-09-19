"""Verify startup diagnostics and listener preflight checks."""

import socket
from types import SimpleNamespace

import pytest

from anyagent.runtime.startup import (
    ANYAGENT_BANNER,
    build_startup_display,
    check_listener_available,
    get_network_ipv4_addresses,
)


def test_startup_display_lists_default_access_urls():
    display = build_startup_display("127.0.0.1", 8000, frontend_ready=True)

    assert ANYAGENT_BANNER in display
    assert ".___________." in ANYAGENT_BANNER
    assert "`---|  |----`" in ANYAGENT_BANNER
    assert "AnyAgent v0.1.0  Frontend: ready" in display
    assert "Chat:     http://127.0.0.1:8000/" in display
    assert "Settings: http://127.0.0.1:8000/settings" in display
    assert "API Docs: http://127.0.0.1:8000/docs" in display


def test_wildcard_listener_lists_local_and_network_urls(monkeypatch):
    monkeypatch.setattr(
        "anyagent.runtime.startup.get_network_ipv4_addresses",
        lambda: ["10.0.0.2", "192.168.1.8"],
    )

    display = build_startup_display("0.0.0.0", 8080, frontend_ready=False)

    assert "Frontend: unavailable" in display
    assert "Chat:     http://127.0.0.1:8080/" in display
    assert "Network:  http://10.0.0.2:8080/" in display
    assert "Network:  http://192.168.1.8:8080/" in display


def test_network_addresses_are_filtered_deduplicated_and_sorted(monkeypatch):
    ipv4 = socket.AF_INET
    ipv6 = socket.AF_INET6
    monkeypatch.setattr(
        "anyagent.runtime.startup.psutil.net_if_addrs",
        lambda: {
            "loopback": [SimpleNamespace(family=ipv4, address="127.0.0.1")],
            "ethernet": [
                SimpleNamespace(family=ipv4, address="192.168.1.8"),
                SimpleNamespace(family=ipv6, address="::1"),
            ],
            "duplicate": [
                SimpleNamespace(family=ipv4, address="192.168.1.8"),
                SimpleNamespace(family=ipv4, address="10.0.0.2"),
            ],
        },
    )

    assert get_network_ipv4_addresses() == ["10.0.0.2", "192.168.1.8"]


def test_listener_preflight_accepts_available_port():
    with socket.socket() as temporary:
        temporary.bind(("127.0.0.1", 0))
        port = temporary.getsockname()[1]

    check_listener_available("127.0.0.1", port)


def test_listener_preflight_rejects_occupied_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]

        with pytest.raises(OSError):
            check_listener_available("127.0.0.1", port)
