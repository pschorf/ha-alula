"""Standalone smoke test for the pyalula library.

Usage:
    ALULA_USER=you@example.com ALULA_PASS=secret python -m pyalula.smoke_test

Optional:
    ALULA_ARM=1   — actually arm/disarm the panel (use with caution!)
"""

import asyncio
import os
import sys

from pyalula import AlulaClient


async def main() -> None:
    username = os.environ.get("ALULA_USER")
    password = os.environ.get("ALULA_PASS")
    do_arm = os.environ.get("ALULA_ARM") == "1"

    if not username or not password:
        print("Set ALULA_USER and ALULA_PASS environment variables.")
        sys.exit(1)

    async with AlulaClient() as client:
        print("1. Logging in...")
        await client.login(username, password)
        print("   OK")

        print("2. Fetching panel status (REST)...")
        panel = await client.get_panel_status()
        print(f"   Panel:     {panel.name} (id={panel.id})")
        print(f"   Arm state: {panel.arm_state.value}")

        print("3. Connecting WebSocket...")
        await client.connect_ws()
        print("   OK")

        print("4. Requesting zone statuses (WebSocket)...")
        zones = await client.fetch_zone_statuses()
        if zones:
            print(f"   {len(zones)} zones:")
            for zone in sorted(zones, key=lambda z: int(z.id) if z.id.isdigit() else 0):
                status = "OPEN" if zone.is_open else "closed"
                bypassed = " [bypassed]" if zone.is_bypassed else ""
                print(f"     [{zone.zone_type.value:12s}] {zone.name}: {status}{bypassed}")
        else:
            print("   No zone data received (WebSocket response format may need tuning)")
            print("   Check client._zones and inspect raw WS messages via DEBUG logging")

        if do_arm:
            print("5. Arming away...")
            await client.arm("away")
            await asyncio.sleep(3)
            panel = await client.get_panel_status()
            print(f"   Arm state: {panel.arm_state.value}")

            print("6. Disarming...")
            await client.disarm()
            await asyncio.sleep(3)
            panel = await client.get_panel_status()
            print(f"   Arm state: {panel.arm_state.value}")

    print("\nSmoke test complete.")


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.DEBUG if os.environ.get("DEBUG") else logging.WARNING)
    asyncio.run(main())
