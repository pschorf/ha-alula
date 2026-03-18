"""Data models for the Alula API."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ArmState(str, Enum):
    DISARMED = "disarm"
    ARMED_HOME = "stay"
    ARMED_AWAY = "away"
    ARMED_NIGHT = "night"
    TRIGGERED = "triggered"

    @classmethod
    def from_api(cls, value: str) -> ArmState:
        """Parse armingLevel string from the REST API."""
        try:
            return cls(value.lower())
        except ValueError:
            return cls.DISARMED


class ZoneType(str, Enum):
    DOOR = "door"
    WINDOW = "window"
    MOTION = "motion"
    SMOKE = "smoke"
    CO = "co"
    GLASS_BREAK = "glass_break"
    OTHER = "other"


@dataclass
class Zone:
    id: str            # e.g. "1", "2" — zone index
    name: str
    zone_type: ZoneType
    is_open: bool      # True = faulted/open/triggered
    is_bypassed: bool = False
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_ws(cls, data: dict) -> Zone:
        """Parse a zone entry from a WebSocket zoneStatus response.

        The response shape is inferred from the smali; update if it differs:
        {
          "index": 1,
          "name": "Front Door",
          "type": "door",           # may be absent
          "open": true,
          "bypassed": false
        }
        """
        index = data.get("index", data.get("zoneIndex", data.get("id", "?")))
        return cls(
            id=str(index),
            name=data.get("name", data.get("zoneName", f"Zone {index}")),
            zone_type=_parse_zone_type(data.get("type", data.get("zoneType", ""))),
            is_open=bool(data.get("open", data.get("faulted", data.get("status", 0)))),
            is_bypassed=bool(data.get("bypassed", data.get("bypass", False))),
            raw=data,
        )


def _parse_zone_type(raw: str) -> ZoneType:
    mapping = {
        "door": ZoneType.DOOR,
        "window": ZoneType.WINDOW,
        "motion": ZoneType.MOTION,
        "smoke": ZoneType.SMOKE,
        "co": ZoneType.CO,
        "glass": ZoneType.GLASS_BREAK,
        "glass_break": ZoneType.GLASS_BREAK,
    }
    return mapping.get(str(raw).lower(), ZoneType.OTHER)


@dataclass
class AlarmPanel:
    id: str
    name: str
    arm_state: ArmState
    zones: list[Zone] = field(default_factory=list)
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_api(cls, data: dict, zones: list[Zone] | None = None) -> AlarmPanel:
        """Parse panel from REST GET /rest/v1/devices response data item."""
        attrs = data.get("attributes", data)
        arm_state = ArmState.from_api(attrs.get("armingLevel", "disarm"))
        return cls(
            id=str(data.get("id", "")),
            name=attrs.get("friendlyName", "Alula Panel"),
            arm_state=arm_state,
            zones=zones or [],
            raw=data,
        )
