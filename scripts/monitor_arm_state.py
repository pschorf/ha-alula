#!/usr/bin/env python3
"""Monitor arm state — logs REST polls and WS keypad pushes to verify no cycling.

Usage:
    export ALULA_USER='you@example.com'
    export ALULA_PASS='yourpassword'
    python scripts/monitor_arm_state.py

Polls REST every 30s and prints each keypad push as it arrives.
Ctrl-C to stop.
"""

import asyncio
import logging
import os
import signal
import sys
from datetime import datetime

# Allow running from project root without installing
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pyalula.client import AlulaClient  # noqa: E402

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)-7s %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
# Our own logger at DEBUG; suppress library noise
log = logging.getLogger("monitor")
log.setLevel(logging.DEBUG)

# Show pyalula keypad/arm debug lines
logging.getLogger("pyalula.client").setLevel(logging.DEBUG)

POLL_INTERVAL = 30  # seconds between REST polls


def ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


async def main() -> None:
    username = os.environ.get("ALULA_USER")
    password = os.environ.get("ALULA_PASS")
    if not username or not password:
        print("Set ALULA_USER and ALULA_PASS environment variables", file=sys.stderr)
        sys.exit(1)

    client = AlulaClient()
    stop = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    try:
        log.info("Logging in as %s …", username)
        await client.login(username, password)

        # Initial REST poll to discover panel
        panel = await client.get_panel_status()
        log.info("Panel: %s (id=%s)", panel.name, panel.id)
        log.info("[REST ] arm_state = %s", panel.arm_state.value)

        # Connect WS and subscribe
        await client.connect_ws()
        log.info("WebSocket connected")

        # Fetch zones once so we see the initial state
        zones = await client.fetch_zone_statuses()
        log.info("Got %d zones", len(zones))

        # Callback: keypad transition detected → immediate REST poll
        def on_arm_change() -> None:
            log.info("[KP   ] Transition detected — scheduling REST poll")
            asyncio.ensure_future(_poll_and_log(client))

        client.on_arm_state_change = on_arm_change

        # Poll loop
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=POLL_INTERVAL)
                break  # stop was set
            except asyncio.TimeoutError:
                pass  # poll interval elapsed
            await _poll_and_log(client)

    finally:
        log.info("Shutting down")
        await client.close()


async def _poll_and_log(client: AlulaClient) -> None:
    try:
        panel = await client.get_panel_status()
        log.info("[REST ] arm_state = %s", panel.arm_state.value)
    except Exception as exc:
        log.warning("[REST ] poll failed: %s", exc)


if __name__ == "__main__":
    asyncio.run(main())
