"""Diagnose the ITv2 connection to a Bentel Absoluta without Home Assistant.

Usage (from the repository root, or from <config>/custom_components/..):

    python3 scripts/diagnose.py <host> [--port 3064] [--pin 1234] [--full]

Without --pin only the TCP connection and the start of the handshake are
checked (the PIN is not needed). With --pin the login is attempted too, and
with --full discovery, labels and one status poll are run as well.
The PIN never appears in the output.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_components" / "bentel_absoluta"))

from itv2.client import (  # noqa: E402
    AbsolutaClient,
    AuthenticationFailed,
    ITv2Error,
)


class MaskPin(logging.Filter):
    """Hide the access code bytes of Enter Access Level (04 00 ...)."""

    _re = re.compile(r"(04 00 [0-9a-f]{2} 00 02 03) ([0-9a-f]{2} [0-9a-f]{2} [0-9a-f]{2})")

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = str(record.msg)
        if record.args:
            record.msg = record.msg % record.args
            record.args = ()
        record.msg = self._re.sub(r"\1 XX XX XX", record.msg)
        return True


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("host")
    ap.add_argument("--port", type=int, default=3064)
    ap.add_argument("--pin", default=None, help="user PIN (optional)")
    ap.add_argument("--full", action="store_true", help="also discovery + poll")
    args = ap.parse_args()

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(MaskPin())
    handler.setFormatter(logging.Formatter("%(relativeCreated)7.0f ms  %(message)s"))
    logging.basicConfig(level=logging.DEBUG, handlers=[handler])
    logging.getLogger("asyncio").setLevel(logging.WARNING)

    # Without a PIN we use a dummy one: the handshake is still fully tested,
    # the panel will simply refuse the login at the end.
    client = AbsolutaClient(args.host, args.pin or "0000", args.port, load_labels=args.full)
    print(f"== Connecting to {args.host}:{args.port}")
    code = 0
    try:
        await client.connect(discover=args.full)
        print("\n== OK: session established and logged in")
        info = client.info
        print(f"   model={info.model} firmware={info.firmware} mac={info.identifier}")
        print(f"   partitions={client.user_partitions} zones={client.user_zones}")
        if args.full:
            print(f"   outputs={client.outputs} remote_commands={client.remote_commands}")
            for p, s in sorted(client.partitions.items()):
                print(f"   partition {p} ({client.partition_labels.get(p, '')}): {s.raw.hex()}")
            for z, s in sorted(client.zones.items()):
                print(f"   zone {z} ({client.zone_labels.get(z, '')}): {s.raw:02x}")
    except AuthenticationFailed:
        if args.pin:
            print("\n== Handshake OK but the panel REJECTED THE PIN")
            code = 2
        else:
            print("\n== Handshake OK (login skipped: no --pin given)")
    except ITv2Error as err:
        print(f"\n== FAILED: {err}")
        code = 1
    finally:
        await client.disconnect()
    return code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
