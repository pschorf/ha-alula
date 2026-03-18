"""Alula alarm panel integration for Home Assistant."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .const import CONF_PANEL_ID, DATA_CLIENT, DATA_COORDINATOR, DOMAIN
from .coordinator import AlulaCoordinator

# Import pyalula from the sibling directory during development.
# In a published integration this would be a PyPI package.
try:
    from pyalula import AlulaClient
    from pyalula.client import AlulaAuthError, AlulaApiError
except ImportError as exc:
    raise ImportError(
        "pyalula library not found. Add the pyalula/ directory to PYTHONPATH "
        "or install it with: pip install -e /path/to/ha-alula"
    ) from exc

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.ALARM_CONTROL_PANEL, Platform.BINARY_SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Alula from a config entry."""
    username: str = entry.data[CONF_USERNAME]
    password: str = entry.data[CONF_PASSWORD]
    panel_id: str | None = entry.data.get(CONF_PANEL_ID)

    client = AlulaClient()
    try:
        await client.login(username, password)
    except AlulaAuthError as err:
        await client.close()
        raise ConfigEntryAuthFailed(f"Invalid credentials: {err}") from err
    except AlulaApiError as err:
        await client.close()
        raise ConfigEntryNotReady(f"Cannot connect to Alula API: {err}") from err

    coordinator = AlulaCoordinator(hass, client, panel_id=panel_id)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        DATA_CLIENT: client,
        DATA_COORDINATOR: coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        await data[DATA_CLIENT].close()
    return unload_ok
