"""Binary sensor entities — one per zone — for the Alula integration."""

from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import AlulaCoordinator

try:
    from pyalula import AlarmPanel, Zone, ZoneType
except ImportError:
    pass

_LOGGER = logging.getLogger(__name__)

# Map ZoneType → HA BinarySensorDeviceClass
_DEVICE_CLASS_MAP: dict["ZoneType", BinarySensorDeviceClass] = {
    ZoneType.DOOR: BinarySensorDeviceClass.DOOR,
    ZoneType.WINDOW: BinarySensorDeviceClass.WINDOW,
    ZoneType.MOTION: BinarySensorDeviceClass.MOTION,
    ZoneType.SMOKE: BinarySensorDeviceClass.SMOKE,
    ZoneType.CO: BinarySensorDeviceClass.CO,
    ZoneType.GLASS_BREAK: BinarySensorDeviceClass.VIBRATION,
    ZoneType.OTHER: BinarySensorDeviceClass.OPENING,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensors for each zone."""
    coordinator: AlulaCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]

    # Create entities for current zones; new zones after restart will appear
    # on the next HA reload (acceptable for v0.1).
    panel: AlarmPanel = coordinator.data
    async_add_entities(
        AlulaZoneSensor(coordinator, zone) for zone in panel.zones
    )


class AlulaZoneSensor(CoordinatorEntity[AlulaCoordinator], BinarySensorEntity):
    """Binary sensor representing a single Alula zone."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: AlulaCoordinator, zone: "Zone") -> None:
        super().__init__(coordinator)
        self._zone_id = zone.id
        self._attr_name = zone.name
        self._attr_unique_id = f"alula_zone_{zone.id}"
        self._attr_device_class = _DEVICE_CLASS_MAP.get(
            zone.zone_type, BinarySensorDeviceClass.OPENING
        )

    def _current_zone(self) -> "Zone | None":
        if self.coordinator.data is None:
            return None
        for zone in self.coordinator.data.zones:
            if zone.id == self._zone_id:
                return zone
        return None

    @property
    def is_on(self) -> bool | None:
        zone = self._current_zone()
        if zone is None:
            return None
        return zone.is_open

    @property
    def extra_state_attributes(self) -> dict:
        zone = self._current_zone()
        if zone is None:
            return {}
        return {"bypassed": zone.is_bypassed}

    @property
    def device_info(self) -> DeviceInfo:
        panel: AlarmPanel = self.coordinator.data
        return DeviceInfo(
            identifiers={(DOMAIN, panel.id)},
            name=panel.name,
            manufacturer="Alula",
        )

    @property
    def available(self) -> bool:
        return super().available and self._current_zone() is not None
