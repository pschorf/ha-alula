"""DataUpdateCoordinator for the Alula integration."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

try:
    from pyalula import AlulaClient, AlarmPanel
    from pyalula.client import AlulaAuthError, AlulaApiError
except ImportError:
    pass

_LOGGER = logging.getLogger(__name__)


class AlulaCoordinator(DataUpdateCoordinator["AlarmPanel"]):
    """Polls the Alula REST API and refreshes zone state via WebSocket."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: "AlulaClient",
        panel_id: str | None = None,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self._client = client
        self._panel_id = panel_id
        self._ws_connected = False

    async def _async_update_data(self) -> "AlarmPanel":
        """Fetch fresh panel + zone data."""
        try:
            # Poll arm state via REST (also caches panel ID needed for WS)
            panel = await self._client.get_panel_status(panel_id=self._panel_id)

            # Ensure WebSocket is up (zone state + arm/disarm commands)
            if not self._ws_connected:
                await self._client.connect_ws()
                self._ws_connected = True

            # Refresh zone state via WebSocket
            zones = await self._client.fetch_zone_statuses(device_id=panel.id)
            panel.zones = zones

            return panel

        except AlulaAuthError as err:
            self._ws_connected = False
            raise UpdateFailed(f"Alula authentication failed: {err}") from err
        except AlulaApiError as err:
            self._ws_connected = False
            raise UpdateFailed(f"Alula API error: {err}") from err
        except Exception as err:
            self._ws_connected = False
            raise UpdateFailed(f"Unexpected error: {err}") from err
