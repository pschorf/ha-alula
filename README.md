# Alula for Home Assistant

A [Home Assistant](https://www.home-assistant.io/) custom integration for [Alula](https://www.alula.com/) security alarm panels (Connect+, Helix, etc.).

## Features

- **Alarm control panel** entity with arm away, arm home, arm night, and disarm
- **Binary sensor** entities for each zone (doors, motion, glass break, smoke, CO)
- Near-instant state updates via WebSocket push events
- PIN code support for disarming

## Installation

### HACS (recommended)

1. Open HACS in your Home Assistant instance
2. Go to **Integrations** > three-dot menu > **Custom repositories**
3. Add `pschorf/ha-alula` as an **Integration**
4. Click **Install**
5. Restart Home Assistant

### Manual

Copy the `custom_components/alula` directory into your Home Assistant `custom_components/` folder and restart.

## Setup

After installation, go to **Settings > Devices & Services > Add Integration > Alula** and enter:

- **Email** -- your Alula account email
- **Password** -- your Alula account password
- **Panel ID** -- leave blank unless you have multiple panels on one account

## pyalula

The integration is powered by [pyalula](https://pypi.org/project/pyalula/), a standalone async Python client for the Alula API. It can also be used independently:

```python
from pyalula import AlulaClient

async with AlulaClient() as client:
    await client.login("user@example.com", "password")
    panel = await client.get_panel_status()
    print(panel.arm_state)
    await client.arm("away")
```

## Development

```bash
pip install -e ".[dev]"

# Library smoke test (requires real credentials):
ALULA_USER=you@example.com ALULA_PASS=secret python -m pyalula.smoke_test

# With debug logging:
DEBUG=1 ALULA_USER=you@example.com ALULA_PASS=secret python -m pyalula.smoke_test
```

## Disclaimer

This project is not affiliated with or endorsed by Alula. It uses the same API as the official Alula mobile app. Use at your own risk.

## License

MIT
