"""Constants for the Bentel Absoluta integration."""

from __future__ import annotations

from .itv2.const import DEFAULT_PORT  # noqa: F401

DOMAIN = "bentel_absoluta"
MANUFACTURER = "Bentel Security"

CONF_PIN = "pin"
CONF_POLL_INTERVAL = "poll_interval"
CONF_REQUIRE_CODE = "require_code"

DEFAULT_POLL_INTERVAL = 5
MIN_POLL_INTERVAL = 2
MAX_POLL_INTERVAL = 60

EVENT_BENTEL = f"{DOMAIN}_event"
