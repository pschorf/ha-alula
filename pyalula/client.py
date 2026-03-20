"""AlulaClient — async client for the Alula alarm panel API.

Authentication:  OAuth2 password grant  →  POST /oauth/token
Panel state:     REST polling            →  GET /rest/v1/devices
Zone state:      WebSocket request/reply →  wss://api.alula.net/ws/v1
Arm / disarm:    WebSocket write         →  wss://api.alula.net/ws/v1
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

import aiohttp

from .const import (
    ARM_LEVEL_AWAY,
    ARM_LEVEL_DISARM,
    ARM_LEVEL_NIGHT,
    ARM_LEVEL_STAY,
    BASE_URL,
    OAUTH_CLIENT_ID,
    OAUTH_CLIENT_SECRET,
    PATH_DEVICES_PANELS,
    PATH_TOKEN,
    REQUEST_TIMEOUT,
    TOKEN_REFRESH_BUFFER,
    WS_CHANNEL,
    WS_CONNECT_TIMEOUT,
    WS_RESPONSE_TIMEOUT,
    WS_URL,
    ZONE_BATCH_SIZE,
)

PATH_SELF = "/rest/v1/self"
from .models import AlarmPanel, ArmState, Zone, ZoneType

_LOGGER = logging.getLogger(__name__)


def _parse_device_type(device_type: str) -> "ZoneType":
    """Map Alula deviceType strings (e.g. 'DWS') to ZoneType enum."""
    t = device_type.upper()
    if t in ("DWS", "DOOR", "WINDOW"):
        return ZoneType.DOOR
    if t in ("PIR", "MOTION", "MD"):
        return ZoneType.MOTION
    if t in ("SMOKE", "SMOKE_DET"):
        return ZoneType.SMOKE
    if t in ("CO", "CO_DET"):
        return ZoneType.CO
    if t in ("GLASS", "GB", "GLASS_BREAK"):
        return ZoneType.GLASS_BREAK
    return ZoneType.OTHER


# Map public arm mode strings → byte codes the WebSocket expects
_ARM_MODE_MAP: dict[str, int] = {
    "disarm": ARM_LEVEL_DISARM,
    "stay": ARM_LEVEL_STAY,
    "home": ARM_LEVEL_STAY,
    "night": ARM_LEVEL_NIGHT,
    "away": ARM_LEVEL_AWAY,
}


class AlulaAuthError(Exception):
    """Invalid credentials or expired token."""


class AlulaApiError(Exception):
    """Unexpected API / network error."""


class AlulaClient:
    """Async client for the Alula alarm panel API.

    Usage::

        async with AlulaClient() as client:
            await client.login("user@example.com", "password")
            panel = await client.get_panel_status()
            print(panel.arm_state)
            await client.arm("away")
            await client.disarm()
    """

    def __init__(self, base_url: str = BASE_URL, ws_url: str = WS_URL) -> None:
        self._base_url = base_url.rstrip("/")
        self._ws_url = ws_url
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._ws_task: asyncio.Task | None = None
        self._ws_ready: asyncio.Event = asyncio.Event()

        # Token state
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._token_expires_at: float = 0.0
        self._user_id: str | None = None   # API user ID, needed for write commands

        # Latest zone data received from WebSocket
        self._zones: dict[str, Zone] = {}  # keyed by zone index string (0-based)
        self._zone_configs: dict[str, dict] = {}  # zone config data keyed by index

        # Latest arm state from virtualKeypadOutput push events
        self._ws_arm_state: "ArmState | None" = None

        # Panel metadata from panelDefinition (populated during init)
        self._max_zones: int = 64
        self._highest_zone_index: int | None = None  # from highestUsedIndexes

        # Panel id cache (filled after first get_panel_status)
        self._panel_id: str | None = None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> AlulaClient:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    async def close(self) -> None:
        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._session and not self._session.closed:
            await self._session.close()

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    async def login(self, username: str, password: str) -> None:
        """Authenticate with username/password and store the token."""
        data = await self._token_request({
            "grant_type": "password",
            "username": username,
            "password": password,
            "client_id": OAUTH_CLIENT_ID,
            "client_secret": OAUTH_CLIENT_SECRET,
        })
        self._store_token(data)
        _LOGGER.debug("Alula login OK, token expires in %ds", data.get("expires_in", 0))
        # Fetch user ID needed for write commands
        self._user_id = await self._fetch_user_id()

    async def _refresh_access_token(self) -> None:
        if not self._refresh_token:
            raise AlulaAuthError("No refresh token available — call login() first")
        _LOGGER.debug("Refreshing Alula access token")
        data = await self._token_request({
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token,
            "client_id": OAUTH_CLIENT_ID,
            "client_secret": OAUTH_CLIENT_SECRET,
        })
        self._store_token(data)

    def _store_token(self, data: dict) -> None:
        self._access_token = data["access_token"]
        expires_in: int = data.get("expires_in", 900)
        self._token_expires_at = time.monotonic() + expires_in
        self._refresh_token = data.get("refresh_token", self._refresh_token)

    async def _maybe_refresh_token(self) -> None:
        remaining = self._token_expires_at - time.monotonic()
        if remaining > TOKEN_REFRESH_BUFFER:
            return
        await self._refresh_access_token()

    async def _fetch_user_id(self) -> str | None:
        try:
            data = await self._get(self._base_url + PATH_SELF)
            uid = data.get("data", {}).get("id")
            _LOGGER.debug("Alula user ID: %s", uid)
            return uid
        except Exception as exc:
            _LOGGER.warning("Could not fetch user ID: %s", exc)
            return None

    async def _token_request(self, payload: dict) -> dict:
        url = self._base_url + PATH_TOKEN
        async with self._get_session().post(
            url,
            data=payload,
            headers={"Accept": "application/json"},
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
        ) as resp:
            if resp.status == 400:
                body = await resp.json()
                raise AlulaAuthError(
                    f"Auth failed: {body.get('error_description', body)}"
                )
            if not resp.ok:
                raise AlulaApiError(f"Token endpoint returned {resp.status}")
            return await resp.json()

    # ------------------------------------------------------------------
    # REST: panel status
    # ------------------------------------------------------------------

    async def get_panel_status(self, panel_id: str | None = None) -> AlarmPanel:
        """Return current panel arm state via REST polling.

        Also refreshes zone list from the last WebSocket data if available.
        """
        await self._maybe_refresh_token()
        url = self._base_url + PATH_DEVICES_PANELS
        data = await self._get(url)
        items = data.get("data", [])
        if not items:
            raise AlulaApiError("No panels found on this account")

        # If caller specified a panel_id, find it; otherwise use the first
        panel_data = next(
            (d for d in items if str(d.get("id")) == panel_id),
            items[0],
        )
        self._panel_id = str(panel_data["id"])
        zones = list(self._zones.values())
        panel = AlarmPanel.from_api(panel_data, zones=zones)
        # Override with fresher WS push state if available
        if self._ws_arm_state is not None:
            panel.arm_state = self._ws_arm_state
        return panel

    # ------------------------------------------------------------------
    # WebSocket: connect + receive loop
    # ------------------------------------------------------------------

    async def connect_ws(self) -> None:
        """Open the WebSocket, wait for ready, then subscribe to device channels."""
        await self._maybe_refresh_token()
        if self._ws and not self._ws.closed:
            return
        if not self._panel_id:
            raise AlulaApiError("Panel ID unknown — call get_panel_status() first")

        ws_url = f"{self._ws_url}?access_token={self._access_token}"
        _LOGGER.debug("Connecting Alula WebSocket: %s", self._ws_url)
        self._ws_ready = asyncio.Event()
        self._ws = await self._get_session().ws_connect(
            ws_url,
            timeout=aiohttp.ClientWSTimeout(ws_close=WS_CONNECT_TIMEOUT),
        )
        self._ws_task = asyncio.create_task(
            self._ws_receive_loop(), name="alula-ws-recv"
        )

        # Wait for the server's "ready" message before subscribing
        await asyncio.wait_for(self._ws_ready.wait(), timeout=WS_CONNECT_TIMEOUT)

        # Subscribe to device.status, device.helix, and device.keypad
        for channel in ("device.status", "device.helix", "device.keypad"):
            await self._ws_send({
                "channel": channel,
                "id": str(uuid.uuid4()),
                "subscribe": {"deviceId": self._panel_id},
            })

        # Enable virtual keypad push stream (triggers virtualKeypadOutput events)
        await self._ws_send({
            "channel": WS_CHANNEL,
            "id": str(uuid.uuid4()),
            "send": {
                "cmdrsp": "virtualKeypadInput",
                "deviceId": self._panel_id,
                "payload": {"enable": True},
                "requestId": str(uuid.uuid4()),
            },
        })

        # Request panel definition and highest used indexes so we know zone count
        await self._ws_send({
            "channel": WS_CHANNEL,
            "id": str(uuid.uuid4()),
            "send": {
                "cmdrsp": "requestMfd",
                "deviceId": self._panel_id,
                "payload": [
                    {"name": "panelDefinition"},
                    {"name": "highestUsedIndexes"},
                ],
                "requestId": str(uuid.uuid4()),
            },
        })

        # Allow panel time to respond with definition/indexes before zone requests
        await asyncio.sleep(WS_RESPONSE_TIMEOUT)

        _LOGGER.debug("Alula WebSocket connected and subscribed")

    async def _ws_receive_loop(self) -> None:
        """Background task: read WebSocket messages and dispatch them."""
        try:
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._handle_ws_message(msg.json())
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    _LOGGER.warning("Alula WebSocket error: %s", self._ws.exception())
                    break
                elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED):
                    break
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            _LOGGER.warning("Alula WebSocket receive loop died: %s", exc)
        finally:
            _LOGGER.debug("Alula WebSocket receive loop exited")

    async def _handle_ws_message(self, msg: dict) -> None:
        """Dispatch an incoming WebSocket message."""
        _LOGGER.debug("WS <<<: %s", msg)

        # "ready" message — signal that subscriptions can now be sent
        if msg.get("message") == "ready" and "sessionId" in msg:
            _LOGGER.debug("WS ready, sessionId=%s", msg.get("sessionId"))
            self._ws_ready.set()
            return

        # All other messages: ingest zone/arm state data
        self._ingest_zone_data(msg)

    def _ingest_zone_data(self, msg: dict) -> None:
        """Extract and cache zone/arm state from any WS message.

        Messages from the server arrive as:
          {"channel":"device.helix","id":"...","event":{"data":{"cmdrsp":"sendMfd","payload":[...]},...}}
        or for push events:
          {"channel":"device.helix","id":"...","event":{"data":{"cmdrsp":"virtualKeypadOutput","payload":{...}},...}}
        """
        # Unwrap event envelope
        event = msg.get("event", {})
        data = event.get("data", {})
        cmdrsp = data.get("cmdrsp", "")

        # sendMfd: response to requestMfd — payload is a list of named objects
        if cmdrsp == "sendMfd":
            for item in data.get("payload", []):
                self._ingest_named_payload(item)
            return

        # virtualKeypadOutput: pushed arm/display state from the panel
        if cmdrsp == "virtualKeypadOutput":
            kp = data.get("payload", {})
            if isinstance(kp, dict):
                self._update_arm_state_from_keypad(kp)
            return

        # Fallback: some servers push zone events at the top level (older firmware)
        self._ingest_named_payload(msg.get("payload", {}))

    def _ingest_named_payload(self, item: dict) -> None:
        """Parse a single payload entry from a sendMfd response.

        Entries use the items[] format:
          {"name": "zoneStatus", "indexFirst": 0, "indexLast": N,
           "items": [{"index": 0, "value": {...}}, ...]}
        """
        if not isinstance(item, dict):
            return
        name = item.get("name", "")

        if name == "zoneConfiguration":
            for entry in item.get("items", []):
                idx = str(entry.get("index", "?"))
                cfg = entry.get("value", {})
                if not cfg:
                    continue
                self._zone_configs[idx] = cfg
                # Propagate name/type to existing zone object
                if idx in self._zones:
                    self._zones[idx].name = cfg.get("zoneName", self._zones[idx].name)
                    self._zones[idx].zone_type = _parse_device_type(cfg.get("deviceType", ""))

        elif name == "zoneStatus":
            for entry in item.get("items", []):
                idx = str(entry.get("index", "?"))
                value = entry.get("value", {})
                if not value:
                    continue
                cfg = self._zone_configs.get(idx, {})
                if idx not in self._zones:
                    zone_name = cfg.get("zoneName") or f"Zone {int(idx) + 1:02d}"
                    self._zones[idx] = Zone(
                        id=idx,
                        name=zone_name,
                        zone_type=_parse_device_type(cfg.get("deviceType", "")),
                        is_open=False,
                    )
                self._zones[idx].is_open = bool(value.get("open", False))
                self._zones[idx].is_bypassed = bool(value.get("bypassed", False))
                self._zones[idx].raw = value

        elif name == "panelDefinition":
            value = item.get("value", {})
            max_zones = value.get("maxZones")
            if max_zones:
                self._max_zones = int(max_zones)
                _LOGGER.debug("Panel maxZones=%d", self._max_zones)

        elif name == "highestUsedIndexes":
            value = item.get("value", {})
            # May be under "value" key directly or as a named field
            zone_idx = value.get("zoneIndex", value.get("zone"))
            if zone_idx is not None:
                self._highest_zone_index = int(zone_idx)
                _LOGGER.debug("Highest used zone index=%d", self._highest_zone_index)

        elif name in ("zoneUpdate", "zoneFault", "zoneRestore"):
            # Single-zone push (legacy flat format)
            value = item.get("value", item)
            try:
                zone = Zone.from_ws(value if isinstance(value, dict) else item)
                self._zones[zone.id] = zone
            except Exception:
                pass

    def _update_arm_state_from_keypad(self, kp: dict) -> None:
        """Derive ArmState from a virtualKeypadOutput payload."""
        armed = kp.get("armed", False)
        stay = kp.get("stay", False)
        fire = kp.get("fire", False)
        alarmMemory = kp.get("alarmMemory", False)

        if fire or alarmMemory:
            self._ws_arm_state = ArmState.TRIGGERED
        elif not armed:
            self._ws_arm_state = ArmState.DISARMED
        elif stay:
            self._ws_arm_state = ArmState.ARMED_HOME
        else:
            self._ws_arm_state = ArmState.ARMED_AWAY
        _LOGGER.debug("WS arm state → %s (kp=%s)", self._ws_arm_state, kp)

    # ------------------------------------------------------------------
    # WebSocket: zone status request
    # ------------------------------------------------------------------

    async def fetch_zone_statuses(self, device_id: str | None = None) -> list[Zone]:
        """Request zone statuses over WebSocket and return the result.

        Requests zoneConfiguration+zoneStatus in batches of 3 (matching the
        web app's behaviour) so the panel firmware doesn't drop large responses.
        """
        dev_id = device_id or self._panel_id
        if not dev_id:
            raise AlulaApiError("Panel ID unknown — call get_panel_status() first")

        await self._ensure_ws()

        # Determine range to request
        max_index = self._highest_zone_index if self._highest_zone_index is not None \
            else self._max_zones - 1

        # Send batched requests (3 zones per batch, matching the web app)
        for first in range(0, max_index + 1, ZONE_BATCH_SIZE):
            last = min(first + ZONE_BATCH_SIZE - 1, max_index)
            inner = {
                "deviceId": dev_id,
                "cmdrsp": "requestMfd",
                "payload": [
                    {"name": "zoneConfiguration", "indexFirst": first, "indexLast": last},
                    {"name": "zoneStatus", "indexFirst": first, "indexLast": last},
                ],
                "requestId": str(uuid.uuid4()),
            }
            await self._ws_send({"channel": WS_CHANNEL, "id": str(uuid.uuid4()), "send": inner})

        # Wait for panel responses (arrive as pushed sendMfd events)
        await asyncio.sleep(WS_RESPONSE_TIMEOUT)

        return list(self._zones.values())

    # ------------------------------------------------------------------
    # WebSocket: arm / disarm
    # ------------------------------------------------------------------

    async def arm(self, mode: str, user_number: int = 0,
                  silent: bool = False, no_entry_delay: bool = False,
                  device_id: str | None = None) -> None:
        """Arm the panel.

        :param mode: 'away', 'home'/'stay', or 'night'
        :param user_number: helix user index (0 = master)
        :param silent: arm without sounding exit beeps
        :param no_entry_delay: bypass entry delay
        """
        level = _ARM_MODE_MAP.get(mode.lower())
        if level is None:
            raise ValueError(
                f"Invalid arm mode {mode!r}. Use: away, stay/home, night"
            )
        await self._send_arming_level(
            level, user_number, silent, no_entry_delay, device_id
        )

    async def disarm(self, pin: str | list[str],
                     silent: bool = False, no_entry_delay: bool = False,
                     device_id: str | None = None) -> None:
        """Disarm the panel.

        :param pin: user PIN code as a string ('1234') or list of digit strings (['1','2','3','4'])
        """
        dev_id = device_id or self._panel_id
        if not dev_id:
            raise AlulaApiError("Panel ID unknown — call get_panel_status() first")

        await self._ensure_ws()

        pin_digits = list(pin) if isinstance(pin, str) else [str(d) for d in pin]

        inner = {
            "deviceId": dev_id,
            "cmdrsp": "changeArmingLevelUsingCode",
            "payload": {
                "armingLevelValue": ARM_LEVEL_DISARM,
                "armSilent": silent,
                "noEntryDelay": no_entry_delay,
                "pin": pin_digits,
            },
            "requestId": str(uuid.uuid4()),
        }
        msg = {"channel": WS_CHANNEL, "id": str(uuid.uuid4()), "send": inner}
        await self._ws_send(msg)
        _LOGGER.debug("Sent changeArmingLevelUsingCode (disarm) to panel %s", dev_id)

    async def _send_arming_level(
        self,
        level: int,
        user_number: int,
        silent: bool,
        no_entry_delay: bool,
        device_id: str | None,
    ) -> None:
        dev_id = device_id or self._panel_id
        if not dev_id:
            raise AlulaApiError("Panel ID unknown — call get_panel_status() first")

        await self._ensure_ws()

        inner = {
            "deviceId": dev_id,
            "cmdrsp": "writeMfd",
            "payload": [{
                "name": "armingLevel",
                "value": {
                    "armingLevelValue": level,
                    "userNumber": user_number,
                    "armSilent": silent,
                    "noEntryDelay": no_entry_delay,
                },
            }],
            "requestId": self._user_id or str(uuid.uuid4()),
        }
        msg = {"channel": WS_CHANNEL, "id": str(uuid.uuid4()), "send": inner}
        await self._ws_send(msg)
        _LOGGER.debug("Sent armingLevel %d to panel %s", level, dev_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
            )
        return self._session

    def _auth_headers(self) -> dict[str, str]:
        if not self._access_token:
            raise AlulaAuthError("Not authenticated — call login() first")
        return {"Authorization": f"Bearer {self._access_token}"}

    async def _get(self, url: str) -> Any:
        headers = {**self._auth_headers(), "Accept": "application/json"}
        async with self._get_session().get(url, headers=headers) as resp:
            return await self._handle_response(resp)

    async def _ensure_ws(self) -> None:
        """Connect WebSocket if not already open."""
        await self._maybe_refresh_token()
        if self._ws is None or self._ws.closed:
            await self.connect_ws()

    async def _ws_send(self, msg: dict) -> None:
        if self._ws is None or self._ws.closed:
            raise AlulaApiError("WebSocket not connected")
        _LOGGER.debug("WS >>>: %s", msg)
        await self._ws.send_json(msg)

    @staticmethod
    async def _handle_response(resp: aiohttp.ClientResponse) -> Any:
        if resp.status == 401:
            raise AlulaAuthError("Alula API returned 401 — token invalid or expired")
        if not resp.ok:
            text = await resp.text()
            raise AlulaApiError(f"Alula API {resp.status}: {text[:200]}")
        return await resp.json()
