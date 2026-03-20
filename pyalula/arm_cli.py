"""Command-line tool for testing Alula arm/disarm commands.

Usage:
    ALULA_USER=you@example.com ALULA_PASS=secret python -m pyalula.arm_cli status
    ALULA_USER=you@example.com ALULA_PASS=secret python -m pyalula.arm_cli arm away
    ALULA_USER=you@example.com ALULA_PASS=secret python -m pyalula.arm_cli arm stay
    ALULA_USER=you@example.com ALULA_PASS=secret python -m pyalula.arm_cli arm night
    ALULA_USER=you@example.com ALULA_PASS=secret python -m pyalula.arm_cli disarm
    ALULA_USER=you@example.com ALULA_PASS=secret python -m pyalula.arm_cli disarm --pin 1234
"""

import argparse
import asyncio
import getpass
import os
import sys

from pyalula import AlulaClient


async def get_status(client: AlulaClient) -> None:
    panel = await client.get_panel_status()
    await client.connect_ws()
    # Wait briefly for virtualKeypadOutput to arrive with fresh arm state
    await asyncio.sleep(2)
    panel = await client.get_panel_status()
    print(f"Panel:     {panel.name}")
    print(f"Arm state: {panel.arm_state.value}")


async def do_arm(client: AlulaClient, mode: str, wait: int) -> None:
    panel = await client.get_panel_status()
    await client.connect_ws()

    print(f"Current state: {panel.arm_state.value}")
    print(f"Arming {mode!r}...")
    await client.arm(mode)

    print(f"Waiting {wait}s for state change...")
    await asyncio.sleep(wait)

    panel = await client.get_panel_status()
    print(f"New state:     {panel.arm_state.value}")


async def do_disarm(client: AlulaClient, pin: str, wait: int) -> None:
    panel = await client.get_panel_status()
    await client.connect_ws()

    print(f"Current state: {panel.arm_state.value}")
    print("Disarming...")
    await client.disarm(pin=pin)

    print(f"Waiting {wait}s for state change...")
    await asyncio.sleep(wait)

    panel = await client.get_panel_status()
    print(f"New state:     {panel.arm_state.value}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Alula arm/disarm CLI")
    parser.add_argument(
        "command",
        choices=["status", "arm", "disarm"],
        help="Command to run",
    )
    parser.add_argument(
        "mode",
        nargs="?",
        choices=["away", "stay", "home", "night"],
        help="Arm mode (required for 'arm' command)",
    )
    parser.add_argument(
        "--pin",
        help="Disarm PIN code (prompted interactively if not provided)",
    )
    parser.add_argument(
        "--wait",
        type=int,
        default=15,
        help="Seconds to wait for state change confirmation (default: 15)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    if args.command == "arm" and not args.mode:
        parser.error("'arm' requires a mode: away, stay, home, or night")

    if args.debug or os.environ.get("DEBUG"):
        import logging
        logging.basicConfig(level=logging.DEBUG)

    username = os.environ.get("ALULA_USER")
    password = os.environ.get("ALULA_PASS")
    if not username or not password:
        print("Set ALULA_USER and ALULA_PASS environment variables.")
        sys.exit(1)

    pin = None
    if args.command == "disarm":
        pin = args.pin or getpass.getpass("PIN: ")
        if not pin.isdigit():
            print("PIN must be numeric.")
            sys.exit(1)

    async with AlulaClient() as client:
        await client.login(username, password)

        if args.command == "status":
            await get_status(client)
        elif args.command == "arm":
            await do_arm(client, args.mode, args.wait)
        elif args.command == "disarm":
            await do_disarm(client, pin, args.wait)


if __name__ == "__main__":
    asyncio.run(main())
