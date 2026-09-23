"""Shared fixtures."""

import pytest


@pytest.fixture(autouse=True)
def _allow_localhost_sockets(request):
    """The simulated panel listens on 127.0.0.1; pytest-socket (pulled in by
    pytest-homeassistant-custom-component) would block it."""
    if request.config.pluginmanager.hasplugin("socket") or request.config.pluginmanager.hasplugin(
        "pytest_socket"
    ):
        request.getfixturevalue("socket_enabled")
