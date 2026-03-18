"""Alarm control panel entity for Alula."""

from __future__ import annotations

import logging

from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    AlarmControlPanelEntityFeature,
    CodeFormat,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA_CLIENT, DATA_COORDINATOR, DOMAIN
from .coordinator import AlulaCoordinator

try:
    from pyalula import AlulaClient, AlarmPanel, ArmState
except ImportError:
    pass

_LOGGER = logging.getLogger(__name__)

# Map Alula ArmState → HA alarm state strings
_STATE_MAP: dict["ArmState", str] = {}  # filled after imports resolve at runtime


def _build_state_map() -> dict:
    from homeassistant.const import (
        STATE_ALARM_ARMED_AWAY,
        STATE_ALARM_ARMED_HOME,
        STATE_ALARM_ARMED_NIGHT,
        STATE_ALARM_DISARMED,
        STATE_ALARM_PENDING,
        STATE_ALARM_TRIGGERED,
    )
    return {
        ArmState.DISARMED: STATE_ALARM_DISARMED,
        ArmState.ARMED_AWAY: STATE_ALARM_ARMED_AWAY,
        ArmState.ARMED_HOME: STATE_ALARM_ARMED_HOME,
        ArmState.ARMED_NIGHT: STATE_ALARM_ARMED_NIGHT,
        ArmState.PENDING: STATE_ALARM_PENDING,
        ArmState.TRIGGERED: STATE_ALARM_TRIGGERED,
    }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Alula alarm control panel."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: AlulaCoordinator = data[DATA_COORDINATOR]
    client: AlulaClient = data[DATA_CLIENT]
    async_add_entities([AlulaAlarmPanel(coordinator, client, entry)])


class AlulaAlarmPanel(CoordinatorEntity[AlulaCoordinator], AlarmControlPanelEntity):
    """Representation of the Alula alarm panel."""

    _attr_has_entity_name = True
    _attr_name = None  # use device name as entity name
    _attr_code_format = CodeFormat.NUMBER
    _attr_code_arm_required = False  # set True if API requires code to arm
    _attr_supported_features = (
        AlarmControlPanelEntityFeature.ARM_AWAY
        | AlarmControlPanelEntityFeature.ARM_HOME
        | AlarmControlPanelEntityFeature.ARM_NIGHT
    )

    def __init__(
        self,
        coordinator: AlulaCoordinator,
        client: "AlulaClient",
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._client = client
        self._entry = entry
        self._state_map = _build_state_map()

    @property
    def unique_id(self) -> str:
        panel: AlarmPanel = self.coordinator.data
        return f"alula_{panel.id}_panel"

    @property
    def device_info(self) -> DeviceInfo:
        panel: AlarmPanel = self.coordinator.data
        return DeviceInfo(
            identifiers={(DOMAIN, panel.id)},
            name=panel.name,
            manufacturer="Alula",
        )

    @property
    def alarm_state(self) -> str | None:
        if self.coordinator.data is None:
            return None
        return self._state_map.get(self.coordinator.data.arm_state)

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        await self._client.disarm()
        await self.coordinator.async_request_refresh()

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        await self._client.arm("away")
        await self.coordinator.async_request_refresh()

    async def async_alarm_arm_home(self, code: str | None = None) -> None:
        await self._client.arm("stay")
        await self.coordinator.async_request_refresh()

    async def async_alarm_arm_night(self, code: str | None = None) -> None:
        await self._client.arm("night")
        await self.coordinator.async_request_refresh()
